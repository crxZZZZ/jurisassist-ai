import hashlib
import io
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import select

from jurisassist.config import get_settings
from jurisassist.models import Chunk, Document, Source, now

SOURCES = {
    "clt": (
        "CLT · Consolidação das Leis do Trabalho",
        "https://www.planalto.gov.br/ccivil_03/decreto-lei/del5452compilado.htm",
    ),
    "terceirizacao": (
        "Lei nº 6.019/1974 · Trabalho temporário e terceirização",
        "https://www.planalto.gov.br/ccivil_03/leis/l6019.htm",
    ),
    "codigo-civil": (
        "Código Civil · Contratos e prestação de serviços",
        "https://www.planalto.gov.br/ccivil_03/leis/2002/l10406compilada.htm",
    ),
}
ARTICLE = re.compile(
    r"^\s*(?i:Art)\.\s*(\d+(?:\.\d{3})*)(?:\s*[º°o])?(?:\s*[-–]([A-Z])(?=[.\s]|$))?\.?\s*"
)


def clean_text(text: str) -> str:
    return re.sub(r"[ \t\xa0]+", " ", text).strip()


def parse_legal_html(raw: bytes) -> tuple[str, list[dict]]:
    # Planalto's legacy pages often omit a reliable charset. Statistical detection
    # can choose Windows-1250 and silently turn Portuguese accents into other letters.
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = raw.decode("windows-1252")
    soup = BeautifulSoup(decoded, "html.parser")
    for node in soup.select("script, style, s, strike, del"):
        node.decompose()
    for node in list(soup.find_all(style=True)):
        if "line-through" in node.get("style", ""):
            node.decompose()
    paragraphs = soup.find_all("p")
    lines = [clean_text(p.get_text(" ", strip=True)) for p in paragraphs if not p.find("p")]
    if not lines:
        lines = [clean_text(x) for x in soup.get_text("\n").splitlines()]
    lines = [line for line in lines if line]
    for index, line in enumerate(lines):
        if line == "CONSOLIDAÇÃO DAS LEIS DO TRABALHO":
            lines = lines[index + 1 :]
            break
    result, current = [], None
    for line in lines:
        match = ARTICLE.match(line)
        if match:
            article = match.group(1).rstrip(".") + (
                "-" + match.group(2).upper() if match.group(2) else ""
            )
            current = {"article": article, "parts": []}
            result.append(current)
        elif re.match(r"^(?:TÍTULO|CAPÍTULO|SEÇÃO|SUBSEÇÃO|ANEXO|QUADRO)\b", line, re.I) or (
            line.isupper() and len(line) < 250
        ):
            current = None
        if current is not None:
            # Keep amendment notes, but never index explicitly revoked dispositions.
            if re.search(r"\(\s*(?:revogad[oa]|vetado)", line, re.I):
                continue
            current["parts"].append(line)
    body = "\n".join(lines)
    chunks = []
    for entry in result:
        for index, part in enumerate(entry["parts"]):
            caput = entry["parts"][0] if entry["parts"] else ""
            prefix = caput + "\n" if index and len(caput) < 700 else ""
            for fragment in fragment_text(part, size=1000 - len(prefix)):
                fragment = prefix + fragment
                chunks.append(
                    {
                        "locator": f"Art. {entry['article']} · trecho {index + 1}",
                        "text": fragment,
                        "metadata": {
                            "article": entry["article"],
                            "context_added": bool(prefix),
                            "requires_temporal_review": bool(
                                re.search(r"vigência|produção de efeitos", fragment, re.I)
                            ),
                        },
                    }
                )
    return body, chunks


def fragment_text(text: str, size: int = 1000) -> list[str]:
    """Short passages fit the E5 512-token window; don't silently truncate articles."""
    words, result, current, length = text.split(), [], [], 0
    for word in words:
        if current and length + len(word) + 1 > size:
            result.append(" ".join(current))
            current, length = [], 0
        current.append(word)
        length += len(word) + 1
    if current:
        result.append(" ".join(current))
    return result


def contract_chunks(text: str) -> list[dict]:
    chunks = []
    for ordinal, fragment in enumerate(fragment_text(text)):
        chunks.append({"locator": f"Trecho {ordinal + 1}", "text": fragment, "metadata": {}})
    return chunks


def extract_upload(filename: str, raw: bytes) -> tuple[str, dict]:
    settings = get_settings()
    if not raw or len(raw) > settings.max_upload_bytes:
        raise ValueError("O arquivo deve conter dados e ter no máximo 10 MB.")
    extension = filename.rsplit(".", 1)[-1].lower()
    metadata = {"format": extension, "synthetic_only": True}
    if extension == "pdf":
        if not raw.startswith(b"%PDF-"):
            raise ValueError("O arquivo não é um PDF válido.")
        try:
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted:
                raise ValueError("PDF protegido por senha não é aceito.")
            if len(reader.pages) > settings.max_pages:
                raise ValueError("O limite é de 50 páginas.")
            texts = []
            for page in reader.pages:
                text = page.extract_text() or ""
                if not text.strip():
                    raise ValueError(
                        "PDF com página sem texto. Envie uma versão textual; OCR não está disponível."
                    )
                texts.append(text)
                if sum(map(len, texts)) > settings.max_document_chars:
                    raise ValueError("Texto muito extenso para esta versão.")
            body = "\n\n".join(texts)
            metadata["pages"] = len(reader.pages)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(
                "Não foi possível ler o PDF. Verifique a integridade do arquivo."
            ) from exc
    elif extension in {"txt", "md"}:
        try:
            body = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Salve o texto com codificação UTF-8.") from exc
        if "\x00" in body:
            raise ValueError("Arquivo binário não é aceito como texto.")
    else:
        raise ValueError("Formatos aceitos: PDF textual, TXT e Markdown.")
    if len(body.strip()) < 40 or len(body) > settings.max_document_chars:
        raise ValueError("O texto deve ter entre 40 e 180.000 caracteres.")
    return body.strip(), metadata


def bootstrap_sources(db, load_snapshots=False):
    for key, (title, url) in SOURCES.items():
        if db.get(Source, key) is None:
            db.add(Source(id=key, title=title, url=url))
    db.commit()
    if load_snapshots:
        for path in Path("corpus/snapshots").glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            source_id = data["source_id"]
            if source_id not in SOURCES or data["url"] != SOURCES[source_id][1]:
                raise ValueError("Snapshot com origem não autorizada.")
            if hashlib.sha256(data["body"].encode()).hexdigest() != data["checksum"]:
                raise ValueError("Checksum do snapshot inválido.")
            if db.scalar(select(Document.id).where(Document.source_id == source_id).limit(1)):
                continue
            collected = datetime.fromisoformat(data["collected_at"])
            db.add(
                Document(
                    source_id=source_id,
                    title=data["title"],
                    kind="law",
                    body=data["body"],
                    checksum=data["checksum"],
                    metadata_json={**data["metadata"], "bundled_snapshot": True},
                    status="pending_review",
                    created_at=collected,
                )
            )
            db.get(Source, source_id).checked_at = collected
        db.commit()


def fetch_source(db, source_id: str) -> Document | None:
    if source_id not in SOURCES:
        raise ValueError("Fonte não autorizada.")
    source = db.get(Source, source_id)
    if source is None:
        raise ValueError("Fonte não cadastrada.")
    # URLs cannot be supplied by users. Redirects are disallowed to prevent SSRF.
    with httpx.Client(timeout=45, follow_redirects=False) as client:
        with client.stream(
            "GET", SOURCES[source_id][1], headers={"User-Agent": "Mozilla/5.0"}
        ) as response:
            response.raise_for_status()
            content = bytearray()
            for part in response.iter_bytes():
                content.extend(part)
                if len(content) > 8 * 1024 * 1024:
                    raise ValueError("Fonte excedeu 8 MB.")
    body, chunks = parse_legal_html(bytes(content))
    if len(chunks) < 5 or "Art." not in body:
        raise ValueError("A estrutura da fonte mudou; revisão do parser necessária.")
    if source_id == "codigo-civil":
        chunks = [
            item
            for item in chunks
            if 421 <= int(item["metadata"]["article"].split("-")[0].replace(".", "")) <= 609
        ]
    checksum = hashlib.sha256(body.encode()).hexdigest()
    source.checked_at, source.check_error = now(), None
    existing = db.scalar(
        select(Document).where(Document.source_id == source_id, Document.checksum == checksum)
    )
    if existing:
        db.commit()
        return None
    for previous_candidate in db.scalars(
        select(Document).where(Document.source_id == source_id, Document.status == "pending_review")
    ):
        previous_candidate.status = "superseded"
    document = Document(
        title=source.title,
        kind="law",
        source_id=source_id,
        body=body,
        checksum=checksum,
        status="pending_review",
        metadata_json={
            "chunks": chunks,
            "url": source.url,
            "parser": "legal-html-v2",
            "review_note": "Conferir vigência, redações concorrentes e notas de alteração antes de aprovar.",
        },
    )
    db.add(document)
    db.commit()
    return document


def index_document(db, document: Document, embedder):
    if document.status in {"ready", "indexed", "retired"}:
        return
    if document.kind == "law" and document.approved_at is None:
        raise ValueError("Aprovação administrativa obrigatória.")
    chunks = (
        document.metadata_json.get("chunks")
        if document.kind == "law"
        else contract_chunks(document.body)
    )
    if not chunks:
        raise ValueError("Documento sem trechos indexáveis.")
    vectors = embedder.passages([x["text"] for x in chunks])
    if len(vectors) != len(chunks):
        raise ValueError("Quantidade inválida de embeddings.")
    # Index and retire the previous version in the same transaction.
    if document.source_id:
        db.get(Source, document.source_id, with_for_update=True)
        newer = db.scalar(
            select(Document.id)
            .where(
                Document.source_id == document.source_id,
                Document.approved_at > document.approved_at,
                Document.status.in_(["indexed", "indexing"]),
            )
            .limit(1)
        )
        if newer:
            document.status = "superseded"
            return
        for previous in db.scalars(
            select(Document).where(
                Document.source_id == document.source_id, Document.status == "indexed"
            )
        ):
            previous.status = "retired"
    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
        db.add(
            Chunk(
                document_id=document.id,
                ordinal=index,
                locator=chunk["locator"],
                text=chunk["text"],
                metadata_json=chunk["metadata"],
                embedding=vector,
            )
        )
    document.status = "indexed" if document.kind == "law" else "ready"
    document.embedding_model = get_settings().embeddings_model
    db.flush()


def due_sources(db):
    cutoff = now() - timedelta(hours=get_settings().source_check_hours)
    return list(
        db.scalars(
            select(Source).where((Source.checked_at.is_(None)) | (Source.checked_at < cutoff))
        )
    )
