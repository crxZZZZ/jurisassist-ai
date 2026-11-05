"""Real model smoke test; uses only an isolated benchmark database and synthetic data."""

import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

from jurisassist.ai import analyze_contract
from jurisassist.config import get_settings
from jurisassist.db import session_factory
from jurisassist.ingestion import index_document
from jurisassist.models import Document, User
from jurisassist.retrieval import get_embeddings
from jurisassist.samples import SAMPLES
from jurisassist.security import hasher


def main():
    if not get_settings().database_url.endswith("/jurisassist_benchmark"):
        raise SystemExit("Este teste exige o banco descartável jurisassist_benchmark.")
    with session_factory()() as db:
        user = User(
            email=f"smoke-{uuid4()}@local.invalid",
            name="Smoke test",
            password_hash=hasher.hash(str(uuid4())),
        )
        db.add(user)
        db.flush()
        title, _, body = SAMPLES["servicos-ti"]
        doc = Document(
            owner_id=user.id,
            title=title,
            kind="contract",
            body=body,
            checksum=hashlib.sha256(body.encode()).hexdigest(),
            metadata_json={},
        )
        db.add(doc)
        db.flush()
        index_document(db, doc, get_embeddings())
        started = time.perf_counter()
        result = analyze_contract(
            db, user.id, doc.id, progress=lambda stage: print(stage, flush=True)
        )
        payload = {"seconds": round(time.perf_counter() - started, 2), "result": result}
        Path("reports").mkdir(exist_ok=True)
        Path("reports/model-contract-smoke.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "seconds": payload["seconds"],
                    "findings": len(result["findings"]),
                    "coverage": result["coverage"],
                    "citations": len(result["citations"]),
                }
            )
        )
        db.rollback()


if __name__ == "__main__":
    main()
