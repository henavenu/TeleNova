#!/usr/bin/env bash
# TeleNova (Nova assistant) — standalone launcher (macOS / Linux), port 5002.
# The app is a client of the Trust platform: it installs the RAI Trust SDK from
# sdk-dist/wheelhouse and reaches the Trust APIs over HTTP. Which platform it talks
# to (local beta / GCP) is set by RAI_PE_URL + RAI_PAP_URL in rai.env and
# RAI_APP_KEY in .env — no platform code lives in this repo.
set -euo pipefail
cd "$(dirname "$0")"

export APP_PORT="${APP_PORT:-5002}"

VENV="./venv"
PY="$VENV/bin/python"

# Deps (langchain-core 1.4.8 etc.) need Python >=3.10; macOS system python3 is often
# 3.9, so prefer a newer interpreter. Override with PYTHON=/path/to/python.
pick_python() {
  if [ -n "${PYTHON:-}" ]; then echo "$PYTHON"; return; fi
  for c in python3.12 python3.13 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && \
       "$c" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)' 2>/dev/null; then
      echo "$c"; return
    fi
  done
  echo ""
}

if [ ! -x "$PY" ]; then
  BOOT_PY="$(pick_python)"
  if [ -z "$BOOT_PY" ]; then
    echo "[TeleNova] FATAL: no Python >=3.10 found. Install one (e.g. 'brew install python@3.12') or set PYTHON=/path/to/python." >&2
    exit 1
  fi
  echo "[TeleNova] First run — creating venv with $BOOT_PY and installing dependencies..."
  "$BOOT_PY" -m venv "$VENV"
  "$PY" -m pip install --upgrade pip --quiet
  "$PY" -m pip install -r requirements.txt
  "$PY" -m pip install --find-links sdk-dist/wheelhouse rai-sdk-langgraph
fi

[ -f rai.env ] || { echo "[TeleNova] No rai.env — copying rai.env.example (Trust API URLs)."; cp rai.env.example rai.env; }
[ -f .env ]    || { echo "[TeleNova] No .env — copying .env.example. Set your LLM key and RAI_APP_KEY."; cp .env.example .env; }

echo "[TeleNova] Starting on http://127.0.0.1:${APP_PORT}  (app_id=telenova)"
exec "$PY" server.py
