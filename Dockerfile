# ============================================================================
#  Open Codex — Full-suite Docker image
#  Stage 1: Build frontend (Node/Vite → static assets)
#  Stage 2: Python runtime  (FastAPI + uvicorn + ALL optional deps)
# ============================================================================

# ── Stage 1: Frontend ────────────────────────────────────────────────────────
FROM node:22-alpine AS frontend

WORKDIR /build
COPY src/open_codex/frontend/package.json src/open_codex/frontend/package-lock.json* ./
RUN npm ci 2>/dev/null || npm install
COPY src/open_codex/frontend/ ./
RUN npm run build
# vite outDir '../static' relative to /build → output at /static

# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim

# System deps for native extensions (llama-cpp, torch, playwright, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        git \
        curl \
        wget \
        libgomp1 \
        libglib2.0-0 \
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libdbus-1-3 \
        libxkbcommon0 \
        libx11-6 \
        libxcomposite1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2 \
        libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Open Codex core ──────────────────────────────────────────────────────────
COPY pyproject.toml ./
COPY src/ ./src/
COPY README.md ./

RUN pip install --no-cache-dir setuptools wheel && \
    pip install --no-cache-dir ".[test]"

# ── Optional extras (all baked in) ───────────────────────────────────────────
RUN pip install --no-cache-dir \
        mysql-connector-python \
        google-genai \
        pyperclip \
        httpx \
        playwright

# Playwright Chromium browser binary
RUN python -m playwright install chromium

# ── Joomla MCP companion deps ───────────────────────────────────────────────
COPY joomcpla-main/ ./joomcpla-main/
RUN pip install --no-cache-dir \
        black \
        bleach \
        markdown \
        "mcp[cli]" \
        google-generativeai \
        transformers \
        tokenizers \
        torch --index-url https://download.pytorch.org/whl/cpu

# Install joomcpla as a package if it has a pyproject.toml
RUN if [ -f joomcpla-main/pyproject.toml ]; then \
        pip install --no-cache-dir ./joomcpla-main 2>/dev/null || true; \
    fi

# ── Built frontend overlay ──────────────────────────────────────────────────
COPY --from=frontend /static/ ./src/open_codex/static/

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

# Labels for registry
LABEL org.opencontainers.image.title="open-codex"
LABEL org.opencontainers.image.description="AI CLI with OSS LLM integration — full suite"
LABEL org.opencontainers.image.version="0.1.18"

CMD ["python", "-m", "uvicorn", "open_codex.api:app", "--host", "0.0.0.0", "--port", "8000"]
