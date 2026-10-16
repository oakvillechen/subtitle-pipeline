#!/bin/bash
cd "$(dirname "$0")"
pgrep -x ollama >/dev/null || (nohup /opt/homebrew/bin/ollama serve >/tmp/ollama_serve.log 2>&1 &)
exec ./.venv/bin/python gui.py
