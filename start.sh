#!/usr/bin/env bash
# Local development startup (without Docker)
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Check dependencies
command -v ffmpeg >/dev/null 2>&1 || { echo "ERROR: ffmpeg not found. Install it first."; exit 1; }
command -v redis-cli >/dev/null 2>&1 || { echo "ERROR: redis-cli not found. Install Redis first."; exit 1; }

# Check Redis is running
redis-cli ping >/dev/null 2>&1 || { echo "ERROR: Redis is not running. Start it with: redis-server"; exit 1; }

# Create virtualenv if needed
if [ ! -d "$ROOT/.venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$ROOT/.venv"
fi

source "$ROOT/.venv/bin/activate"
pip install -q -r "$ROOT/backend/requirements.txt"

mkdir -p "$ROOT/downloads" "$ROOT/data"

# Copy .env if missing
if [ ! -f "$ROOT/.env" ] && [ -f "$ROOT/.env.example" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "Created .env from .env.example"
fi

cd "$ROOT/backend"

echo ""
echo "Starting Celery worker..."
celery -A app.tasks.celery_app.celery_app worker --loglevel=info -Q downloads,scheduler &
WORKER_PID=$!

echo "Starting Celery beat..."
celery -A app.tasks.celery_app.celery_app beat --loglevel=info &
BEAT_PID=$!

echo "Starting FastAPI server on http://0.0.0.0:8000 ..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
SERVER_PID=$!

trap "kill $WORKER_PID $BEAT_PID $SERVER_PID 2>/dev/null; exit" INT TERM

echo ""
echo "✓ All services started."
echo "  UI:   http://localhost:8000"
echo "  Docs: http://localhost:8000/api/docs"
echo ""
echo "Press Ctrl+C to stop all services."

wait
