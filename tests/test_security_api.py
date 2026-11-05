from conftest import authenticate
from fastapi.testclient import TestClient
from jurisassist.db import session_factory
from jurisassist.models import Conversation, Document, Job, Message
from sqlalchemy import select


def test_authentication_and_csrf(client):
    assert client.get("/api/v1/conversations").status_code == 401
    authenticate(client)
    assert client.cookies.get("juris_session")
    assert "HttpOnly" in client.post(
        "/api/v1/auth/login", json={"email": "alice@example.test", "password": "test-password-123"}
    ).headers.get("set-cookie")
    # The second login rotated the CSRF token.
    assert client.post("/api/v1/conversations", json={"title": "Consulta"}).status_code == 403
    client.headers["X-CSRF-Token"] = client.cookies.get("juris_csrf")
    assert client.post("/api/v1/conversations", json={"title": "Consulta"}).status_code == 201
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_origin_rejected_before_login(client):
    result = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example"},
        json={"email": "alice@example.test", "password": "test-password-123"},
    )
    assert result.status_code == 403


def test_login_limit_shared_database(client):
    for _ in range(10):
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": "missing@example.test", "password": "wrong"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "missing@example.test", "password": "wrong"}
        ).status_code
        == 429
    )


def test_owner_isolation_all_resources(alice):
    from jurisassist.api import create_app

    with session_factory()() as db:
        conversation = Conversation(owner_id="alice", title="Privado")
        document = Document(
            owner_id="alice",
            title="Privado",
            kind="contract",
            checksum="abc",
            body="CONTRATO_PRIVADO_CANARIO",
            metadata_json={},
        )
        db.add_all([conversation, document])
        db.flush()
        job = Job(owner_id="alice", kind="index", payload={"document_id": document.id})
        message = Message(conversation_id=conversation.id, role="assistant", content="Privado")
        db.add_all([job, message])
        db.commit()
        ids = conversation.id, document.id, job.id, message.id
    with TestClient(create_app()) as bob:
        authenticate(bob, "bob@example.test", "test-password-456")
        for path in [
            f"/conversations/{ids[0]}/messages",
            f"/documents/{ids[1]}",
            f"/jobs/{ids[2]}",
            f"/jobs/{ids[2]}/events",
        ]:
            assert bob.get("/api/v1" + path).status_code == 404
        assert bob.get("/api/v1/admin/sources").status_code == 403
        assert (
            bob.post("/api/v1/feedback", json={"message_id": ids[3], "rating": -1}).status_code
            == 404
        )
        assert bob.get("/api/v1/documents").json() == []


def test_chat_idempotency_and_conflicts(alice):
    conversation = alice.post("/api/v1/conversations", json={}).json()
    path = f"/api/v1/conversations/{conversation['id']}/messages"
    headers = {"Idempotency-Key": "message-1"}
    first = alice.post(path, json={"content": "Quem é empregador?"}, headers=headers)
    second = alice.post(path, json={"content": "Quem é empregador?"}, headers=headers)
    assert first.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert alice.post(path, json={"content": "Outra pergunta"}, headers=headers).status_code == 409
    assert alice.post(path, json={"content": "Nova pergunta"}).status_code == 409
    with session_factory()() as db:
        assert len(list(db.scalars(select(Message)))) == 1


def test_queue_limit_and_upload_validation(alice):
    invalid = alice.post(
        "/api/v1/documents",
        data={"synthetic": "true"},
        files={"file": ("fake.pdf", b"not pdf", "application/pdf")},
    )
    assert invalid.status_code == 422
    denied = alice.post(
        "/api/v1/documents",
        data={"synthetic": "false"},
        files={"file": ("file.txt", b"Fictitious text" * 10, "text/plain")},
    )
    assert denied.status_code == 422
    for _ in range(3):
        assert alice.post("/api/v1/examples/servicos-ti").status_code == 202
    assert alice.post("/api/v1/examples/servicos-ti").status_code == 429


def test_request_body_limit_before_multipart(client):
    response = client.post(
        "/api/v1/documents",
        content=b"x" * (11 * 1024 * 1024),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 413


def test_sources_require_admin_review(alice, corpus):
    from jurisassist.models import now

    with session_factory()() as db:
        newer = Document(
            source_id="clt",
            title="Nova redação",
            kind="law",
            checksum="newhash",
            body="Art. 2º Texto de nova versão para revisão.",
            status="pending_review",
            metadata_json={"chunks": []},
        )
        db.add(newer)
        db.commit()
        doc_id = newer.id
    response = alice.post(f"/api/v1/admin/documents/{doc_id}/approve")
    assert response.status_code == 202
    with session_factory()() as db:
        doc = db.get(Document, doc_id)
        assert doc.approved_at <= now()
        assert doc.status == "indexing"
