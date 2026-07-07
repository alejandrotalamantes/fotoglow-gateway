#!/data/data/com.termux/files/usr/bin/bash
# Arranque del gateway en Termux (Android)
set -e
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  echo "Crea el venv primero: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if [[ ! -f config.json ]]; then
  echo "Falta config.json — copia config.example.json y edítalo."
  exit 1
fi

# Evita que Android duerma el proceso durante el evento
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
  echo "Wake lock activado"
fi

source .venv/bin/activate

echo "--- IP en interfaces (usa la del hotspot para la Sony) ---"
ip -4 addr show 2>/dev/null | grep -E 'inet ' || ifconfig 2>/dev/null | grep inet || true
echo "-----------------------------------------------------------"
echo "Panel evento: http://127.0.0.1:8080"
echo ""

exec python -m gateway
