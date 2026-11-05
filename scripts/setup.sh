#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for program in docker ollama python3; do command -v "$program" >/dev/null || { echo "Instale $program. Consulte o README."; exit 1; }; done
python3 - <<'PY'
from pathlib import Path
import secrets, shutil
if shutil.disk_usage('.').free < 15 * 2**30:
    raise SystemExit('Reserve pelo menos 15 GiB livres.')
path = Path('.env')
if not path.exists():
    path.write_text(Path('.env.example').read_text().replace('change-this-local-password', secrets.token_urlsafe(24)))
    path.chmod(0o600)
PY
docker info >/dev/null
ollama pull qwen3:4b
docker compose up -d --build
echo 'Aplicação: http://localhost:8080'
echo 'Crie seu usuário: docker compose exec api jurisassist create-user'
echo 'Revise e aprove as fontes na área Administração.'
