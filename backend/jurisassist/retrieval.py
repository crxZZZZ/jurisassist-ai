import re
import time
import unicodedata
from datetime import timedelta
from functools import lru_cache

import numpy as np
import snowballstemmer
from rank_bm25 import BM25Okapi
from sqlalchemy import func, select

from jurisassist import telemetry
from jurisassist.config import get_settings
from jurisassist.models import Chunk, Document, Source, now

STOP_WORDS = {
    "para",
    "como",
    "uma",
    "que",
    "dos",
    "das",
    "com",
    "por",
    "quais",
    "qual",
    "quem",
    "sobre",
    "previsto",
    "prevista",
    "previstos",
    "previstas",
    "deve",
    "devem",
    "pode",
    "podem",
    "ser",
    "são",
    "sao",
    "seu",
    "sua",
    "essa",
    "esse",
    "isso",
    "esta",
    "este",
    "existe",
    "funciona",
    "verificar",
    "revisar",
}
_stemmer = snowballstemmer.stemmer("portuguese")


class Embeddings:
    def __init__(self):
        from jurisassist.onnx_models import E5Encoder

        settings = get_settings()
        if settings.embeddings_model != "intfloat/multilingual-e5-small":
            raise ValueError("Troca de embeddings exige implementação e reindexação explícitas.")
        self.model = E5Encoder(settings.data_dir / "models")

    def passages(self, texts: list[str]) -> list[list[float]]:
        return self.model.embed(["passage: " + text for text in texts])

    def query(self, text: str) -> list[float]:
        return self.model.embed(["query: " + text])[0]


@lru_cache
def get_embeddings():
    return Embeddings()


def words(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z0-9]+", normalized) if len(w) > 2} - STOP_WORDS


def lexical_tokens(value: str) -> list[str]:
    tokens = [
        t for t in re.findall(r"[a-zà-ÿ0-9]+", value.lower()) if len(t) > 2 and t not in STOP_WORDS
    ]
    return _stemmer.stemWords(tokens)


@lru_cache(maxsize=4)
def lexical_index(rows: tuple[tuple[str, str], ...]):
    return BM25Okapi([lexical_tokens(text) or ["__empty__"] for _, text in rows])


def allowed_documents(owner_id: str, document_id: str | None = None):
    if document_id:
        return (
            (Document.id == document_id)
            & (Document.owner_id == owner_id)
            & (Document.status == "ready")
        )
    return (Document.kind == "law") & (Document.status == "indexed")


def citation(db, chunk: Chunk) -> dict:
    doc = db.get(Document, chunk.document_id)
    source = db.get(Source, doc.source_id) if doc.source_id else None
    return {
        "id": chunk.id,
        "document_id": doc.id,
        "title": doc.title,
        "locator": chunk.locator,
        "text": chunk.text,
        "kind": doc.kind,
        "url": source.url if source else None,
        "version": doc.checksum[:12],
        "collected_at": doc.created_at.isoformat(),
        "checked_at": source.checked_at.isoformat() if source and source.checked_at else None,
    }


def search(
    db, owner_id: str, query: str, mode="hybrid", limit=5, document_id=None, embedder=None
) -> list[dict]:
    if mode not in {"text", "vector", "hybrid"}:
        raise ValueError("Modo de busca inválido.")
    start = time.perf_counter()
    authorized = allowed_documents(owner_id, document_id)
    base = select(Chunk).join(Document).where(authorized)
    rankings = []
    if mode in {"text", "hybrid"}:
        # IDF is computed only on the authorized corpus. A bounded cache is enough
        # for the initial three-law collection; large corpora need a search service.
        rows = db.execute(
            select(Chunk.id, Chunk.text).join(Document).where(authorized).order_by(Chunk.id)
        )
        corpus = tuple((row[0], row[1]) for row in rows)
        eligible = None
        if db.bind.dialect.name == "postgresql":
            vector = func.to_tsvector("portuguese", Chunk.text)
            tsquery = func.websearch_to_tsquery("portuguese", " OR ".join(sorted(words(query))))
            eligible = set(
                db.scalars(
                    select(Chunk.id).join(Document).where(authorized, vector.op("@@")(tsquery))
                )
            )
        found = []
        if corpus:
            scores = lexical_index(corpus).get_scores(lexical_tokens(query))
            ids = [
                corpus[index][0]
                for index in np.argsort(scores)[::-1]
                if scores[index] > 0 and (eligible is None or corpus[index][0] in eligible)
            ][:40]
            found = [db.get(Chunk, identifier) for identifier in ids]
        rankings.append(found)
    if mode in {"vector", "hybrid"}:
        embedding = (embedder or get_embeddings()).query(query)
        compatible = base.where(
            Document.embedding_model == get_settings().embeddings_model,
            Chunk.embedding.is_not(None),
        )
        if db.bind.dialect.name == "postgresql":
            found = list(
                db.scalars(
                    compatible.order_by(Chunk.embedding.cosine_distance(embedding)).limit(40)
                )
            )
        else:
            found = list(db.scalars(compatible))
            found.sort(
                key=lambda c: -sum(a * b for a, b in zip(c.embedding, embedding, strict=True))
            )
            found = found[:40]
        rankings.append(found)
    scores, objects = {}, {}
    for ranking_index, ranking in enumerate(rankings):
        for rank, chunk in enumerate(ranking):
            weight = 1.5 if mode == "hybrid" and ranking_index == 1 else 1.0
            scores[chunk.id] = scores.get(chunk.id, 0) + weight / (30 + rank + 1)
            objects[chunk.id] = chunk
    ordered, seen = [], set()
    for key in sorted(scores, key=scores.get, reverse=True):
        chunk = objects[key]
        group = (chunk.document_id, chunk.metadata_json.get("article", chunk.id))
        if group in seen:
            continue
        seen.add(group)
        ordered.append(key)
        if len(ordered) >= limit:
            break
    telemetry.retrieval.labels(mode).observe(time.perf_counter() - start)
    return [citation(db, objects[key]) for key in ordered]


def get_article(db, source_id: str, article: str) -> list[dict]:
    normalized = re.sub(r"^Art\.\s*", "", article, flags=re.I).strip(" .º°")
    chunks = db.scalars(
        select(Chunk)
        .join(Document)
        .where(Document.source_id == source_id, Document.status == "indexed")
        .order_by(Chunk.ordinal)
    )
    return [citation(db, c) for c in chunks if c.metadata_json.get("article") == normalized][:8]


def basis_state(db) -> dict:
    sources = list(db.scalars(select(Source)))
    pending = bool(
        db.scalar(
            select(Document.id)
            .where(Document.kind == "law", Document.status.in_(["pending_review", "indexing"]))
            .limit(1)
        )
    )
    indexed = len(
        list(
            db.scalars(
                select(Document.id).where(Document.kind == "law", Document.status == "indexed")
            )
        )
    )
    cutoff = now() - timedelta(days=get_settings().source_stale_days)
    stale = any(s.checked_at is None or s.checked_at < cutoff or s.check_error for s in sources)
    return {
        "indexed_sources": indexed,
        "expected_sources": len(sources),
        "pending_update": pending,
        "stale": stale,
        "warning": "Há atualização pendente de revisão."
        if pending
        else "Confira a data das fontes antes de usar a resposta."
        if stale
        else None,
    }
