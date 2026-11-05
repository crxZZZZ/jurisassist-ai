"""Export only public legal snapshots, never contracts or user data."""

import json
from pathlib import Path

from jurisassist.ingestion import SOURCES
from jurisassist.models import Document
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def main():
    target = Path("corpus/snapshots")
    target.mkdir(parents=True, exist_ok=True)
    with Session(create_engine("sqlite:///data/migrations.db")) as db:
        for source_id, (_, url) in SOURCES.items():
            doc = db.scalar(
                select(Document)
                .where(Document.source_id == source_id, Document.kind == "law")
                .order_by(Document.created_at.desc())
            )
            if doc is None or doc.metadata_json.get("parser") != "legal-html-v2":
                raise SystemExit("Colete as fontes com o parser atual antes de exportar.")
            snapshot = {
                "source_id": source_id,
                "url": url,
                "title": doc.title,
                "collected_at": doc.created_at.isoformat(),
                "checksum": doc.checksum,
                "body": doc.body,
                "metadata": doc.metadata_json,
            }
            (target / f"{source_id}.json").write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"{source_id}: snapshot publico exportado")


if __name__ == "__main__":
    main()
