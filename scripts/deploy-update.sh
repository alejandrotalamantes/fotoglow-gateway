#!/bin/bash
# Actualiza el gateway desde git y reinicia el servicio.
# Uso: bash scripts/deploy-update.sh

set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -d .git ]; then
  echo "Error: no hay repositorio git en $ROOT"
  exit 1
fi

echo "==> git pull"
git pull --ff-only

if [ -f requirements.txt ]; then
  if [ -d .venv ]; then
    echo "==> pip install (venv)"
    .venv/bin/pip install -r requirements.txt -q
  else
    echo "==> Creando venv"
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt -q
  fi
fi

if [ ! -f config.json ]; then
  echo "==> config.json no existe, copiando ejemplo"
  cp config.example.json config.json
  echo "    Edita config.json antes de usar en produccion."
fi

if systemctl is-active --quiet cabina-gateway 2>/dev/null; then
  echo "==> Reiniciando cabina-gateway"
  sudo systemctl restart cabina-gateway
  systemctl --no-pager status cabina-gateway | head -n 8
else
  echo "Servicio cabina-gateway no activo (omitido reinicio)"
fi

echo "Listo."
