import hashlib
import json
import statistics
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from jurisassist.ai import analyze_contract, prompt, research_chat
from jurisassist.config import get_settings
from jurisassist.db import session_factory
from jurisassist.ingestion import index_document
from jurisassist.models import Chunk, Document, User, now
from jurisassist.retrieval import basis_state, get_embeddings, search
from jurisassist.security import hasher

ROOT = Path(__file__).resolve().parents[2]


def cases_path():
    candidates = [Path("evaluation/cases.jsonl"), ROOT / "evaluation/cases.jsonl"]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        "evaluation/cases.jsonl não encontrado. Execute na raiz do repositório."
    )


def load_cases():
    return [
        json.loads(line)
        for line in cases_path().read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def reports_dir():
    return get_settings().data_dir / "evaluations"


def read_reports():
    reports = []
    for path in sorted(reports_dir().glob("*.json"), reverse=True)[:30]:
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
            reports.append({k: v for k, v in result.items() if k != "cases"})
        except (ValueError, OSError):
            continue
    return reports


def evaluate(mode="hybrid", version="v2", generate=False, gateway=None):
    rows, hits, latencies = [], [], []
    with session_factory()() as db:
        if basis_state(db)["indexed_sources"] < 3:
            raise ValueError(
                "Aprove e indexe as três fontes antes de avaliar. Base incompleta não gera um benchmark válido."
            )
        corpus_snapshot = [
            {
                "source_id": d.source_id,
                "checksum": d.checksum,
                "parser": d.metadata_json.get("parser"),
                "embedding_model": d.embedding_model,
            }
            for d in db.scalars(
                select(Document).where(Document.kind == "law", Document.status == "indexed")
            )
        ]
        user = User(
            email=f"eval-{uuid4()}@local.invalid",
            name="Avaliador temporário",
            password_hash=hasher.hash(str(uuid4())),
        )
        db.add(user)
        db.flush()
        for case in load_cases():
            started = time.perf_counter()
            row = {"id": case["id"], "category": case["category"], "manual_review": "pending"}
            if "source" in case:
                found = search(db, user.id, case["question"], mode=mode)
                matched = []
                for evidence in found:
                    chunk = db.get(Chunk, evidence["id"])
                    document = db.get(Document, chunk.document_id)
                    matched.append(
                        document.source_id == case["source"]
                        and chunk.metadata_json.get("article") == case["article"]
                    )
                hit = any(matched)
                hits.append(hit)
                row.update({"retrieval_hit": hit, "retrieved_ids": [c["id"] for c in found]})
            if generate:
                if case["category"] == "contract":
                    doc = Document(
                        owner_id=user.id,
                        title=case["id"],
                        kind="contract",
                        body=case["contract"],
                        checksum=hashlib.sha256(case["contract"].encode()).hexdigest(),
                        metadata_json={},
                    )
                    db.add(doc)
                    db.flush()
                    index_document(db, doc, get_embeddings())
                    result = analyze_contract(
                        db, user.id, doc.id, gateway=gateway, mode=mode, version=version
                    )
                else:
                    result = research_chat(
                        db, user.id, case["question"], gateway=gateway, mode=mode, version=version
                    )
                serialized = json.dumps(result, ensure_ascii=False)
                row["result"] = result
                row["status_pass"] = (
                    result.get("status") in case["expected_status"]
                    if "expected_status" in case
                    else None
                )
                row["forbidden_absent"] = (
                    case.get("forbidden", "__no_forbidden_marker__") not in serialized
                    if case["category"] == "adversarial"
                    else None
                )
                row["citation_integrity"] = all(
                    db.get(Chunk, c["id"]) is not None for c in result.get("citations", [])
                )
            duration = round(time.perf_counter() - started, 3)
            if generate or "source" in case:
                latencies.append(duration)
            row["duration_seconds"] = duration
            rows.append(row)
        # No evaluation users, contracts or conversations survive the run.
        db.rollback()
    identifier = now().strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    report = {
        "id": identifier,
        "created_at": now().isoformat(),
        "mode": mode,
        "prompt_version": version,
        "model": get_settings().model,
        "embedding_model": get_settings().embeddings_model,
        "embedding_revision": "761b726dd34fb83930e26aab4e9ac3899aa1fa78",
        "prompt_sha256": hashlib.sha256(prompt(version).encode()).hexdigest(),
        "corpus": corpus_snapshot,
        "retrieval_revision": "bm25-pt-rrf-1.5-diverse-v1",
        "generation": generate,
        "inventory_cases": len(rows),
        "evaluated": len(rows) if generate else len(hits),
        "generation_cases": len(rows) if generate else 0,
        "retrieval_cases": len(hits),
        "recall_at_5": sum(hits) / len(hits) if hits else None,
        "retrieval_target_met": bool(hits) and sum(hits) / len(hits) >= 0.9,
        "p50_seconds": statistics.median(latencies),
        "p95_seconds": sorted(latencies)[int(0.95 * (len(latencies) - 1))],
        "parameters": {"temperature": 0, "num_ctx": 8192, "num_predict": 2200},
        "manual_review_status": "pending",
        "cases": rows,
    }
    reports_dir().mkdir(parents=True, exist_ok=True)
    (reports_dir() / f"{identifier}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
