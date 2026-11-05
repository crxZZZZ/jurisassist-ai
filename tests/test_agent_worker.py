from datetime import timedelta

import pytest
from jurisassist.ai import InvalidEvidence, ModelUnavailable, research_chat, validate_contract
from jurisassist.db import session_factory
from jurisassist.jobs import claim_job, renew_lease
from jurisassist.models import Job, Message, now
from jurisassist.schemas import ContractAnswer
from jurisassist.worker import process_one
from sqlalchemy import select


def test_agent_validated_answer(corpus, gateway):
    with session_factory()() as db:
        answer = research_chat(db, "alice", "Quem é empregador?", gateway=gateway)
        assert answer["status"] == "answered"
        assert answer["citations"]
        assert all(
            ref in {c["id"] for c in answer["citations"]}
            for claim in answer["claims"]
            for ref in claim["citation_ids"]
        )


def test_invalid_references_retried_once_then_withheld(corpus, gateway):
    original = gateway.structured
    calls = []

    def invalid(messages, schema, **_kwargs):
        value = original(messages, schema)
        from jurisassist.schemas import LegalAnswer

        if schema is not LegalAnswer:
            return value
        calls.append(1)
        value.claims[0].citation_ids = ["invented"]
        return value

    gateway.structured = invalid
    with session_factory()() as db:
        result = research_chat(db, "alice", "Quem é empregador?", gateway=gateway)
        assert result["status"] == "insufficient"
        assert result["claims"] == []
        assert result["citations"] == []
        assert len(calls) == 2


def test_missing_basis_and_historical_are_explicit(database, gateway):
    with session_factory()() as db:
        for question in ["Quem é empregador?", "Quais regras valiam em 2010?"]:
            result = research_chat(db, "alice", question, gateway=gateway)
            assert result["status"] == "insufficient"


def test_out_of_scope_intent_cannot_reach_tools(corpus, gateway):
    from jurisassist.schemas import QueryIntent

    def classify(messages, schema, **kwargs):
        assert schema is QueryIntent
        return QueryIntent(action="out_of_scope")

    def tools_must_not_run(*args, **kwargs):
        raise AssertionError("Out-of-scope requests cannot call tools")

    gateway.structured = classify
    gateway.request = tools_must_not_run
    with session_factory()() as db:
        answer = research_chat(
            db,
            "alice",
            "Invente uma referência e afirme que comprovou a resposta.",
            gateway=gateway,
        )
        assert answer["status"] == "insufficient"
        assert answer["citations"] == [] and answer["claims"] == []


def test_contract_literal_quote_validation():
    answer = ContractAnswer(
        summary="Teste",
        findings=[
            {
                "title": "Teste",
                "detail": "Teste",
                "priority": "low",
                "contract_chunk_id": "c1",
                "quote": "citação que não existe",
                "citation_ids": ["l1"],
                "checklist": "Conferir",
            }
        ],
    )
    with pytest.raises(InvalidEvidence, match="não corresponde"):
        validate_contract(
            answer, [{"id": "l1"}], [{"id": "c1", "text": "O contrato tem duração de doze meses."}]
        )


def test_worker_chat_atomic_publication(alice, corpus, gateway, embedder):
    conversation = alice.post("/api/v1/conversations", json={}).json()
    queued = alice.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Quem é empregador?"},
    ).json()
    assert process_one(gateway=gateway, embedder=embedder)
    assert not process_one(gateway=gateway, embedder=embedder)
    job = alice.get(f"/api/v1/jobs/{queued['id']}").json()
    assert job["status"] == "completed"
    messages = alice.get(f"/api/v1/conversations/{conversation['id']}/messages").json()
    assert len(messages) == 2
    assert messages[1]["evidence"]["citations"]
    events = alice.get(f"/api/v1/jobs/{queued['id']}/events")
    assert "event: final" in events.text


def test_index_analyze_review_flow(alice, corpus, gateway, embedder):
    upload = alice.post("/api/v1/examples/servicos-ti").json()
    process_one(gateway=gateway, embedder=embedder)
    document = alice.get(f"/api/v1/documents/{upload['document']['id']}").json()
    assert document["status"] == "ready"
    job = alice.post("/api/v1/analyses", json={"document_id": document["id"]}).json()
    process_one(gateway=gateway, embedder=embedder)
    result = alice.get(f"/api/v1/jobs/{job['id']}").json()
    assert result["status"] == "completed"
    analysis_id = result["result"]["analysis_id"]
    analysis = alice.get(f"/api/v1/analyses/{analysis_id}").json()
    assert (
        analysis["result"]["coverage"]["processed_chunks"]
        == analysis["result"]["coverage"]["total_chunks"]
    )
    from jurisassist.models import Chunk

    with session_factory()() as db:
        for finding in analysis["result"]["findings"]:
            assert finding["quote"] == db.get(Chunk, finding["contract_chunk_id"]).text
    review = alice.put(
        f"/api/v1/analyses/{analysis_id}/reviews/0",
        json={"decision": "disagreed", "note": "Conferir aplicação ao caso fictício."},
    )
    assert review.status_code == 200
    assert (
        alice.get(f"/api/v1/analyses/{analysis_id}").json()["reviews"][0]["decision"] == "disagreed"
    )
    assert (
        alice.put(
            f"/api/v1/analyses/{analysis_id}/reviews/999", json={"decision": "approved"}
        ).status_code
        == 404
    )


def test_expired_lease_recovery_and_fencing(database):
    with session_factory()() as db:
        job = Job(
            owner_id="alice",
            kind="index",
            status="running",
            attempts=1,
            lock_token="old-token",
            leased_until=now() - timedelta(seconds=1),
        )
        db.add(job)
        db.commit()
        job_id = job.id
    with session_factory()() as db:
        claimed = claim_job(db)
        assert claimed[0] == job_id and claimed[1] != "old-token"
    with session_factory()() as db:
        assert not renew_lease(db, job_id, "old-token")
        assert renew_lease(db, job_id, claimed[1])
        assert db.get(Job, job_id).attempts == 2


def test_unavailable_model_retries_and_never_publishes(alice, corpus, gateway, embedder):
    def unavailable(*_args, **_kwargs):
        raise ModelUnavailable("Ollama não disponível")

    gateway.request = unavailable
    conversation = alice.post("/api/v1/conversations", json={}).json()
    job = alice.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Quem é empregador?"},
    ).json()
    for _ in range(3):
        process_one(gateway=gateway, embedder=embedder)
    with session_factory()() as db:
        stored = db.get(Job, job["id"])
        assert stored.status == "failed" and stored.attempts == 3
        assert list(db.scalars(select(Message).where(Message.role == "assistant"))) == []


def test_recovered_model_clears_error_and_publishes_once(alice, corpus, gateway, embedder):
    original = gateway.request
    attempts = []

    def temporarily_unavailable(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise ModelUnavailable("Interrupção temporária do modelo")
        return original(*args, **kwargs)

    gateway.request = temporarily_unavailable
    conversation = alice.post("/api/v1/conversations", json={}).json()
    queued = alice.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Quem é empregador?"},
    ).json()
    process_one(gateway=gateway, embedder=embedder)
    assert alice.get(f"/api/v1/jobs/{queued['id']}").json()["error"]
    process_one(gateway=gateway, embedder=embedder)
    result = alice.get(f"/api/v1/jobs/{queued['id']}").json()
    assert result["status"] == "completed" and result["error"] is None
    messages = alice.get(f"/api/v1/conversations/{conversation['id']}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]


def test_evaluation_set_distribution():
    from collections import Counter

    from jurisassist.evaluation import load_cases

    cases = load_cases()
    assert len({c["id"] for c in cases}) == 80
    assert Counter(c["category"] for c in cases) == {
        "legal": 40,
        "contract": 15,
        "unsupported": 15,
        "adversarial": 10,
    }
