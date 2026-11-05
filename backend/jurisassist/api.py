import asyncio
import hashlib
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

import httpx
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from jurisassist import telemetry
from jurisassist.config import get_settings
from jurisassist.db import get_db, session_factory
from jurisassist.ingestion import SOURCES, extract_upload
from jurisassist.jobs import enqueue
from jurisassist.models import (
    Analysis,
    Audit,
    Conversation,
    Document,
    Feedback,
    Job,
    Message,
    Review,
    Session,
    Source,
    User,
    now,
)
from jurisassist.retrieval import basis_state
from jurisassist.schemas import (
    AnalyzeInput,
    ConversationInput,
    FeedbackInput,
    LoginInput,
    MessageInput,
    ReviewInput,
)
from jurisassist.security import (
    COOKIE,
    CSRF_COOKIE,
    admin_user,
    current_user,
    digest,
    hasher,
    password_matches,
    rate_limit,
)

log = logging.getLogger(__name__)


def public_user(user):
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


def job_view(job):
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "stage": job.stage,
        "attempts": job.attempts,
        "error": job.error,
        "result": job.result,
        "created_at": job.created_at.isoformat(),
        "conversation_id": job.payload.get("conversation_id"),
    }


def document_view(doc):
    return {
        "id": doc.id,
        "title": doc.title,
        "kind": doc.kind,
        "status": doc.status,
        "source_id": doc.source_id,
        "version": doc.checksum[:12],
        "created_at": doc.created_at.isoformat(),
        "approved_at": doc.approved_at,
        "review_note": doc.metadata_json.get("review_note"),
        "chunk_count": len(doc.metadata_json.get("chunks", [])),
        "url": doc.metadata_json.get("url"),
    }


def owned(db, model, object_id, user, field="owner_id"):
    obj = db.get(model, object_id)
    if obj is None or getattr(obj, field) != user.id:
        raise HTTPException(404, "Registro não encontrado.")
    return obj


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD", "OPTIONS"}:
            return await self.app(scope, receive, send)
        body, size = [], 0
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            size += len(event.get("body", b""))
            if size > self.max_bytes:
                response = JSONResponse(
                    {"detail": "Corpo da requisição excede o limite de 10 MB."}, status_code=413
                )
                return await response(scope, receive, send)
            body.append(event)
            if not event.get("more_body", False):
                break

        async def replay():
            if body:
                return body.pop(0)
            return await receive()

        return await self.app(scope, replay, send)


def create_app():
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_):
        telemetry.configure_logging(settings.log_level)
        yield

    app = FastAPI(
        title="JurisAssist API",
        version="0.1.0",
        lifespan=lifespan,
        description="Pesquisa jurídica local com evidências versionadas. Sessão por cookie e X-CSRF-Token para mutações.",
    )
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_upload_bytes + 65536)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def request_context(request, call_next):
        request_id = str(uuid4())
        started = time.perf_counter()
        origin = request.headers.get("origin")
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and origin
            and origin not in settings.origins
        ):
            return JSONResponse({"detail": "Origem não autorizada."}, status_code=403)
        try:
            response = await call_next(request)
        except Exception as exc:
            log.error(
                "request_failed", extra={"request_id": request_id, "error_type": type(exc).__name__}
            )
            response = JSONResponse(
                {
                    "detail": "Falha interna. Consulte o identificador da requisição.",
                    "request_id": request_id,
                },
                status_code=500,
            )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        route = request.scope.get("route")
        path = route.path if route else "unmatched"
        telemetry.requests.labels(request.method, path, str(response.status_code)).inc()
        telemetry.latency.labels(path).observe(time.perf_counter() - started)
        return response

    @app.exception_handler(IntegrityError)
    async def conflict_handler(_request, _exc):
        return JSONResponse(
            {"detail": "Operação concorrente ou registro duplicado. Atualize e tente novamente."},
            status_code=409,
        )

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready(db: DBSession = Depends(get_db)):
        db.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.post("/api/v1/auth/login", tags=["auth"])
    def login(
        payload: LoginInput, request: Request, response: Response, db: DBSession = Depends(get_db)
    ):
        rate_limit(db, "login-ip:" + (request.client.host if request.client else "unknown"), 10)
        rate_limit(db, "login-account:" + payload.email.strip().lower(), 10)
        user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
        # Verify a fixed dummy hash for absent accounts to avoid a cheap timing oracle.
        encoded = user.password_hash if user else dummy_hash
        matches = password_matches(encoded, payload.password)
        if user is None or not matches:
            raise HTTPException(401, "E-mail ou senha inválidos.")
        token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        db.add(
            Session(
                token_hash=digest(token),
                user_id=user.id,
                csrf_hash=digest(csrf),
                expires_at=now() + timedelta(hours=settings.session_hours),
            )
        )
        db.add(Audit(actor_id=user.id, action="auth.login", target_id=user.id))
        db.commit()
        for name, value, httponly in [(COOKIE, token, True), (CSRF_COOKIE, csrf, False)]:
            response.set_cookie(
                name,
                value,
                max_age=settings.session_hours * 3600,
                httponly=httponly,
                secure=settings.cookie_secure,
                samesite="strict",
                path="/",
            )
        return {"user": public_user(user), "csrf_token": csrf}

    @app.get("/api/v1/auth/me", tags=["auth"])
    def me(user: User = Depends(current_user)):
        return public_user(user)

    @app.post("/api/v1/auth/logout", tags=["auth"])
    def logout(
        request: Request,
        response: Response,
        user: User = Depends(current_user),
        db: DBSession = Depends(get_db),
    ):
        session = db.get(Session, digest(request.cookies.get(COOKIE, "")))
        if session:
            db.delete(session)
        db.commit()
        response.delete_cookie(COOKIE)
        response.delete_cookie(CSRF_COOKIE)
        return {"status": "ok"}

    @app.get("/api/v1/status", tags=["system"])
    def status(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
        installed, online = False, False
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                result = client.get(f"{settings.ollama_url}/api/tags")
                result.raise_for_status()
                installed = any(
                    m.get("name") == settings.model for m in result.json().get("models", [])
                )
                online = True
        except (httpx.HTTPError, ValueError):
            pass
        running = db.scalar(select(Job).where(Job.status == "running").limit(1))
        return {
            "ollama_online": online,
            "model_installed": installed,
            "model": settings.model,
            "basis": basis_state(db),
            "worker_busy": bool(running),
        }

    @app.get("/api/v1/conversations", tags=["chat"])
    def conversations(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
        return [
            {"id": c.id, "title": c.title, "created_at": c.created_at}
            for c in db.scalars(
                select(Conversation)
                .where(Conversation.owner_id == user.id)
                .order_by(Conversation.created_at.desc())
                .limit(100)
            )
        ]

    @app.post("/api/v1/conversations", status_code=201, tags=["chat"])
    def new_conversation(
        payload: ConversationInput,
        user: User = Depends(current_user),
        db: DBSession = Depends(get_db),
    ):
        rate_limit(db, f"conversation:{user.id}", 20)
        conversation = Conversation(owner_id=user.id, title=payload.title.strip())
        db.add(conversation)
        db.commit()
        return {"id": conversation.id, "title": conversation.title}

    @app.get("/api/v1/conversations/{conversation_id}/messages", tags=["chat"])
    def messages(
        conversation_id: str, user: User = Depends(current_user), db: DBSession = Depends(get_db)
    ):
        owned(db, Conversation, conversation_id, user)
        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "evidence": m.evidence,
                "created_at": m.created_at,
            }
            for m in db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
        ]

    @app.post("/api/v1/conversations/{conversation_id}/messages", status_code=202, tags=["chat"])
    def send_message(
        conversation_id: str,
        payload: MessageInput,
        user: User = Depends(current_user),
        db: DBSession = Depends(get_db),
        idempotency_key: str | None = Header(default=None, max_length=150),
    ):
        conversation = owned(db, Conversation, conversation_id, user)
        rate_limit(db, f"chat:{user.id}", 10)
        stable_payload = {"conversation_id": conversation_id, "question": payload.content.strip()}
        if idempotency_key:
            old = db.scalar(
                select(Job).where(Job.owner_id == user.id, Job.idempotency_key == idempotency_key)
            )
            if old:
                if old.kind != "chat" or any(
                    old.payload.get(k) != v for k, v in stable_payload.items()
                ):
                    raise HTTPException(
                        409, "Chave de idempotência reutilizada com outra mensagem."
                    )
                return job_view(old)
        db.refresh(conversation, with_for_update=True)
        busy = db.scalar(
            select(Job).where(
                Job.owner_id == user.id, Job.kind == "chat", Job.status.in_(["queued", "running"])
            )
        )
        if busy:
            raise HTTPException(409, "Aguarde a consulta anterior terminar.")
        job = enqueue(db, user, "chat", stable_payload, idempotency_key)
        message = Message(
            conversation_id=conversation_id, role="user", content=payload.content.strip()
        )
        db.add(message)
        db.flush()
        job.payload = {**job.payload, "message_id": message.id}
        if conversation.title == "Nova consulta":
            conversation.title = payload.content.strip()[:100]
        db.commit()
        return job_view(job)

    @app.get("/api/v1/jobs", tags=["jobs"])
    def list_jobs(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
        return [
            job_view(j)
            for j in db.scalars(
                select(Job).where(Job.owner_id == user.id).order_by(Job.created_at.desc()).limit(50)
            )
        ]

    @app.get("/api/v1/jobs/{job_id}", tags=["jobs"])
    def get_job(job_id: str, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
        return job_view(owned(db, Job, job_id, user))

    @app.get("/api/v1/jobs/{job_id}/events", tags=["jobs"])
    def events(
        job_id: str,
        request: Request,
        user: User = Depends(current_user),
        db: DBSession = Depends(get_db),
    ):
        owned(db, Job, job_id, user)
        token_hash = digest(request.cookies.get(COOKIE, ""))

        async def stream():
            last = None
            for _ in range(300):
                if await request.is_disconnected():
                    return
                with session_factory()() as stream_db:
                    session = stream_db.get(Session, token_hash)
                    if session is None or session.expires_at < now():
                        yield 'event: error\ndata: {"detail":"Sessão encerrada."}\n\n'
                        return
                    job = stream_db.get(Job, job_id)
                    if job is None or job.owner_id != user.id:
                        return
                    data = job_view(job)
                encoded = json.dumps(data, ensure_ascii=False)
                if encoded != last:
                    event = (
                        "final"
                        if data["status"] == "completed"
                        else "error"
                        if data["status"] == "failed"
                        else "status"
                    )
                    yield f"event: {event}\ndata: {encoded}\n\n"
                    last = encoded
                else:
                    yield ": heartbeat\n\n"
                if data["status"] in {"completed", "failed"}:
                    return
                await asyncio.sleep(2)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    @app.get("/api/v1/documents", tags=["documents"])
    def documents(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
        docs = db.scalars(
            select(Document)
            .where((Document.owner_id == user.id) | (Document.kind == "law"))
            .order_by(Document.created_at.desc())
            .limit(100)
        )
        return [document_view(doc) for doc in docs]

    @app.get("/api/v1/documents/{document_id}", tags=["documents"])
    def document_detail(
        document_id: str, user: User = Depends(current_user), db: DBSession = Depends(get_db)
    ):
        doc = db.get(Document, document_id)
        if doc is None or (doc.kind != "law" and doc.owner_id != user.id):
            raise HTTPException(404, "Documento não encontrado.")
        return {**document_view(doc), "body": doc.body}

    @app.post("/api/v1/documents", status_code=202, tags=["documents"])
    def upload(
        file: UploadFile = File(),
        synthetic: bool = Form(),
        user: User = Depends(current_user),
        db: DBSession = Depends(get_db),
    ):
        rate_limit(db, f"upload:{user.id}", 5)
        if not synthetic:
            raise HTTPException(422, "A demonstração aceita somente documentos fictícios.")
        try:
            body, metadata = extract_upload(
                file.filename or "", file.file.read(settings.max_upload_bytes + 1)
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        title = (file.filename or "Contrato fictício").replace("\\", "/").split("/")[-1][:200]
        doc = Document(
            owner_id=user.id,
            title=title,
            kind="contract",
            body=body,
            checksum=hashlib.sha256(body.encode()).hexdigest(),
            metadata_json=metadata,
        )
        db.add(doc)
        db.flush()
        job = enqueue(db, user, "index", {"document_id": doc.id})
        db.add(Audit(actor_id=user.id, action="document.upload", target_id=doc.id))
        db.commit()
        return {"document": document_view(doc), "job": job_view(job)}

    @app.get("/api/v1/examples", tags=["documents"])
    def examples(user: User = Depends(current_user)):
        from jurisassist.samples import SAMPLES

        return [
            {"id": key, "title": value[0], "description": value[1]}
            for key, value in SAMPLES.items()
        ]

    @app.post("/api/v1/examples/{example_id}", status_code=202, tags=["documents"])
    def use_example(
        example_id: str, user: User = Depends(current_user), db: DBSession = Depends(get_db)
    ):
        from jurisassist.samples import SAMPLES

        if example_id not in SAMPLES:
            raise HTTPException(404, "Exemplo não encontrado.")
        rate_limit(db, f"upload:{user.id}", 5)
        title, _, body = SAMPLES[example_id]
        doc = Document(
            owner_id=user.id,
            title=title,
            kind="contract",
            body=body,
            checksum=hashlib.sha256(body.encode()).hexdigest(),
            metadata_json={"synthetic_only": True},
        )
        db.add(doc)
        db.flush()
        job = enqueue(db, user, "index", {"document_id": doc.id})
        db.commit()
        return {"document": document_view(doc), "job": job_view(job)}

    @app.post("/api/v1/analyses", status_code=202, tags=["analyses"])
    def create_analysis(
        payload: AnalyzeInput,
        user: User = Depends(current_user),
        db: DBSession = Depends(get_db),
        idempotency_key: str | None = Header(default=None, max_length=150),
    ):
        document = owned(db, Document, payload.document_id, user)
        if document.status != "ready":
            raise HTTPException(409, "Aguarde a indexação do contrato.")
        if basis_state(db)["indexed_sources"] == 0:
            raise HTTPException(409, "Prepare e aprove as fontes jurídicas antes da análise.")
        rate_limit(db, f"analysis:{user.id}", 5)
        job = enqueue(db, user, "analyze", payload.model_dump(), idempotency_key)
        db.commit()
        return job_view(job)

    @app.get("/api/v1/analyses", tags=["analyses"])
    def analyses(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
        return [
            {
                "id": a.id,
                "document_id": a.document_id,
                "title": db.get(Document, a.document_id).title,
                "created_at": a.created_at,
            }
            for a in db.scalars(
                select(Analysis)
                .where(Analysis.owner_id == user.id)
                .order_by(Analysis.created_at.desc())
                .limit(100)
            )
        ]

    @app.get("/api/v1/analyses/{analysis_id}", tags=["analyses"])
    def get_analysis(
        analysis_id: str, user: User = Depends(current_user), db: DBSession = Depends(get_db)
    ):
        analysis = owned(db, Analysis, analysis_id, user)
        reviews = db.scalars(select(Review).where(Review.analysis_id == analysis_id))
        return {
            "id": analysis.id,
            "document_id": analysis.document_id,
            "result": analysis.result,
            "reviews": [
                {"item_index": r.item_index, "decision": r.decision, "note": r.note}
                for r in reviews
            ],
        }

    @app.put("/api/v1/analyses/{analysis_id}/reviews/{item_index}", tags=["analyses"])
    def review(
        analysis_id: str,
        item_index: int,
        payload: ReviewInput,
        user: User = Depends(current_user),
        db: DBSession = Depends(get_db),
    ):
        analysis = owned(db, Analysis, analysis_id, user)
        if item_index < 0 or item_index >= len(analysis.result.get("findings", [])):
            raise HTTPException(404, "Item não encontrado.")
        row = db.scalar(
            select(Review).where(Review.analysis_id == analysis_id, Review.item_index == item_index)
        )
        if row is None:
            row = Review(analysis_id=analysis_id, item_index=item_index, reviewer_id=user.id)
            db.add(row)
        row.decision, row.note, row.updated_at = payload.decision, payload.note, now()
        db.add(
            Audit(
                actor_id=user.id,
                action="analysis.review." + payload.decision,
                target_id=f"{analysis_id}:{item_index}",
            )
        )
        db.commit()
        return {"status": "saved"}

    @app.post("/api/v1/feedback", tags=["feedback"])
    def feedback(
        payload: FeedbackInput, user: User = Depends(current_user), db: DBSession = Depends(get_db)
    ):
        message = db.get(Message, payload.message_id)
        if message is None or message.role != "assistant":
            raise HTTPException(404, "Resposta não encontrada.")
        owned(db, Conversation, message.conversation_id, user)
        row = db.scalar(
            select(Feedback).where(Feedback.owner_id == user.id, Feedback.message_id == message.id)
        )
        if row is None:
            row = Feedback(owner_id=user.id, message_id=message.id)
            db.add(row)
        row.rating, row.comment = payload.rating, payload.comment
        db.commit()
        return {"status": "saved"}

    @app.get("/api/v1/admin/sources", tags=["admin"])
    def sources(user: User = Depends(admin_user), db: DBSession = Depends(get_db)):
        return [
            {
                "id": s.id,
                "title": s.title,
                "url": s.url,
                "checked_at": s.checked_at,
                "check_error": s.check_error,
            }
            for s in db.scalars(select(Source))
        ]

    @app.post("/api/v1/admin/sources/{source_id}/fetch", status_code=202, tags=["admin"])
    def ingest(source_id: str, user: User = Depends(admin_user), db: DBSession = Depends(get_db)):
        if source_id not in SOURCES:
            raise HTTPException(404, "Fonte não autorizada.")
        rate_limit(db, f"source:{user.id}", 5)
        job = enqueue(db, user, "fetch", {"source_id": source_id})
        db.commit()
        return job_view(job)

    @app.post("/api/v1/admin/documents/{document_id}/approve", status_code=202, tags=["admin"])
    def approve(
        document_id: str, user: User = Depends(admin_user), db: DBSession = Depends(get_db)
    ):
        doc = db.get(Document, document_id, with_for_update=True)
        if doc is None or doc.kind != "law" or doc.status != "pending_review":
            raise HTTPException(409, "A versão não está disponível para aprovação.")
        newer = db.scalar(
            select(Document.id)
            .where(Document.source_id == doc.source_id, Document.created_at > doc.created_at)
            .limit(1)
        )
        if newer:
            raise HTTPException(409, "Existe versão mais recente; revise a versão mais nova.")
        doc.approved_at, doc.approved_by, doc.status = now(), user.id, "indexing"
        job = enqueue(db, user, "index", {"document_id": doc.id})
        db.add(Audit(actor_id=user.id, action="source.approve", target_id=doc.id))
        db.commit()
        return job_view(job)

    @app.post("/api/v1/admin/documents/{document_id}/reindex", status_code=202, tags=["admin"])
    def reindex(
        document_id: str, user: User = Depends(admin_user), db: DBSession = Depends(get_db)
    ):
        doc = db.get(Document, document_id)
        if doc is None or doc.status != "indexing" or not doc.approved_at:
            raise HTTPException(
                409, "Somente versões aprovadas com indexação pendente podem ser reenfileiradas."
            )
        active = db.scalar(
            select(Job).where(Job.kind == "index", Job.status.in_(["queued", "running"]))
        )
        if active:
            raise HTTPException(409, "Aguarde a indexação em andamento.")
        job = enqueue(db, user, "index", {"document_id": doc.id})
        db.commit()
        return job_view(job)

    @app.get("/api/v1/admin/overview", tags=["admin"])
    def overview(user: User = Depends(admin_user), db: DBSession = Depends(get_db)):
        from jurisassist.evaluation import read_reports

        return {
            "jobs": [
                job_view(j)
                for j in db.scalars(select(Job).order_by(Job.created_at.desc()).limit(30))
            ],
            "feedback": [
                {"rating": f.rating, "comment": f.comment, "message_id": f.message_id}
                for f in db.scalars(select(Feedback).limit(50))
            ],
            "evaluations": read_reports(),
            "basis": basis_state(db),
        }

    @app.get("/api/v1/admin/metrics", tags=["admin"])
    def metrics(user: User = Depends(admin_user)):
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/v1/admin/metrics/worker", tags=["admin"])
    def worker_metrics(user: User = Depends(admin_user)):
        try:
            result = httpx.get(f"{settings.worker_metrics_url}/metrics", timeout=3, trust_env=False)
            result.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Métricas do worker indisponíveis.") from exc
        return Response(result.content, media_type=CONTENT_TYPE_LATEST)

    return app


dummy_hash = hasher.hash("dummy-account-password-not-a-credential")
app = create_app()
