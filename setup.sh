#!/usr/bin/env bash
set -e
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium
command -v ollama >/dev/null || { echo "Install Ollama first: https://ollama.com/download"; exit 1; }
ollama pull "$(python -c "import yaml;print(yaml.safe_load(open('config/settings.yaml'))['ollama']['model'])")"

[ -f .env ] || cp .env.example .env
[ -f config/candidate.yaml ] || cp config/candidate.example.yaml config/candidate.yaml
[ -f data/resume.md ] || cp data/resume.example.md data/resume.md
echo "Done. Edit data/resume.md and .env, then: secjobs run"
