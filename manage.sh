#!/usr/bin/env bash
# =============================================================================
#  manage.sh — OCODX project manager  v3 (self-healing)
#
#  Usage:
#    ./manage.sh            – smart default: install if needed, then launch
#    ./manage.sh install    – full dep install: uv, Python venv, npm, Playwright
#    ./manage.sh web        – start API server + open browser
#    ./manage.sh test       – run the full pytest suite
#    ./manage.sh build      – rebuild the production frontend bundle
#    ./manage.sh doctor     – check all provider + dep readiness
#    ./manage.sh fix        – auto-repair: venv, pip deps, frontend build
#    ./manage.sh desktop    – (re)create the macOS Desktop launcher icon
#    ./manage.sh rezip      – re-create open-codex-master.zip cleanly
#    ./manage.sh stop       – stop a running server
# =============================================================================
set -Euo pipefail          # -E = ERR traps propagate into subshells

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
MAGENTA='\033[0;35m'

info()    { echo -e "${CYAN}[OCODX]${RESET}  $*"; }
success() { echo -e "${GREEN}[OCODX] ✓${RESET} $*"; }
warn()    { echo -e "${YELLOW}[OCODX] ⚠${RESET}  $*"; }
error()   { echo -e "${RED}[OCODX] ✗${RESET}  $*" >&2; }
die()     { error "$*"; exit 1; }
step()    { echo -e "\n${BOLD}${MAGENTA}▸ $*${RESET}"; }

# ── Paths & constants ─────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
FRONTEND="$SCRIPT_DIR/src/open_codex/frontend"
PORT=8000
API_URL="http://127.0.0.1:$PORT"
PID_FILE="$SCRIPT_DIR/.server.pid"
LOG_FILE="$SCRIPT_DIR/.server.log"
APP_NAME="OCODX"
APP_DISPLAY="OCODX — OpenCodex Desktop App"
DESKTOP="$HOME/Desktop"
APP_BUNDLE="$DESKTOP/${APP_NAME}.app"

# ── Homebrew PATH injection (macOS) ───────────────────────────────────────────
# System shell on macOS often lacks /opt/homebrew/bin; fix that first.
for _hb_prefix in /opt/homebrew /usr/local; do
    [[ -d "$_hb_prefix/bin" ]] && export PATH="$_hb_prefix/bin:$PATH"
done
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# ── Error trap ────────────────────────────────────────────────────────────────
_err_trap() {
    local code=$? line=$1
    error "Unexpected error on line ${line} (exit ${code})"
    error "Run with TRACE=1 ./manage.sh <cmd> for verbose output."
    error "Or run:  ./manage.sh fix   to auto-repair common issues."
    exit "$code"
}
trap '_err_trap $LINENO' ERR
[[ "${TRACE:-0}" == "1" ]] && set -x

# ── Smart pip finder (handles venvs built without pip) ────────────────────────
find_pip() {
    for c in "$VENV/bin/pip" "$VENV/bin/pip3" "$VENV/bin/python -m pip"; do
        # shellcheck disable=SC2086
        $c --version &>/dev/null 2>&1 && { echo $c; return 0; }
    done
    # Last resort: bootstrap pip into the venv
    if [[ -x "$VENV/bin/python" ]]; then
        warn "pip not found in venv — bootstrapping …"
        "$VENV/bin/python" -m ensurepip --upgrade 2>/dev/null \
            || curl -sSL https://bootstrap.pypa.io/get-pip.py | "$VENV/bin/python"
        "$VENV/bin/pip" --version &>/dev/null && { echo "$VENV/bin/pip"; return 0; }
        "$VENV/bin/pip3" --version &>/dev/null && { echo "$VENV/bin/pip3"; return 0; }
    fi
    return 1
}

# ── Venv health check: verify core imports work ───────────────────────────────
venv_is_healthy() {
    [[ -x "$VENV/bin/python" ]] || return 1
    "$VENV/bin/python" -c "import fastapi, uvicorn, httpx" &>/dev/null 2>&1
}

# ── pip install with retry ────────────────────────────────────────────────────
pip_install() {
    local PIP; PIP="$(find_pip)" || die "Cannot locate pip inside venv."
    local attempt=1
    while (( attempt <= 3 )); do
        # shellcheck disable=SC2086
        if $PIP install "$@" --quiet 2>&1; then
            return 0
        fi
        warn "pip install failed (attempt $attempt/3) — retrying …"
        sleep 2
        (( attempt++ )) || true
    done
    die "pip install failed after 3 attempts: $*"
}

# =============================================================================
# DEPENDENCY FINDERS
# =============================================================================

# ── uv ────────────────────────────────────────────────────────────────────────
find_uv() {
    for c in \
        "$(command -v uv 2>/dev/null || true)" \
        "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" \
        "/opt/homebrew/bin/uv" "/usr/local/bin/uv"; do
        [[ -n "$c" && -x "$c" ]] && { echo "$c"; return 0; }
    done
    return 1
}

ensure_uv() {
    if UV="$(find_uv)"; then
        info "uv → $UV  ($(${UV} --version 2>/dev/null | head -1))"
    else
        step "Installing uv (fast Python package manager) …"
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
        UV="$(find_uv)" || die "uv install failed — visit https://github.com/astral-sh/uv"
        success "uv installed: $UV"
    fi
}

UV=""

# ── Python ≥ 3.11 ─────────────────────────────────────────────────────────────
# The system /usr/bin/python3 on macOS ships as 3.9 (Command Line Tools).
# We need ≥ 3.11.  Try Homebrew first, then uv's bundled managed Python.
find_system_python() {
    for c in \
        "/opt/homebrew/bin/python3.14" \
        "/opt/homebrew/bin/python3.13" \
        "/opt/homebrew/bin/python3.12" \
        "/opt/homebrew/bin/python3.11" \
        "/usr/local/bin/python3.14" \
        "/usr/local/bin/python3.13" \
        "/usr/local/bin/python3.12" \
        "/usr/local/bin/python3.11" \
        "$(command -v python3 2>/dev/null || true)"; do
        if [[ -n "$c" && -x "$c" ]]; then
            local ver
            ver="$("$c" -c 'import sys; print(sys.version_info[:2])' 2>/dev/null || true)"
            # ver is like "(3, 12)"
            local minor
            minor="$(echo "$ver" | tr -d '() ' | cut -d',' -f2)"
            if [[ "${minor:-0}" -ge 11 ]]; then
                echo "$c"; return 0
            fi
        fi
    done
    return 1
}

PYTHON_BASE=""
ensure_python_base() {
    if PYTHON_BASE="$(find_system_python)"; then
        local ver; ver="$("$PYTHON_BASE" --version 2>&1)"
        info "Python base → $PYTHON_BASE  ($ver)"
    else
        warn "Python ≥ 3.11 not found on PATH — installing via uv managed Python …"
        ensure_uv
        "$UV" python install 3.12 --quiet
        PYTHON_BASE="$("$UV" python find 3.12 2>/dev/null)" \
            || die "Could not locate uv-managed Python 3.12"
        success "Python 3.12 provisioned via uv: $PYTHON_BASE"
    fi
}

# ── Node / npm ────────────────────────────────────────────────────────────────
ensure_node() {
    if ! command -v node &>/dev/null; then
        warn "Node.js not found."
        if command -v brew &>/dev/null; then
            step "Installing Node.js via Homebrew …"
            brew install node
        else
            die "Node.js is required. Install from https://nodejs.org or via Homebrew."
        fi
    fi
    local nver; nver="$(node --version)"
    info "Node  → $(command -v node)  ($nver)"
    info "npm   → $(command -v npm)   ($(npm --version))"
}

# ── mysql-connector-python (optional) ─────────────────────────────────────────
try_install_mysql_connector() {
    local PY="$VENV/bin/python"
    if "$PY" -c "import mysql.connector" &>/dev/null 2>&1; then
        return 0  # already installed
    fi
    info "mysql-connector-python not present — attempting install (optional, needed for YOO Builder MySQL direct mode) …"
    "$VENV/bin/pip" install mysql-connector-python --quiet \
        && success "mysql-connector-python installed." \
        || warn "mysql-connector-python install failed — YOO Builder MySQL tools won't work until you install it manually."
}

# ── google-genai (optional) ──────────────────────────────────────────────────
try_install_genai() {
    local PY="$VENV/bin/python"
    if "$PY" -c "import google.genai" &>/dev/null 2>&1; then
        return 0
    fi
    info "google-genai not present — installing …"
    "$VENV/bin/pip" install google-genai --quiet \
        && success "google-genai installed." \
        || warn "google-genai install failed — Gemini provider won't work."
}

# =============================================================================
# VENV + DEPS
# =============================================================================

PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"

ensure_venv() {
    ensure_uv
    ensure_python_base

    # Detect broken venv: python exists but can't run
    if [[ -x "$PYTHON" ]] && ! "$PYTHON" -c "import sys" &>/dev/null 2>&1; then
        warn "Broken venv detected — recreating …"
        rm -rf "$VENV"
    fi

    if [[ ! -x "$PYTHON" ]]; then
        step "Creating virtual environment at $VENV …"
        if ! "$UV" venv "$VENV" --python "$PYTHON_BASE" 2>/dev/null; then
            warn "uv venv failed — falling back to python -m venv …"
            "$PYTHON_BASE" -m venv "$VENV" || die "venv creation failed."
        fi
        # Bootstrap pip if missing
        if ! "$VENV/bin/python" -m pip --version &>/dev/null 2>&1; then
            info "Bootstrapping pip …"
            "$VENV/bin/python" -m ensurepip --upgrade 2>/dev/null \
                || curl -sSL https://bootstrap.pypa.io/get-pip.py | "$VENV/bin/python" \
                || warn "pip bootstrap failed — will retry during dep install."
        fi
        success "Venv ready."
    else
        local pver; pver="$("$PYTHON" --version 2>&1)"
        info "Venv → $VENV  ($pver)"
    fi
}

ensure_python_deps() {
    ensure_venv
    step "Installing / syncing Python dependencies …"

    local installed=0
    # Try uv first (fast), then pip fallback, then direct pip install
    if [[ -n "${UV:-}" ]] && "$UV" pip install --python "$PYTHON" -e "$SCRIPT_DIR[test]" --quiet 2>/dev/null; then
        success "Python dependencies synced via uv."
        installed=1
    fi
    if (( installed == 0 )); then
        warn "uv sync failed — trying pip …"
        local PIP_BIN; PIP_BIN="$(find_pip 2>/dev/null || true)"
        if [[ -n "$PIP_BIN" ]]; then
            # shellcheck disable=SC2086
            if $PIP_BIN install -e "$SCRIPT_DIR[test]" --quiet 2>/dev/null; then
                success "Python dependencies installed via pip."
                installed=1
            fi
        fi
    fi
    if (( installed == 0 )); then
        # Last resort: install core packages manually
        warn "pyproject.toml install failed — installing core packages directly …"
        pip_install fastapi uvicorn httpx ollama huggingface_hub anthropic
        success "Core packages installed."
    fi

    # Validate — if core imports still fail, try one more recreate
    if ! venv_is_healthy; then
        warn "Core imports failed after install — recreating venv and retrying …"
        rm -rf "$VENV"
        ensure_venv
        pip_install fastapi uvicorn httpx ollama huggingface_hub anthropic
        venv_is_healthy || die "Dependency install failed. Run: TRACE=1 ./manage.sh install"
    fi

    # Optional extras (non-fatal)
    step "Installing optional extras …"
    try_install_mysql_connector
    try_install_genai

    # Playwright
    if ! "$PYTHON" -c "import playwright" &>/dev/null 2>&1; then
        info "Installing playwright …"
        pip_install playwright 2>/dev/null || warn "playwright install failed — browser automation disabled."
    fi
    if "$PYTHON" -c "import playwright" &>/dev/null 2>&1; then
        "$PYTHON" -m playwright install chromium --quiet 2>/dev/null \
            && success "Playwright chromium ready." \
            || warn "Playwright browser binaries failed — run: .venv/bin/python -m playwright install chromium"
    fi
}

# ── Frontend ──────────────────────────────────────────────────────────────────
build_frontend() {
    ensure_node
    if [[ ! -d "$FRONTEND" ]]; then
        warn "Frontend source not found at $FRONTEND — skipping."; return
    fi
    step "Installing frontend npm dependencies …"
    if ! npm --prefix "$FRONTEND" install --silent 2>/dev/null; then
        warn "npm install failed — clearing node_modules and retrying …"
        rm -rf "$FRONTEND/node_modules" "$FRONTEND/.vite"
        npm --prefix "$FRONTEND" install --silent \
            || die "npm install failed twice. Check your internet connection."
    fi
    step "Building frontend …"
    if ! npm --prefix "$FRONTEND" run build 2>&1; then
        error "Frontend build failed. Common fixes:"
        error "  1. Check TypeScript errors above"
        error "  2. Run: cd $FRONTEND && npx tsc --noEmit"
        error "  3. Run: TRACE=1 ./manage.sh build"
        die "Frontend build failed."
    fi
    success "Frontend built → $SCRIPT_DIR/src/open_codex/static/"
}

# Full install
cmd_install() {
    echo -e "\n${BOLD}${CYAN}╔══════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${CYAN}║   OCODX — OpenCodex Desktop App Install  ║${RESET}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${RESET}\n"
    ensure_python_deps
    build_frontend
    cmd_desktop   # create/update desktop icon automatically on install
    echo ""
    echo -e "${BOLD}${GREEN}┌─ Installation complete ─────────────────────────────────────┐${RESET}"
    echo -e "${GREEN}│  Launch:        ./manage.sh web                                │${RESET}"
    echo -e "${GREEN}│  Or double-click '${APP_NAME}' on your Desktop                 │${RESET}"
    echo -e "${GREEN}│  Browser tab:   OCODX — OpenCodex Desktop App                 │${RESET}"
    echo -e "${GREEN}└─────────────────────────────────────────────────────────────────┘${RESET}"
}

# Auto-repair common issues
cmd_fix() {
    echo -e "\n${BOLD}${CYAN}╔══════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${CYAN}║      OCODX — Auto-Repair / Fix           ║${RESET}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${RESET}\n"

    step "Checking venv health …"
    if ! venv_is_healthy; then
        warn "Venv unhealthy — rebuilding from scratch …"
        rm -rf "$VENV"
    else
        success "Venv healthy."
    fi

    step "Reinstalling Python dependencies …"
    ensure_python_deps

    step "Checking frontend bundle …"
    if [[ ! -f "$SCRIPT_DIR/src/open_codex/static/index.html" ]]; then
        warn "Bundle missing — building …"
        build_frontend
    else
        success "Frontend bundle present."
    fi

    step "Verifying Python syntax …"
    local ok=1
    for f in \
        src/open_codex/api.py \
        src/open_codex/mcp_bridge.py \
        src/open_codex/mcp_servers.py \
        src/open_codex/mcp_servers_yoo.py \
        src/open_codex/agents/coding_agent.py; do
        if [[ -f "$f" ]]; then
            "$PYTHON" -c "import ast; ast.parse(open('$f').read())" 2>/dev/null \
                && success "  $f" \
                || { error "  SYNTAX ERROR: $f"; ok=0; }
        fi
    done
    (( ok )) && success "All Python files parse cleanly." \
              || warn "Syntax errors found — check files above."

    step "Recreating desktop icon …"
    cmd_desktop

    echo ""
    success "Fix complete.  Run:  ./manage.sh web"
}

# =============================================================================
# DOCTOR — provider readiness check
# =============================================================================
cmd_doctor() {
    echo ""
    echo -e "${BOLD}Open Codex — System Doctor${RESET}"
    echo "══════════════════════════════════════════════════════"

    _chk() {
        local label="$1" url="$2" fix="$3" tip="${4:-}"
        printf "  %-30s " "$label"
        if curl -sf --max-time 4 "$url" -o /dev/null 2>&1; then
            echo -e "${GREEN}✓  online${RESET}"
            if [[ -n "$tip" ]]; then
                echo -e "     ${CYAN}Tip:${RESET} $tip"
            fi
        else
            echo -e "${YELLOW}✗  not reachable${RESET}"
            echo -e "     ${CYAN}Fix:${RESET} $fix"
        fi
        return 0
    }

    step "LLM Providers"
    _chk "LM Studio  (localhost:1234)" \
        "http://localhost:1234/v1/models" \
        "Open LM Studio → Local Server tab → Start Server"

    echo -ne "  $(printf '%-30s' 'Ollama     (localhost:11434)')"
    if curl -sf --max-time 4 http://localhost:11434/api/tags -o /tmp/.ollama_tags 2>&1; then
        local _py; _py="${VENV}/bin/python"
        if [[ ! -x "$_py" ]]; then _py="python3"; fi
        local models
        models="$("$_py" -c "import json; d=json.load(open('/tmp/.ollama_tags')); print(', '.join(m['name'] for m in d.get('models',[])) or '(none pulled)')" 2>/dev/null || echo '?')"
        echo -e "${GREEN}✓  running${RESET}  models: $models"
        if [[ "$models" == "(none pulled)" ]]; then
            echo -e "     ${CYAN}Tip:${RESET} pull a model →  ollama pull llama3"
        fi
    else
        echo -e "${YELLOW}✗  not running${RESET}"
        echo -e "     ${CYAN}Fix:${RESET} run →  ollama serve"
    fi

    _chk "Ollama Cloud  (ollama.com)" \
        "https://ollama.com" \
        "Check internet connection or set OLLAMA_CLOUD_API_KEY in the UI" \
        "Get your key at https://ollama.com/settings/keys"

    _chk "Gemini API  (generativelanguage.googleapis.com)" \
        "https://generativelanguage.googleapis.com" \
        "Set GEMINI_API_KEY in the MCP Hub config drawer"

    step "Python deps"
    local PY="${VENV}/bin/python"
    if [[ ! -x "$PY" ]]; then
        warn "venv not found — run ./manage.sh install first"
    else
        local pver; pver="$("$PY" --version 2>&1)"
        echo -e "  Python venv          ${GREEN}✓${RESET}  $pver"
        for pkg in fastapi uvicorn ollama httpx huggingface_hub; do
            printf "  %-30s " "$pkg"
            "$PY" -c "import $pkg" 2>/dev/null \
                && echo -e "${GREEN}✓${RESET}" \
                || echo -e "${YELLOW}✗  missing — run ./manage.sh install${RESET}"
        done
        printf "  %-30s " "google-genai"
        "$PY" -c "import google.genai" 2>/dev/null \
            && echo -e "${GREEN}✓${RESET}" \
            || echo -e "${YELLOW}✗  missing — run ./manage.sh install${RESET}"
        printf "  %-30s " "mysql.connector (optional)"
        "$PY" -c "import mysql.connector" 2>/dev/null \
            && echo -e "${GREEN}✓${RESET}" \
            || echo -e "${YELLOW}✗  (optional) install: pip install mysql-connector-python${RESET}"
        printf "  %-30s " "playwright (optional)"
        "$PY" -c "import playwright" 2>/dev/null \
            && echo -e "${GREEN}✓${RESET}" \
            || echo -e "${YELLOW}✗  (optional) install included in ./manage.sh install${RESET}"
    fi

    step "Frontend"
    if [[ -f "$SCRIPT_DIR/src/open_codex/static/index.html" ]]; then
        echo -e "  Static bundle        ${GREEN}✓  built${RESET}"
    else
        echo -e "  Static bundle        ${YELLOW}✗  not built — run ./manage.sh build${RESET}"
    fi

    step "Node / npm"
    if command -v node &>/dev/null; then
        echo -e "  Node $(node --version)   $(command -v node)"
        echo -e "  npm  $(npm --version)"
    else
        echo -e "  ${YELLOW}✗  Node not found — install via brew install node${RESET}"
    fi

    echo ""
    echo "══════════════════════════════════════════════════════"
    echo ""
}

# =============================================================================
# SERVE
# =============================================================================

open_browser() {
    local url="$1"
    case "$(uname -s)" in
        Darwin)  sleep 1.5 && open "$url" &;;
        Linux)   sleep 1.5 && xdg-open "$url" 2>/dev/null &;;
        CYGWIN*|MINGW*) start "$url" ;;
    esac
}

wait_for_server() {
    local url="$API_URL/docs"
    local max=40 i
    info "Waiting for server at $API_URL …"
    for i in $(seq 1 $max); do
        if curl -sf "$url" -o /dev/null 2>&1; then
            success "Server up after ${i}×0.5s"
            return 0
        fi
        sleep 0.5
    done
    warn "Server did not respond in 20 s — opening browser anyway."
}

cmd_stop() {
    if [[ -f "$PID_FILE" ]]; then
        local pid; pid="$(cat "$PID_FILE")"
        if kill -0 "$pid" 2>/dev/null; then
            info "Stopping server (PID $pid) …"
            kill "$pid" 2>/dev/null || true
            sleep 1
            kill -9 "$pid" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
        success "Server stopped."
    else
        # Fallback: kill by port
        if lsof -ti tcp:$PORT >/dev/null 2>&1; then
            info "Killing process on port $PORT …"
            lsof -ti tcp:$PORT | xargs kill -9 2>/dev/null || true
            success "Port $PORT freed."
        else
            info "No server running."
        fi
    fi
}

cmd_web() {
    ensure_python_deps

    # Auto-build frontend if missing or stale (newer source than bundle)
    local _bundle="$SCRIPT_DIR/src/open_codex/static/index.html"
    if [[ ! -f "$_bundle" ]]; then
        warn "Frontend bundle not found — building now …"
        build_frontend
    elif [[ "$FRONTEND/src/App.tsx" -nt "$_bundle" ]] || \
         [[ "$FRONTEND/src/YooBuilderPanel.tsx" -nt "$_bundle" ]] || \
         [[ "$FRONTEND/index.html" -nt "$_bundle" ]]; then
        info "Frontend source is newer than bundle — rebuilding …"
        build_frontend
    fi

    cmd_doctor

    # Kill any process holding the port (including stale server)
    if lsof -ti tcp:$PORT >/dev/null 2>&1; then
        info "Port $PORT in use — stopping existing process …"
        lsof -ti tcp:$PORT | xargs kill -9 2>/dev/null || true
        sleep 1
    fi
    cmd_stop 2>/dev/null || true

    step "Starting Open Codex API on $API_URL …"
    "$PYTHON" -m uvicorn open_codex.api:app \
        --host 127.0.0.1 --port $PORT \
        --reload \
        2>&1 | tee -a "$LOG_FILE" &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$PID_FILE"

    wait_for_server
    open_browser "$API_URL"

    echo ""
    echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${RESET}"
    echo -e "${GREEN}  Open Codex → $API_URL${RESET}"
    echo -e "${GREEN}  Log  →  $LOG_FILE${RESET}"
    echo -e "${GREEN}  Stop →  ./manage.sh stop   or  Ctrl+C${RESET}"
    echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${RESET}"
    echo ""
    echo -e "  ${CYAN}AI Providers:${RESET}"
    echo -e "    Ollama local  — ${BOLD}ollama serve${RESET}  (then pull a model)"
    echo -e "    Ollama Cloud  — paste key from ollama.com/settings/keys in the UI"
    echo -e "    LM Studio     — open LM Studio → Local Server → Start Server"
    echo -e "    Gemini        — paste GEMINI_API_KEY in MCP Hub config"
    echo ""
    echo -e "  ${CYAN}YOO Builder MySQL (optional):${RESET}"
    echo -e "    Set YOOMYSQL_HOST / _USER / _PASSWORD / _DATABASE as env vars"
    echo -e "    or configure them in the YOO Builder config drawer in the UI."
    echo ""

    trap "cmd_stop; exit 0" INT TERM
    wait "$SERVER_PID" || true
}

# =============================================================================
# DESKTOP LAUNCHER (macOS .app bundle)
# =============================================================================
cmd_desktop() {
    if [[ "$(uname -s)" != "Darwin" ]]; then
        warn "Desktop launcher creation is macOS-only."; return
    fi

    step "Creating Desktop launcher: ${APP_NAME}.app …"

    # Remove any old branding (Open Codex.app → OCODX.app)
    [[ -d "$DESKTOP/Open Codex.app" ]] && rm -rf "$DESKTOP/Open Codex.app" && info "Removed old 'Open Codex.app' from Desktop."

    # Absolute path to manage.sh (works even if called from elsewhere)
    local MANAGE_SH="$SCRIPT_DIR/manage.sh"

    # Remove stale bundle
    rm -rf "$APP_BUNDLE"
    mkdir -p "$APP_BUNDLE/Contents/MacOS"
    mkdir -p "$APP_BUNDLE/Contents/Resources"

    # ── Info.plist ────────────────────────────────────────────────────────────
    cat > "$APP_BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>${APP_DISPLAY}</string>
    <key>CFBundleIdentifier</key>
    <string>com.ocodx.app</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSUIElement</key>
    <false/>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

    # ── Launcher shell script (the actual executable) ─────────────────────────
    cat > "$APP_BUNDLE/Contents/MacOS/launcher" <<LAUNCHER
#!/usr/bin/env bash
# Open Codex Desktop Launcher
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH"

MANAGE="${MANAGE_SH}"

# If server is already running, just open browser
if curl -sf http://127.0.0.1:8000/docs -o /dev/null 2>&1; then
    open "http://127.0.0.1:8000"
    exit 0
fi

# Open a Terminal window running manage.sh web
osascript <<'OSASCRIPT'
tell application "Terminal"
    activate
    do script "cd '${SCRIPT_DIR}' && bash '${MANAGE_SH}' web"
end tell
OSASCRIPT
LAUNCHER
    chmod +x "$APP_BUNDLE/Contents/MacOS/launcher"

    # ── Icon (generate a clean ICNS programmatically via Python + Pillow) ─────
    local ICNS_TARGET="$APP_BUNDLE/Contents/Resources/AppIcon.icns"

    # Try to generate with Pillow if available; gracefully skip if not
    "${VENV}/bin/python" 2>/dev/null <<PYICON || warn "Pillow not available — icon will use system default."
from PIL import Image, ImageDraw, ImageFont
import struct, io

def make_png(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Deep space gradient circle (dark navy → teal)
    for i in range(size // 2, 0, -1):
        t = i / (size / 2)
        r = int(8  + (0  - 8)  * (1 - t))
        g = int(18 + (150 - 18) * (1 - t))
        b = int(28 + (160 - 28) * (1 - t))
        pad = size // 2 - i
        d.ellipse([pad, pad, size - pad, size - pad], fill=(r, g, b, 255))
    # Subtle inner glow ring
    ring_pad = int(size * 0.06)
    d.ellipse(
        [ring_pad, ring_pad, size - ring_pad, size - ring_pad],
        outline=(99, 202, 183, 80),
        width=max(1, size // 64),
    )
    # "OCODX" text — two lines: "OC" top, "ODX" bottom for balance
    font_size = int(size * 0.26)
    font_sm   = int(size * 0.14)
    try:
        font  = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", font_size)
        font2 = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", font_sm)
    except Exception:
        font  = ImageFont.load_default()
        font2 = font
    # Main label
    txt = "OCODX"
    bbox = d.textbbox((0, 0), txt, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) / 2 - bbox[0]
    ty = (size - th) / 2 - bbox[1] - size * 0.04
    d.text((tx, ty), txt, font=font, fill=(255, 255, 255, 245))
    # Subtitle
    sub = "OpenCodex"
    sb = d.textbbox((0, 0), sub, font=font2)
    sw = sb[2] - sb[0]
    d.text(((size - sw) / 2 - sb[0], ty + th + size * 0.02), sub,
           font=font2, fill=(99, 202, 183, 180))
    buf = io.BytesIO(); img.save(buf, "PNG"); return buf.getvalue()

TYPES = {
    "icp4":  16,
    "icp5":  32,
    "icp6":  64,
    "ic07": 128,
    "ic08": 256,
    "ic09": 512,
    "ic10":1024,
}
chunks = b""
for typ, sz in TYPES.items():
    data = make_png(sz)
    chunks += typ.encode() + struct.pack(">I", len(data) + 8) + data
icns = b"icns" + struct.pack(">I", len(chunks) + 8) + chunks
open("${ICNS_TARGET}", "wb").write(icns)
print("OCODX icon generated: ${ICNS_TARGET}")
PYICON

    # ── Quarantine removal + registration ─────────────────────────────────────
    xattr -cr "$APP_BUNDLE" 2>/dev/null || true
    # Touch so Finder refreshes the icon cache
    touch "$APP_BUNDLE"

    success "Desktop launcher created: $APP_BUNDLE"
    info "Double-click '${APP_NAME}' on your Desktop to launch OCODX."
}

# =============================================================================
# TESTS
# =============================================================================
cmd_test() {
    ensure_python_deps
    step "Running test suite …"
    "$PYTHON" -m pytest "$SCRIPT_DIR/tests" -v --tb=short \
        || { error "Tests failed."; exit 1; }
}

# =============================================================================
# BUILD FRONTEND
# =============================================================================
cmd_build() {
    ensure_node
    build_frontend
}

# =============================================================================
# REZIP
# =============================================================================
cmd_rezip() {
    local out="$SCRIPT_DIR/../open-codex-master.zip"
    step "Building clean zip → $out …"
    "$PYTHON" - <<'PYEOF'
import zipfile, pathlib

src    = pathlib.Path(".")
out    = pathlib.Path("../open-codex-master.zip")
PREFIX = "open-codex-master"

EXCLUDE = {".venv","__pycache__",".pytest_cache",".git",
           "dist","build","debbuild","node_modules"}

def skip(rel):
    return any(p in EXCLUDE or p.endswith(".egg-info") for p in rel.parts)

out.unlink(missing_ok=True)
count = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if skip(rel): continue
        zf.write(p, pathlib.Path(PREFIX) / rel)
        count += 1
mb = out.stat().st_size / 1_048_576
print(f"✓  {count} entries  {mb:.1f} MB  →  {out}")
PYEOF
    success "Zip ready: $out"
}

# =============================================================================
# DISPATCH
# =============================================================================
CMD="${1:-}"
cd "$SCRIPT_DIR"

# Interaction: Choose deployment method
prompt_setup() {
    clear
    echo -e "${BOLD}${CYAN}⬡ OCODX — Sovereign Liquid Matrix (SLM-v3)${RESET}"
    echo -e "Choose your preferred deployment method:\n"
    echo -e "  ${BOLD}1)${RESET} ${BOLD}Standard Local Setup${RESET} (Native macOS/Linux, faster UI, direct access)"
    echo -e "  ${BOLD}2)${RESET} ${BOLD}Docker Deployment${RESET}   (Clean, containerized, easy cleanup)\n"
    
    read -rp "Select [1-2, default=1]: " choice
    case "$choice" in
        2) 
            info "Initializing Docker Deployment..."
            if [ ! -f .env ]; then
                cp .env.example .env
                info "Created .env from template. Edit it for custom AI keys."
            fi
            docker-compose up -d --build
            success "OCODX is launching in Docker at http://localhost:8000"
            touch "$SCRIPT_DIR/.docker_selected"
            exit 0
            ;;
        *) 
            info "Proceeding with Standard Local Setup..."
            # Continue to default local install/run logic
            ;;
    esac
}

# Smart default: if no arg given, install if needed then launch
if [[ -z "$CMD" ]]; then
    if [[ ! -d "$VENV" ]] && [[ ! -f "$SCRIPT_DIR/.docker_selected" ]]; then
        prompt_setup
    fi
    
    if ! venv_is_healthy 2>/dev/null || [[ ! -f "$SCRIPT_DIR/src/open_codex/static/index.html" ]]; then
        echo -e "\n${BOLD}${CYAN}OCODX — First run detected. Running install …${RESET}\n"
        cmd_install
    fi
    cmd_web
    exit 0
fi

case "$CMD" in
    install) cmd_install ;;
    web)     cmd_web ;;
    docker)  
        info "Running in Docker..."
        docker-compose up -d --build
        ;;
    stop)    cmd_stop ;;
    test)    cmd_test ;;
    build)   cmd_build ;;
    doctor)  cmd_doctor ;;
    fix)     cmd_fix ;;
    desktop) cmd_desktop ;;
    rezip)   cmd_rezip ;;
    help|--help|-h)
        echo ""
        echo -e "${BOLD}OCODX — OpenCodex Desktop App  (manage.sh)${RESET}"
        echo ""
        echo -e "  ${CYAN}./manage.sh${RESET}           Smart default: install if needed, then launch"
        echo -e "  ${CYAN}./manage.sh docker${RESET}    Launch the full stack in Docker"
        echo -e "  ${CYAN}./manage.sh install${RESET}   Full install: venv, Python deps, npm, frontend, icon"
        echo -e "  ${CYAN}./manage.sh web${RESET}       Start API server + open browser"
        echo -e "  ${CYAN}./manage.sh stop${RESET}      Stop a running server"
        echo -e "  ${CYAN}./manage.sh build${RESET}     Rebuild the frontend bundle"
        echo -e "  ${CYAN}./manage.sh test${RESET}      Run the full pytest suite"
        echo -e "  ${CYAN}./manage.sh doctor${RESET}    Check all provider + dep readiness"
        echo -e "  ${CYAN}./manage.sh fix${RESET}       Auto-repair venv, deps, frontend, icon"
        echo -e "  ${CYAN}./manage.sh desktop${RESET}   (Re)create the Desktop launcher icon"
        echo -e "  ${CYAN}./manage.sh rezip${RESET}     Rebuild open-codex-master.zip"
        echo ""
        echo -e "  ${CYAN}TRACE=1 ./manage.sh <cmd>${RESET}  Verbose shell trace for debugging"
        echo ""
        ;;
    *)
        error "Unknown command: '$CMD'"
        echo -e "  Run  ${CYAN}./manage.sh help${RESET}  to see available commands."
        exit 1
        ;;
esac
