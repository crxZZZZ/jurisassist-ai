FROM ghcr.io/astral-sh/uv:0.13.5 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra embeddings --no-install-project
COPY backend ./backend
RUN uv sync --frozen --no-dev --extra embeddings && useradd --uid 10001 --create-home appuser && mkdir -p /app/data && chown -R appuser:appuser /app/data
COPY alembic.ini ./
COPY migrations ./migrations
COPY evaluation ./evaluation
COPY corpus ./corpus
USER appuser
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "jurisassist.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
