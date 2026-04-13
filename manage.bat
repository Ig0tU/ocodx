@echo off
setlocal enabledelayedexpansion
:: =============================================================================
::  manage.bat — OCODX project manager  v3 (self-healing)
::
::  Usage:
::    manage.bat            – smart default: install if needed, then launch
::    manage.bat docker     – launch the full stack in Docker
::    manage.bat install    – full dep install: uv, Python venv, npm, Playwright
::    manage.bat web        – start API server + open browser
::    manage.bat test       – run the full pytest suite
::    manage.bat build      – rebuild the production frontend bundle
::    manage.bat doctor     – check all provider + dep readiness
::    manage.bat fix        – auto-repair: venv, pip deps, frontend build
::    manage.bat rezip      – re-create open-codex-master.zip cleanly
::    manage.bat stop       – stop a running server
:: =============================================================================

:: ── ANSI colours (requires Windows 10 1511+ Terminal) ────────────────────────
for /f %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"
set "CYAN=%ESC%[0;36m"
set "GREEN=%ESC%[0;32m"
set "YELLOW=%ESC%[1;33m"
set "RED=%ESC%[0;31m"
set "MAGENTA=%ESC%[0;35m"
set "BOLD=%ESC%[1m"
set "RESET=%ESC%[0m"

set "SCRIPT_DIR=%~dp0"
:: Strip trailing backslash
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "VENV=%SCRIPT_DIR%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"
set "UVICORN=%VENV%\Scripts\uvicorn.exe"
set "PYTEST=%VENV%\Scripts\pytest.exe"
set "FRONTEND=%SCRIPT_DIR%\src\open_codex\frontend"
set "PORT=8000"
set "API_URL=http://127.0.0.1:%PORT%"

:: ─────────────────────────────────────────────────────────────────────────────

:dispatch
set "CMD=%~1"
if "%CMD%"=="" (
    :: Smart default: if run without args, check if we need to ask
    if not exist "%PYTHON%" (
        if not exist "%SCRIPT_DIR%\.docker_selected" (
            call :prompt_setup
        )
    )

    :: Install if missing core components, then web
    if not exist "%PYTHON%" (
        echo.
        echo %BOLD%[OCODX] First run detected. Running install ...%RESET%
        call :do_install
    ) else (
        :: Check if frontend is built
        if not exist "%SCRIPT_DIR%\src\open_codex\static\index.html" (
            echo.
            echo %BOLD%[OCODX] Frontend bundle missing. Running install ...%RESET%
            call :do_install
        )
    )
    goto :do_web
)
if /i "%CMD%"=="install" goto :do_install
if /i "%CMD%"=="web"     goto :do_web
if /i "%CMD%"=="docker"  goto :do_docker
if /i "%CMD%"=="stop"    goto :do_stop
if /i "%CMD%"=="test"    goto :do_test
if /i "%CMD%"=="build"   goto :do_build
if /i "%CMD%"=="doctor"  goto :do_doctor
if /i "%CMD%"=="fix"     goto :do_fix
if /i "%CMD%"=="rezip"   goto :do_rezip
if /i "%CMD%"=="help"    goto :help
if /i "%CMD%"=="-h"      goto :help
if /i "%CMD%"=="--help"  goto :help
echo %RED%[OCODX] ERROR%RESET% Unknown command: %CMD%
echo Run:  manage.bat help
exit /b 1

:: ── Interaction ──────────────────────────────────────────────────────────────

:prompt_setup
cls
echo %BOLD%%CYAN%⬡ OCODX — Sovereign Liquid Matrix (SLM-v3)%RESET%
echo Choose your preferred deployment method:
echo.
echo   %BOLD%1)%RESET% %BOLD%Standard Local Setup%RESET% (Native Windows, faster UI, direct access)
echo   %BOLD%2)%RESET% %BOLD%Docker Deployment%RESET%   (Clean, containerized, easy cleanup)
echo.
set /p choice="Select [1-2, default=1]: "
if "%choice%"=="2" (
    call :info "Initializing Docker Deployment..."
    if not exist ".env" (
        copy ".env.example" ".env"
        call :info "Created .env from template. Edit it for custom AI keys."
    )
    docker-compose up -d --build
    call :success "OCODX is launching in Docker at http://localhost:8000"
    echo docker > "%SCRIPT_DIR%\.docker_selected"
    exit /b 0
)
call :info "Proceeding with Standard Local Setup..."
exit /b 0

:: ── Helpers ──────────────────────────────────────────────────────────────────

:info
echo %CYAN%[OCODX]%RESET%  %~1
exit /b 0

:success
echo %GREEN%[OCODX] ✓%RESET% %~1
exit /b 0

:warn
echo %YELLOW%[OCODX] ⚠%RESET%  %~1
exit /b 0

:err
echo %RED%[OCODX] ✗%RESET%  %~1
exit /b 0

:step
echo.
echo %BOLD%%MAGENTA%▸ %~1%RESET%
exit /b 0

:: ── Docker ───────────────────────────────────────────────────────────────────

:do_docker
call :info "Running in Docker..."
docker-compose up -d --build
exit /b 0

:: ── Locate uv ────────────────────────────────────────────────────────────────

:find_uv
set "UV="
for %%P in (
    "%USERPROFILE%\.local\bin\uv.exe"
    "%USERPROFILE%\.cargo\bin\uv.exe"
    "%USERPROFILE%\AppData\Roaming\uv\uv.exe"
    "C:\Program Files\uv\uv.exe"
) do (
    if exist %%P (
        set "UV=%%~P"
        goto :find_uv_done
    )
)
:: Try PATH
where uv >nul 2>&1
if %errorlevel%==0 (
    for /f "delims=" %%i in ('where uv') do set "UV=%%i" & goto :find_uv_done
)
:find_uv_done
exit /b 0

:ensure_uv
call :find_uv
if not defined UV (
    call :step "Installing uv (fast Python package manager) ..."
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "irm https://astral.sh/uv/install.ps1 | iex"
    if %errorlevel% neq 0 (
        call :err "uv installation failed."
        echo Please install manually: https://github.com/astral-sh/uv
        exit /b 1
    )
    call :find_uv
    if not defined UV (
        call :err "uv still not found after install. Restart this terminal."
        exit /b 1
    )
    call :success "uv installed: %UV%"
)
exit /b 0

:: ── Ensure venv + deps ───────────────────────────────────────────────────────

:ensure_venv
call :ensure_uv
if not exist "%PYTHON%" (
    call :step "Creating virtual environment at %VENV% ..."
    "%UV%" venv "%VENV%" --python python
    if %errorlevel% neq 0 (
        call :warn "uv venv failed — falling back to python -m venv ..."
        python -m venv "%VENV%" || (
            call :err "Failed to create venv. Is Python installed?"
            exit /b 1
        )
    )
    :: Bootstrap pip if missing
    if not exist "%PIP%" (
        call :info "Bootstrapping pip ..."
        "%PYTHON%" -m ensurepip --upgrade >nul 2>&1 || (
            powershell -NoProfile -ExecutionPolicy Bypass -Command ^
                "Invoke-WebRequest https://bootstrap.pypa.io/get-pip.py -OutFile '%TEMP%\get-pip.py'; & '%PYTHON%' '%TEMP%\get-pip.py'"
        )
    )
    call :success "Venv ready."
)
exit /b 0

:do_install
call :ensure_deps
call :build_frontend
call :success "Installation complete. Run: manage.bat"
exit /b 0

:ensure_deps
call :ensure_venv
if %errorlevel% neq 0 exit /b 1
call :step "Installing / syncing Python dependencies ..."
"%UV%" pip install --python "%PYTHON%" -e "%SCRIPT_DIR%[test]" --quiet
if %errorlevel% neq 0 (
    call :warn "uv sync failed — trying direct pip install ..."
    "%PYTHON%" -m pip install -e "%SCRIPT_DIR%[test]" --quiet || (
        call :err "Dependency install failed."
        exit /b 1
    )
)
call :success "Python dependencies ready."

:: Optional extras (non-fatal)
call :step "Installing optional extras ..."
"%PYTHON%" -m pip install mysql-connector-python google-genai playwright --quiet 2>nul
if %errorlevel%==0 (
    call :success "Optional packages (mysql, genai, playwright) installed."
)

if exist "%PYTHON%" (
    "%PYTHON%" -m playwright install chromium --quiet 2>nul
    if %errorlevel%==0 call :success "Playwright chromium ready."
)
exit /b 0

:: ── Build frontend ───────────────────────────────────────────────────────────

:build_frontend
if not exist "%FRONTEND%" (
    call :warn "Frontend source not found. Skipping."
    exit /b 0
)
call :info "Installing frontend npm dependencies..."
where npm >nul 2>&1
if %errorlevel% neq 0 (
    call :warn "npm not found. Skipping frontend build."
    call :warn "Install Node.js from https://nodejs.org/ and re-run."
    exit /b 0
)
npm --prefix "%FRONTEND%" install --silent
if %errorlevel% neq 0 ( call :err "npm install failed." & exit /b 1 )
call :info "Building frontend..."
npm --prefix "%FRONTEND%" run build
if %errorlevel% neq 0 ( call :err "Frontend build failed." & exit /b 1 )
call :success "Frontend built."
exit /b 0

:: ── Doctor ───────────────────────────────────────────────────────────────────

:do_doctor
echo.
echo %BOLD%OCODX — System Doctor%RESET%
echo ════════════════════════════════════════════════════════════════════════════

:: LM Studio
set "LM_OK=0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { $r = Invoke-WebRequest http://localhost:1234/v1/models -TimeoutSec 3 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 ( set "LM_OK=1" )

<nul set /p "=  LM Studio  (localhost:1234)    ... "
if "%LM_OK%"=="1" (
    echo %GREEN%✓  online%RESET%
) else (
    echo %YELLOW%—  not reachable%RESET%
    echo      %CYAN%Fix:%RESET% Open LM Studio → Local Server tab → Start Server
)

:: Ollama local
set "OLL_OK=0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { Invoke-WebRequest http://localhost:11434/api/tags -TimeoutSec 3 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 ( set "OLL_OK=1" )

<nul set /p "=  Ollama     (localhost:11434)   ... "
if "%OLL_OK%"=="1" (
    echo %GREEN%✓  running%RESET%
) else (
    echo %YELLOW%—  not running%RESET%
    echo      %CYAN%Fix:%RESET% run →  ollama serve
)

:: Ollama Cloud
set "CLOUD_OK=0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { Invoke-WebRequest https://ollama.com -TimeoutSec 5 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 ( set "CLOUD_OK=1" )

<nul set /p "=  Ollama Cloud (ollama.com)       ... "
if "%CLOUD_OK%"=="1" (
    echo %GREEN%✓  reachable%RESET%
) else (
    echo %YELLOW%—  no internet or ollama.com down%RESET%
)

:: Python Deps check
call :step "Python deps"
if not exist "%PYTHON%" (
    call :warn "venv not found — run manage.bat install first"
) else (
    for /f "delims=" %%v in ('"%PYTHON%" --version') do set "PVER=%%v"
    echo   Python venv          %GREEN%✓%RESET%  !PVER!
    for %%P in (fastapi uvicorn ollama httpx) do (
        <nul set /p "=  %%P                   "
        "%PYTHON%" -c "import %%P" >nul 2>&1
        if !errorlevel!==0 ( echo %GREEN%✓%RESET% ) else ( echo %YELLOW%—  missing%RESET% )
    )
    <nul set /p "=  google-genai            "
    "%PYTHON%" -c "import google.genai" >nul 2>&1
    if !errorlevel!==0 ( echo %GREEN%✓%RESET% ) else ( echo %YELLOW%—  missing%RESET% )
    
    <nul set /p "=  mysql-connector-python  "
    "%PYTHON%" -c "import mysql.connector" >nul 2>&1
    if !errorlevel!==0 ( echo %GREEN%✓%RESET% ) else ( echo %YELLOW%—  missing%RESET% )
)

call :step "Frontend"
if exist "%SCRIPT_DIR%\src\open_codex\static\index.html" (
    echo   Static bundle        %GREEN%✓  built%RESET%
) else (
    echo   Static bundle        %YELLOW%—  not built — run manage.bat build%RESET%
)

echo ════════════════════════════════════════════════════════════════════════════
echo.
exit /b 0

:: ── Fix ──────────────────────────────────────────────────────────────────────

:do_fix
call :step "OCODX — Auto-Repair / Fix"
if exist "%VENV%" (
    call :info "Checking venv health ..."
    "%PYTHON%" -c "import fastapi" >nul 2>&1 || (
        call :warn "Venv unhealthy — rebuilding ..."
        rmdir /s /q "%VENV%"
    )
)
call :ensure_deps
call :build_frontend
call :success "Fix complete. Run: manage.bat web"
exit /b 0

:: ── Kill anything on PORT ───────────────────────────────────────────────────

:do_stop
call :info "Stopping server on port %PORT% ..."
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% "') do (
    taskkill /PID %%a /F >nul 2>&1
)
call :success "Server stopped."
exit /b 0

:kill_port
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% "') do (
    taskkill /PID %%a /F >nul 2>&1
)
exit /b 0

:: ── Wait for server ──────────────────────────────────────────────────────────

:wait_for_server
call :info "Waiting for server at %API_URL% ..."
set /a "TRIES=0"
:wait_loop
set /a "TRIES+=1"
if %TRIES% gtr 30 (
    call :warn "Server did not respond within 15s — opening browser anyway."
    exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { Invoke-WebRequest %API_URL%/docs -TimeoutSec 1 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
    call :success "Server is up."
    exit /b 0
)
timeout /t 1 /nobreak >nul
goto :wait_loop

:: ── web ──────────────────────────────────────────────────────────────────────

:do_web
call :ensure_deps
if %errorlevel% neq 0 exit /b 1

:: Auto-build frontend if missing
if not exist "%SCRIPT_DIR%\src\open_codex\static\index.html" (
    call :warn "Frontend bundle missing — building now ..."
    call :build_frontend
)

call :do_doctor

call :info "Stopping any previous instance on port %PORT% ..."
call :kill_port
timeout /t 1 /nobreak >nul

call :step "Starting OCODX API on %API_URL% ..."
start "" /b "%PYTHON%" -m uvicorn open_codex.api:app ^
    --host 127.0.0.1 --port %PORT% --reload

call :wait_for_server

call :info "Opening browser ..."
start "" "%API_URL%"

call :success "OCODX running at %API_URL%   (Ctrl+C to stop)"
echo.
echo   %CYAN%Providers:%RESET%
echo     Ollama local -- run:  ollama serve
echo     Ollama Cloud -- paste key from ollama.com/settings/keys in the UI
echo     LM Studio    -- open LM Studio → Local Server → Start Server
echo     Gemini       -- paste GEMINI_API_KEY in the UI
echo.

:: Keep window alive
:web_loop
timeout /t 5 /nobreak >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { Invoke-WebRequest %API_URL%/docs -TimeoutSec 2 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% neq 0 (
    call :warn "Server stopped."
    exit /b 0
)
goto :web_loop

:: ── rezip ────────────────────────────────────────────────────────────────────

:do_rezip
call :ensure_venv
if %errorlevel% neq 0 exit /b 1

set "ZIPOUT=%SCRIPT_DIR%\..\open-codex-master.zip"
call :step "Building clean zip → %ZIPOUT% ..."
"%PYTHON%" -c ^"
import zipfile, pathlib, os

src    = pathlib.Path(r'%SCRIPT_DIR%')
out    = pathlib.Path(r'%ZIPOUT%')
PREFIX = 'open-codex-master'

EXCLUDE = {'.venv', '__pycache__', '.pytest_cache', '.git', 'dist', 'build', 'debbuild', 'node_modules'}

def skip(rel):
    return any(p in EXCLUDE or p.endswith('.egg-info') for p in rel.parts)

out.unlink(missing_ok=True)
count = 0
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for p in sorted(src.rglob('*')):
        rel = p.relative_to(src)
        if skip(rel):
            continue
        zf.write(p, pathlib.Path(PREFIX) / rel)
        count += 1

mb = out.stat().st_size / 1_048_576
print(f'OK  {count} entries  {mb:.1f} MB  -^>  {out}')
^"
if %errorlevel% neq 0 ( call :err "Rezip failed." & exit /b 1 )
call :success "Zip ready: %ZIPOUT%"
exit /b 0

:: ── help ─────────────────────────────────────────────────────────────────────

:help
echo.
echo %BOLD%OCODX — OpenCodex Desktop App (manage.bat)%RESET%
echo.
echo   %CYAN%manage.bat%RESET%           Smart default: install if needed, then launch
echo   %CYAN%manage.bat docker%RESET%    Launch the full stack in Docker
echo   %CYAN%manage.bat install%RESET%   Full install: venv, Python deps, npm, frontend
echo   %CYAN%manage.bat web%RESET%       Start API server + open browser
echo   %CYAN%manage.bat stop%RESET%      Stop a running server
echo   %CYAN%manage.bat build%RESET%     Rebuild the frontend bundle
echo   %CYAN%manage.bat test%RESET%      Run the full pytest suite
echo   %CYAN%manage.bat doctor%RESET%    Check all provider + dep readiness
echo   %CYAN%manage.bat fix%RESET%       Auto-repair venv, deps, frontend
echo   %CYAN%manage.bat rezip%RESET%     Rebuild open-codex-master.zip
echo.
exit /b 0
