import hashlib
import math

import pytest
from fastapi.testclient import TestClient
from jurisassist.config import get_settings
from jurisassist.db import Base, get_engine, session_factory
from jurisassist.ingestion import bootstrap_sources, index_document
from jurisassist.models import Document, User, now
from jurisassist.security import hasher
from sqlalchemy import select


class TestEmbeddings:
    """Deterministic test double. Never used by the application or real evaluations."""

    __test__ = False

    def query(self, value):
        from jurisassist.retrieval import words

        vector = [0.0] * 384
        for word in words(value):
            index = int(hashlib.sha256(word.encode()).hexdigest()[:8], 16) % 384
            vector[index] += 1
        norm = math.sqrt(sum(x * x for x in vector)) or 1
        return [x / norm for x in vector]

    def passages(self, texts):
        return [self.query(x) for x in texts]


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIS_DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("JURIS_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    get_engine.cache_clear()
    Base.metadata.create_all(get_engine())
    with session_factory()() as db:
        db.add_all(
            [
                User(
                    id="alice",
                    email="alice@example.test",
                    name="Alice",
                    role="admin",
                    password_hash=hasher.hash("test-password-123"),
                ),
                User(
                    id="bob",
                    email="bob@example.test",
                    name="Bob",
                    role="user",
                    password_hash=hasher.hash("test-password-456"),
                ),
            ]
        )
        db.commit()
        bootstrap_sources(db)
    yield
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def client(database):
    from jurisassist.api import create_app

    with TestClient(create_app()) as c:
        yield c


def authenticate(client, email="alice@example.test", password="test-password-123"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


@pytest.fixture
def alice(client):
    return authenticate(client)


@pytest.fixture
def embedder():
    return TestEmbeddings()


@pytest.fixture
def corpus(database, embedder, monkeypatch):
    import jurisassist.retrieval as retrieval

    monkeypatch.setattr(retrieval, "get_embeddings", lambda: embedder)
    with session_factory()() as db:
        for source, article, content in [
            (
                "clt",
                "2",
                "Art. 2º Considera-se empregador a empresa que assume os riscos da atividade econômica, admite, assalaria e dirige a prestação pessoal de serviço.",
            ),
            (
                "terceirizacao",
                "5-A",
                "Art. 5º-A A empresa contratante é subsidiariamente responsável pelas obrigações trabalhistas referentes ao período em que ocorrer a prestação de serviços.",
            ),
            (
                "codigo-civil",
                "422",
                "Art. 422. Os contratantes são obrigados a guardar os princípios de probidade e boa-fé na conclusão e execução do contrato.",
            ),
        ]:
            document = Document(
                title=source,
                source_id=source,
                kind="law",
                body=content,
                checksum=hashlib.sha256(content.encode()).hexdigest(),
                approved_at=now(),
                metadata_json={
                    "chunks": [
                        {
                            "locator": f"Art. {article}",
                            "text": content,
                            "metadata": {"article": article},
                        }
                    ]
                },
            )
            db.add(document)
            db.flush()
            index_document(db, document, embedder)
        db.commit()
        for source in db.scalars(select(retrieval.Source)):
            source.checked_at = now()
        db.commit()


class GoodGateway:
    def request(self, messages, schema=None, tools=None):
        return {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "get_article",
                        "arguments": {"source_id": "clt", "article": "2"},
                    }
                }
            ],
        }

    def structured(self, messages, schema, **_kwargs):
        import json

        from jurisassist.schemas import QueryIntent

        if schema is QueryIntent:
            return schema(action="research")

        data = json.loads(
            next(
                m["content"]
                for m in messages
                if m["role"] == "user" and m["content"].startswith("{")
            )
        )
        if "untrusted_evidence" in data:
            return schema.model_validate(
                {
                    "status": "answered",
                    "summary": "Veja o fundamento consultado.",
                    "claims": [
                        {
                            "text": data["untrusted_evidence"][0]["text"],
                            "citation_ids": [data["untrusted_evidence"][0]["id"]],
                        }
                    ],
                }
            )
        clause, law = data["untrusted_contract"][0], data["untrusted_law"][0]
        return schema.model_validate(
            {
                "summary": "Contrato fictício de serviços.",
                "obligations": [
                    {"text": "Conferir a obrigação contratual.", "citation_ids": [clause["id"]]}
                ],
                "deadlines": [],
                "findings": [
                    {
                        "title": "Responsabilidade",
                        "detail": "Conferir a distribuição de responsabilidades.",
                        "priority": "high",
                        "contract_chunk_id": clause["id"],
                        "quote": clause["text"][:80],
                        "citation_ids": [law["id"]],
                        "checklist": "Revisar a cláusula com o jurídico.",
                    }
                ],
            }
        )


@pytest.fixture
def gateway():
    return GoodGateway()
