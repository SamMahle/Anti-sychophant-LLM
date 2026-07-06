#!/usr/bin/env bash
# One-click start: sets up a private Python environment on first run,
# then opens the accountability agent in your browser.
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required but was not found."
  echo "Install it from https://www.python.org/downloads/ and run this again."
  read -r -p "Press Enter to close..." _ || true
  exit 1
fi

if [ ! -d .venv ]; then
  echo "First run: setting things up (this takes a minute)..."
  python3 -m venv .venv
fi
. .venv/bin/activate
pip install -q -r requirements.txt

python main.py web
