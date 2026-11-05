import hashlib
import io
import json
from datetime import datetime

import pytest
from jurisassist.db import session_factory
from jurisassist.ingestion import contract_chunks, extract_upload, index_document, parse_legal_html
from jurisassist.models import Chunk, Document, now
from jurisassist.retrieval import basis_state, get_article, search
from pypdf import PdfWriter
from sqlalchemy import select


def test_html_preserves_articles_excludes_revoked():
    html = '<html><meta charset="utf-8"><p><s>Art. 2º redação antiga</s></p><p>Art. 2º Empregador.</p><p>§ 1º Complemento.</p><p>Art. 4º-A Serviços a terceiros.</p><p>§ 1º (Revogado)</p></html>'.encode()
    body, chunks = parse_legal_html(html)
    assert "redação antiga" not in body
    assert [c["metadata"]["article"] for c in chunks] == ["2", "2", "4-A"]
    assert "Revogado" not in " ".join(c["text"] for c in chunks)


def test_chunks_cover_all_text():
    body = " ".join(f"palavra{i}" for i in range(1000))
    chunks = contract_chunks(body)
    assert " ".join(c["text"] for c in chunks) == body
    assert all(len(c["text"]) <= 1000 for c in chunks)


def test_legacy_portuguese_charset_and_article_hyphens():
    raw = "<p>Art. 2º - Considera-se empregador a empresa.</p><p>Art. 4<sup>o</sup>-A. Prestação de serviços.</p><p>§ 1º Remuneração e direção.</p><p>Art. 11 - O contrato deve ser escrito.</p>".encode(
        "cp1252"
    )
    body, chunks = parse_legal_html(raw)
    assert "Prestação" in body and "direção" in body
    assert [c["metadata"]["article"] for c in chunks] == ["2", "4-A", "4-A", "11"]
    assert chunks[2]["text"].startswith("Art. 4")


def test_clt_preamble_is_not_the_labor_code():
    raw = "<p>Art. 2º Este decreto entra em vigor.</p><p>CONSOLIDAÇÃO DAS LEIS DO TRABALHO</p><p>Art. 2º Considera-se empregador a empresa.</p>".encode(
        "cp1252"
    )
    _, chunks = parse_legal_html(raw)
    assert len(chunks) == 1 and "empregador" in chunks[0]["text"]


def test_upload_rejects_scanned_password_and_invalid():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(ValueError, match="sem texto"):
        extract_upload("scan.pdf", buffer.getvalue())
    writer.encrypt("password")
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(ValueError, match="senha"):
        extract_upload("encrypted.pdf", buffer.getvalue())
    for filename, body in [
        ("x.exe", b"x" * 100),
        ("x.txt", b"\x00" * 100),
        ("x.txt", b"\xff" * 100),
        ("x.pdf", b"garbage"),
    ]:
        with pytest.raises(ValueError):
            extract_upload(filename, body)


def test_pdf_page_limit():
    writer = PdfWriter()
    for _ in range(51):
        writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(ValueError, match="50 páginas"):
        extract_upload("long.pdf", buffer.getvalue())


def test_retrieval_and_document_acl(corpus, embedder):
    with session_factory()() as db:
        doc = Document(
            owner_id="alice",
            title="Confidencial",
            kind="contract",
            checksum="private",
            body="CONTRATO_PRIVADO_CANARIO obrigações trabalhistas",
            metadata_json={},
        )
        db.add(doc)
        db.flush()
        index_document(db, doc, embedder)
        db.commit()
        for mode in ["text", "vector", "hybrid"]:
            found = search(db, "bob", "obrigações trabalhistas", mode=mode, embedder=embedder)
            assert found
            assert all(c["kind"] == "law" for c in found)
            assert (
                search(
                    db,
                    "bob",
                    "obrigações trabalhistas",
                    mode=mode,
                    document_id=doc.id,
                    embedder=embedder,
                )
                == []
            )
        assert get_article(db, "clt", "2")[0]["locator"] == "Art. 2"


def test_new_version_retires_old_but_keeps_citations(corpus, embedder):
    with session_factory()() as db:
        old = db.scalar(select(Document).where(Document.source_id == "clt"))
        old_chunk = db.scalar(select(Chunk).where(Chunk.document_id == old.id))
        new = Document(
            source_id="clt",
            title="Atualizada",
            kind="law",
            status="indexing",
            checksum="v2",
            body="Art. 2º Texto atualizado.",
            approved_at=now(),
            metadata_json={
                "chunks": [
                    {
                        "locator": "Art. 2",
                        "text": "Art. 2º Texto atualizado.",
                        "metadata": {"article": "2"},
                    }
                ]
            },
        )
        db.add(new)
        db.flush()
        index_document(db, new, embedder)
        db.commit()
        assert old.status == "retired"
        assert db.get(Chunk, old_chunk.id)
        assert get_article(db, "clt", "2")[0]["document_id"] == new.id
        assert not basis_state(db)["pending_update"]


def test_unapproved_law_never_indexed(database, embedder):
    with session_factory()() as db:
        doc = Document(
            title="Não aprovada", kind="law", checksum="x", body="Art. 2º texto", metadata_json={}
        )
        db.add(doc)
        db.flush()
        with pytest.raises(ValueError, match="Aprovação"):
            index_document(db, doc, embedder)


def test_snapshot_is_pending_and_preserves_collection_date(database, tmp_path, monkeypatch):
    from jurisassist.ingestion import SOURCES, bootstrap_sources
    from jurisassist.models import Source

    folder = tmp_path / "corpus" / "snapshots"
    folder.mkdir(parents=True)
    body = "Art. 2º Considera-se empregador a empresa."
    payload = {
        "source_id": "clt",
        "url": SOURCES["clt"][1],
        "title": "CLT",
        "body": body,
        "checksum": hashlib.sha256(body.encode()).hexdigest(),
        "collected_at": "2026-10-23T12:00:00",
        "metadata": {"parser": "legal-html-v2"},
    }
    (folder / "clt.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with session_factory()() as db:
        bootstrap_sources(db, load_snapshots=True)
        doc = db.scalar(select(Document).where(Document.source_id == "clt"))
        assert doc.status == "pending_review" and doc.approved_at is None
        assert db.get(Source, "clt").checked_at == datetime(2026, 10, 23, 12)
        assert search(db, "alice", "empregador", mode="text") == []
        bootstrap_sources(db, load_snapshots=True)
        assert len(list(db.scalars(select(Document)))) == 1


def test_changed_source_supersedes_only_unapproved_candidate(database, monkeypatch):
    import httpx
    import jurisassist.ingestion as ingestion

    revision = [1]
    original_client = httpx.Client

    def respond(request):
        html = "".join(
            f"<p>Art. {i}º Texto da revisão {revision[0]} para consulta pública.</p>"
            for i in range(1, 7)
        )
        return httpx.Response(200, content=html.encode("cp1252"), request=request)

    monkeypatch.setattr(
        ingestion.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond)),
    )
    with session_factory()() as db:
        first = ingestion.fetch_source(db, "clt")
        revision[0] = 2
        second = ingestion.fetch_source(db, "clt")
        assert first.status == "superseded"
        assert second.status == "pending_review"
        assert ingestion.fetch_source(db, "clt") is None
