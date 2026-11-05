"""Non-production experiment on the dedicated benchmark database; requires the real model.

Imports official snapshots already collected into the application's local SQLite QA store.
Approval here is a technical fixture, NOT legal review or approval of the application's corpus.
"""

import argparse
import json

from alembic import command
from alembic.config import Config
from jurisassist.config import get_settings
from jurisassist.db import session_factory
from jurisassist.ingestion import bootstrap_sources, index_document
from jurisassist.models import Document, now
from jurisassist.retrieval import get_embeddings
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--import-sqlite", default="sqlite:///data/migrations.db")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_url.endswith("/jurisassist_benchmark"):
        raise SystemExit(
            "Use exclusivamente o banco descartável jurisassist_benchmark via JURIS_DATABASE_URL."
        )
    command.upgrade(Config("alembic.ini"), "head")
    with session_factory()() as db:
        bootstrap_sources(db)
        with Session(create_engine(args.import_sqlite)) as source_db:
            for source in ["clt", "terceirizacao", "codigo-civil"]:
                original = source_db.scalar(
                    select(Document)
                    .where(Document.source_id == source)
                    .order_by(Document.created_at.desc())
                )
                if original is None:
                    raise SystemExit("Colete os snapshots oficiais antes de importar.")
                exists = db.scalar(
                    select(Document).where(
                        Document.source_id == source, Document.checksum == original.checksum
                    )
                )
                if exists:
                    continue
                doc = Document(
                    title=original.title,
                    kind="law",
                    source_id=source,
                    body=original.body,
                    checksum=original.checksum,
                    metadata_json=original.metadata_json,
                    approved_at=now(),
                )
                db.add(doc)
                db.flush()
                index_document(db, doc, get_embeddings())
                db.commit()
                print(
                    json.dumps({"source": source, "chunks": len(original.metadata_json["chunks"])}),
                    flush=True,
                )


if __name__ == "__main__":
    main()
