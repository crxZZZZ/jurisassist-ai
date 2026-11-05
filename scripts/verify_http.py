"""Exercise the running Compose application using an ephemeral local QA account."""

import json
import secrets
import time
from uuid import uuid4

import httpx
from jurisassist.db import session_factory
from jurisassist.models import Audit, Conversation, Document, Job, Session, User
from jurisassist.security import hasher
from sqlalchemy import delete, select


def wait_job(client, job_id):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}")
        response.raise_for_status()
        job = response.json()
        if job["status"] == "completed":
            return job
        if job["status"] == "failed":
            raise RuntimeError(job["error"])
        time.sleep(2)
    raise TimeoutError("A tarefa não terminou em 180 segundos.")


def main():
    identifier = str(uuid4())
    email, password = f"qa-{identifier}@local.invalid", secrets.token_urlsafe(24)
    with session_factory()() as db:
        db.add(
            User(
                id=identifier,
                email=email,
                name="Verificação HTTP temporária",
                role="admin",
                password_hash=hasher.hash(password),
            )
        )
        db.commit()
    try:
        with httpx.Client(base_url="http://127.0.0.1:8080", timeout=15, trust_env=False) as client:
            assert client.get("/").status_code == 200
            login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            status = client.get("/api/v1/status").json()
            print(
                json.dumps(
                    {
                        "model_installed": status["model_installed"],
                        "ollama_online": status["ollama_online"],
                        "basis": status["basis"],
                    }
                ),
                flush=True,
            )
            if not status["model_installed"]:
                raise RuntimeError("O container não alcançou o modelo Ollama do host.")
            conversation = client.post("/api/v1/conversations", json={"title": "QA HTTP"})
            conversation.raise_for_status()
            cid = conversation.json()["id"]
            task = client.post(
                f"/api/v1/conversations/{cid}/messages",
                json={"content": "Quais regras valiam em 2010?"},
            )
            task.raise_for_status()
            result = wait_job(client, task.json()["id"])
            assert result["result"]["status"] == "insufficient"
            assert "event: final" in client.get(f"/api/v1/jobs/{task.json()['id']}/events").text
            upload = client.post("/api/v1/examples/servicos-ti")
            upload.raise_for_status()
            wait_job(client, upload.json()["job"]["id"])
            doc = client.get(f"/api/v1/documents/{upload.json()['document']['id']}")
            assert doc.json()["status"] == "ready"
            assert client.get("/api/v1/admin/metrics/worker").status_code == 200
            assert client.post("/api/v1/auth/logout").status_code == 200
            assert client.get("/api/v1/auth/me").status_code == 401
            print(
                "HTTP real: login, CSRF, status/modelo, fila, SSE, indexacao ONNX e logout aprovados.",
                flush=True,
            )
    finally:
        # Only the uniquely generated QA account and its own synthetic records.
        with session_factory()() as db:
            active = db.scalar(
                select(Job.id)
                .where(Job.owner_id == identifier, Job.status.in_(["queued", "running"]))
                .limit(1)
            )
            if active:
                print(
                    "Conta de QA preservada porque há tarefa ativa; não remover registros em processamento."
                )
            else:
                for model, condition in [
                    (Audit, Audit.actor_id == identifier),
                    (Conversation, Conversation.owner_id == identifier),
                    (Job, Job.owner_id == identifier),
                    (Document, Document.owner_id == identifier),
                    (Session, Session.user_id == identifier),
                    (User, User.id == identifier),
                ]:
                    db.execute(delete(model).where(condition))
                db.commit()


if __name__ == "__main__":
    main()
