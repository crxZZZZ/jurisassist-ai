"""Run against a dedicated disposable database: never point TEST_DATABASE_URL at user data."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Requires disposable PostgreSQL + pgvector"
)
def test_postgres_migrations_vector_and_queue(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from conftest import TestEmbeddings
    from jurisassist.config import get_settings
    from jurisassist.db import get_engine, session_factory
    from jurisassist.ingestion import bootstrap_sources, index_document
    from jurisassist.jobs import claim_job
    from jurisassist.models import Document, Job, User, now
    from jurisassist.retrieval import search

    monkeypatch.setenv("JURIS_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    get_settings.cache_clear()
    get_engine.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    embeddings = TestEmbeddings()
    with session_factory()() as db:
        user = User(email="pg-test@local.invalid", name="PG test", password_hash="test-only")
        db.add(user)
        db.flush()
        bootstrap_sources(db)
        doc = Document(
            source_id="clt",
            title="Test CLT",
            kind="law",
            checksum="postgres-test",
            body="empregador empresa",
            approved_at=now(),
            metadata_json={
                "chunks": [
                    {
                        "locator": "Art. 2",
                        "text": "empregador empresa atividade econômica",
                        "metadata": {"article": "2"},
                    }
                ]
            },
        )
        db.add(doc)
        db.flush()
        index_document(db, doc, embeddings)
        db.add_all([Job(owner_id=user.id, kind="index"), Job(owner_id=user.id, kind="index")])
        db.commit()
        assert search(db, user.id, "empregador", mode="hybrid", embedder=embeddings)

    def claim():
        with session_factory()() as db:
            return claim_job(db)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: claim(), range(2)))
    assert len({result[0] for result in results}) == 2
    command.downgrade(Config("alembic.ini"), "base")
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()
