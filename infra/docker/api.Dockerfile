# GigBid Python image: API, worker, GigSim and the three MCP servers share it (different commands).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install "fastapi==0.162.7" "uvicorn[standard]==0.54.0" "pydantic==2.13.5" "pyyaml==6.0.3" "langgraph==1.2.21" \
    "langgraph-checkpoint-sqlite==3.1.3" "langgraph-checkpoint-postgres==3.2.0" "langgraph-supervisor==0.0.31" "langchain-core==1.8.0" "langchain-openai==1.8.0" "langchain-mcp-adapters==0.3.2" \
    "mcp==1.30.0" "httpx==0.28.1" "sqlalchemy==2.1.8" "psycopg[binary,pool]==3.3.9" "aiosqlite==0.22.1" "arq==0.28.0" "redis==5.3.1" numpy scikit-learn \
    "pypdf==6.17.0" "python-multipart==0.0.32" "PyJWT==2.15.0" cryptography reportlab "fastembed==0.9.1" "qdrant-client==1.15.1" langsmith
COPY . .
RUN pip install --no-deps -e . && python -m scripts.generate_data
RUN useradd -m app && mkdir -p /app/data/processed && chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --retries=5 CMD curl -fs http://localhost:${PORT:-8000}/api/healthz || exit 1
CMD ["sh", "-c", "python -m scripts.seed && uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
