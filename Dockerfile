# ============================================================================
#  OCODX — Full-suite Sovereign Liquid Matrix (SLM-v3) Docker Image
#
#  Stage 1: Build Frontend (React/Vite → Static Assets)
#  Stage 2: Runtime (FastAPI + SLM-v3 Matrix + MCP Toolset + AionUI)
# ============================================================================

# ── Stage 1: Frontend Build ───────────────────────────────────────────────────
FROM node:22-alpine AS frontend-builder

WORKDIR /build
# Cache node_modules using package.json
COPY src/open_codex/frontend/package.json src/open_codex/frontend/package-lock.json* ./
RUN npm ci 2>/dev/null || npm install

# Build the assets
COPY src/open_codex/frontend/ ./
RUN npm run build
# Vite outDir '../static' results in output at /static relative to /build/src/open_codex/frontend
# But since we are in /build, and the config says '../static', it will be in /static.

# ── Stage 2: Python Runtime ───────────────────────────────────────────────────
FROM python:3.12-slim

# System dependencies for AionUI (Playwright), Llama-cpp, and CMS operations
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
        xvfb \
    && rm -rf /var/lib/apt/lists/*

# Install UV for high-speed dependency orchestration
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# ── OCODX Core Installation ──────────────────────────────────────────────────
COPY pyproject.toml uv.lock ./
COPY README.md ./

# Install core dependencies using uv
RUN uv pip install --system --no-cache .

# ── Optional Extra Dependencies ──────────────────────────────────────────────
RUN uv pip install --system --no-cache \
        mysql-connector-python \
        google-genai \
        pyperclip \
        httpx \
        playwright

# Install AionUI Browser (Playwright Chromium)
RUN uv run playwright install --with-deps chromium

# ── Joomla MCP & SLM Matrix Companion ────────────────────────────────────────
COPY joomcpla-main/ ./joomcpla-main/
RUN uv pip install --system --no-cache \
        black \
        bleach \
        markdown \
        "mcp[cli]" \
        google-generativeai \
        transformers \
        tokenizers \
        torch --index-url https://download.pytorch.org/whl/cpu

# Install joomcpla as a local package if available
RUN if [ -f joomcpla-main/pyproject.toml ]; then \
        uv pip install --system --no-cache ./joomcpla-main 2>/dev/null || true; \
    fi

# ── Final Assembly ───────────────────────────────────────────────────────────
# Copy the actual source code
COPY src/ ./src/

# Overlay the built frontend static assets
COPY --from=frontend-builder /static/ ./src/open_codex/static/

# Persistence mapping for projects and threads
ENV HOME=/root
RUN mkdir -p /root/.open_codex

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

# OCODX Metadata
LABEL org.opencontainers.image.title="OCODX"
LABEL org.opencontainers.image.description="Sovereign Liquid Matrix (SLM-v3) Autonomous AI Engine"
LABEL org.opencontainers.image.vendor="AionUI"
LABEL org.opencontainers.image.version="0.1.18"

# Start the OCODX API Server
CMD ["python", "-m", "uvicorn", "open_codex.api:app", "--host", "0.0.0.0", "--port", "8000"]
