#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "Première installation, ça peut prendre quelques minutes…"
  python3 -m venv .venv || { echo "Python 3 est introuvable."; exit 1; }
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
else
  source .venv/bin/activate
fi
python app.py
