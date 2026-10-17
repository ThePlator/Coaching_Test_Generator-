#!/usr/bin/env bash
# One-time setup for Linux and macOS.
#   bash scripts/setup.sh            # install everything, pull gemma3:4b
#   CTG_MODEL=gemma3:1b bash scripts/setup.sh   # smaller model (text only, no photos)
# Safe to run again: every step checks before it installs.

set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${CTG_MODEL:-gemma3:4b}"
say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    ✓ %s\n' "$*"; }
warn() { printf '    ! %s\n' "$*"; }

ask() {  # ask "question" → returns 0 for yes
  read -r -p "    $1 [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

# 1. Python ---------------------------------------------------------------
say "Python"
PY=""
for cand in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$cand" >/dev/null 2>&1 &&
     "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
if [[ -z "$PY" ]]; then
  echo "    Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ and run this again."
  exit 1
fi
ok "$($PY --version)"

# 2. System libraries for PDF export (WeasyPrint needs Pango) --------------
say "PDF libraries (Pango)"
case "$(uname -s)" in
  Linux)
    if ldconfig -p 2>/dev/null | grep -q libpango-1.0; then
      ok "Pango found"
    elif command -v apt-get >/dev/null; then
      warn "Pango not found — installing (needs sudo)"
      sudo apt-get update -qq && sudo apt-get install -y -qq libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b
    elif command -v dnf >/dev/null; then
      sudo dnf install -y pango
    else
      warn "Install Pango with your package manager, or PDFs will fall back to HTML."
    fi
    ;;
  Darwin)
    if command -v brew >/dev/null; then
      brew list pango >/dev/null 2>&1 && ok "Pango found" || brew install pango
    else
      warn "Install Homebrew (https://brew.sh) then run: brew install pango"
    fi
    ;;
esac

# 3. Virtual environment + packages ----------------------------------------
say "Python packages"
[[ -d .venv ]] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt
ok "installed into .venv"

# 4. Ollama + model ---------------------------------------------------------
say "Ollama and $MODEL"
if ! command -v ollama >/dev/null; then
  warn "Ollama is not installed."
  if ask "Install Ollama now from https://ollama.com (runs their official install script)?"; then
    curl -fsSL https://ollama.com/install.sh | sh
  else
    echo "    Install it from https://ollama.com/download, then run this script again."
    exit 1
  fi
fi
ok "$(ollama --version 2>/dev/null | head -1)"

if ! curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
  warn "Ollama is not running — starting it in the background"
  (ollama serve >/dev/null 2>&1 &) ; sleep 3
fi
if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
  ok "$MODEL already downloaded"
else
  echo "    Downloading $MODEL (one time, about 3 GB)…"
  ollama pull "$MODEL"
fi

# 5. Institute profile -------------------------------------------------------
say "Institute profile"
if [[ -f config/institute.toml ]]; then
  ok "config/institute.toml exists"
else
  cp config/institute.example.toml config/institute.toml
  ok "created config/institute.toml — set your institute name in the app sidebar"
fi

# 6. Check --------------------------------------------------------------------
say "Checking"
.venv/bin/python scripts/preflight.py || true

cat <<EOF

Done. To start the app:
    .venv/bin/streamlit run app.py
Then open http://localhost:8501
EOF
