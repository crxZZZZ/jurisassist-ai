from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, update

from jurisassist.config import get_settings
from jurisassist.models import Job, User, now, uid


def enqueue(db, user: User, kind: str, payload: dict, key=None):
    if key:
        existing = db.scalar(select(Job).where(Job.owner_id == user.id, Job.idempotency_key == key))
        if existing:
            if existing.kind != kind or existing.payload != payload:
                raise HTTPException(
                    409, "Esta chave de idempotência já foi usada com outros dados."
                )
            return existing
    # Serialize submissions per user so the queue limit cannot be raced.
    db.execute(select(User).where(User.id == user.id).with_for_update()).scalar_one()
    active = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.owner_id == user.id, Job.status.in_(["queued", "running"]))
    )
    if active >= get_settings().max_jobs_per_user:
        raise HTTPException(429, "Você já possui três tarefas em andamento.")
    job = Job(owner_id=user.id, kind=kind, payload=payload, idempotency_key=key)
    db.add(job)
    db.flush()
    return job


def claim_job(db):
    at = now()
    expired = list(
        db.scalars(
            select(Job)
            .where(Job.status == "running", Job.leased_until < at)
            .with_for_update(skip_locked=True)
        )
    )
    for job in expired:
        job.status = "failed" if job.attempts >= 3 else "queued"
        job.error = (
            "Worker interrompido; limite de tentativas atingido."
            if job.status == "failed"
            else None
        )
        job.lock_token = None
    db.flush()
    job = db.scalar(
        select(Job)
        .where(Job.status == "queued")
        .order_by(Job.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        db.commit()
        return None
    job.status, job.stage, job.lock_token = "running", "Iniciando processamento", uid()
    job.attempts += 1
    job.leased_until = at + timedelta(seconds=get_settings().job_lease_seconds)
    job.updated_at = at
    db.commit()
    return job.id, job.lock_token


def renew_lease(db, job_id, token):
    changed = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == "running", Job.lock_token == token)
        .values(
            leased_until=now() + timedelta(seconds=get_settings().job_lease_seconds),
            updated_at=now(),
        )
    )
    db.commit()
    return changed.rowcount == 1
