# One image for the API, the indexer and migrations; the command picks the role.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.24 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
COPY --from=build /app/.venv /app/.venv
RUN useradd --uid 10001 --create-home app
WORKDIR /app
COPY alembic.ini ./
COPY migrations ./migrations
COPY corpus/sections.jsonl corpus/NOTICE ./corpus/
USER 10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/readyz').status==200 else 1)" || exit 1
CMD ["ska-api"]
