import logging
import signal
import threading
import time
from contextlib import contextmanager

import httpx
from prometheus_client import start_http_server
from sqlalchemy import select

from jurisassist import telemetry
from jurisassist.ai import InvalidEvidence, ModelUnavailable, analyze_contract, research_chat
from jurisassist.config import get_settings
from jurisassist.db import session_factory
from jurisassist.ingestion import due_sources, fetch_source, index_document
from jurisassist.jobs import claim_job, renew_lease
from jurisassist.models import Analysis, Document, Job, Message, Source, now
from jurisassist.retrieval import get_embeddings

log = logging.getLogger(__name__)


@contextmanager
def heartbeat(job_id, token):
    stop = threading.Event()

    def tick():
        while not stop.wait(20):
            try:
                with session_factory()() as db:
                    if not renew_lease(db, job_id, token):
                        return
            except Exception:
                log.warning("lease_renewal_failed", extra={"job_id": job_id})

    thread = threading.Thread(target=tick, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=3)


def process_one(gateway=None, embedder=None):
    with session_factory()() as db:
        claimed = claim_job(db)
    if claimed is None:
        return False
    job_id, token = claimed

    def progress(stage):
        with session_factory()() as db:
            job = db.get(Job, job_id)
            if job.lock_token == token:
                job.stage, job.updated_at = stage, now()
                db.commit()

    try:
        with heartbeat(job_id, token), session_factory()() as db:
            job = db.get(Job, job_id)
            if job.kind == "chat":
                history = list(
                    db.scalars(
                        select(Message)
                        .where(Message.conversation_id == job.payload["conversation_id"])
                        .order_by(Message.created_at.desc())
                        .limit(6)
                    )
                )
                result = research_chat(
                    db,
                    job.owner_id,
                    job.payload["question"],
                    [
                        {"role": m.role, "content": m.content}
                        for m in reversed(history)
                        if m.id != job.payload.get("message_id")
                    ],
                    gateway=gateway,
                    progress=progress,
                )
                # Atomically publish the response and finish the job; lease fencing prevents duplicates.
                db.refresh(job, with_for_update=True)
                if job.lock_token != token:
                    db.rollback()
                    return True
                message = Message(
                    conversation_id=job.payload["conversation_id"],
                    role="assistant",
                    content=result["summary"],
                    evidence=result,
                )
                db.add(message)
                db.flush()
                result = {**result, "message_id": message.id}
            elif job.kind == "index":
                progress("Gerando embeddings e indexando documento")
                document = db.get(Document, job.payload["document_id"])
                if document is None:
                    raise ValueError("Documento não encontrado.")
                index_document(db, document, embedder or get_embeddings())
                result = {"document_id": document.id, "status": document.status}
            elif job.kind == "fetch":
                progress("Baixando fonte oficial")
                document = fetch_source(db, job.payload["source_id"])
                result = {
                    "document_id": document.id if document else None,
                    "changed": bool(document),
                }
            elif job.kind == "analyze":
                result = analyze_contract(
                    db, job.owner_id, job.payload["document_id"], gateway=gateway, progress=progress
                )
                db.refresh(job, with_for_update=True)
                if job.lock_token != token:
                    db.rollback()
                    return True
                analysis = Analysis(
                    owner_id=job.owner_id,
                    document_id=job.payload["document_id"],
                    job_id=job.id,
                    result=result,
                )
                db.add(analysis)
                db.flush()
                result = {"analysis_id": analysis.id}
            else:
                raise ValueError("Tipo de tarefa não permitido.")
            # Every publication is fenced against lease replacement.
            db.refresh(job, with_for_update=True)
            if job.lock_token != token:
                db.rollback()
                return True
            job.result, job.status, job.stage = result, "completed", "Concluído"
            job.error = None
            job.updated_at, job.leased_until = now(), None
            db.commit()
            telemetry.jobs.labels(job.kind, "completed").inc()
    except Exception as exc:
        with session_factory()() as db:
            job = db.get(Job, job_id, with_for_update=True)
            if job.lock_token == token:
                transient = isinstance(exc, (ModelUnavailable, httpx.TransportError)) or (
                    isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500
                )
                retry = transient and job.attempts < 3
                job.status = "queued" if retry else "failed"
                job.stage = "Aguardando nova tentativa" if retry else "Falha no processamento"
                job.error = (
                    str(exc)
                    if isinstance(exc, (ModelUnavailable, InvalidEvidence, ValueError))
                    else "Falha no processamento. Consulte o diagnóstico pelo identificador da tarefa."
                )
                job.leased_until, job.lock_token, job.updated_at = None, None, now()
                db.commit()
                telemetry.jobs.labels(job.kind, job.status).inc()
        log.error("job_failed", extra={"job_id": job_id, "error_type": type(exc).__name__})
    return True


def check_sources():
    with session_factory()() as db:
        for source in due_sources(db):
            try:
                fetch_source(db, source.id)
            except Exception as exc:
                db.rollback()
                stored = db.get(Source, source.id)
                stored.checked_at, stored.check_error = now(), type(exc).__name__
                db.commit()
                log.warning("source_check_failed", extra={"error_type": type(exc).__name__})


def main():
    telemetry.configure_logging(get_settings().log_level)
    start_http_server(8001, addr=get_settings().worker_metrics_host)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    last_check = 0
    while not stop.is_set():
        try:
            if time.monotonic() - last_check > 3600:
                check_sources()
                last_check = time.monotonic()
            if not process_one():
                stop.wait(2)
        except Exception as exc:
            log.error("worker_cycle_failed", extra={"error_type": type(exc).__name__})
            stop.wait(5)


if __name__ == "__main__":
    main()
