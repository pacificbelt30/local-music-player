from contextlib import asynccontextmanager
from pathlib import Path

import redis as redis_lib
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config import settings
from app.database import init_db
from app.schemas import HealthResponse

FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.downloads_path.mkdir(parents=True, exist_ok=True)
    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.playlists_path.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(
    title="SyncTune Hub",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/api/v1/health", response_model=HealthResponse, tags=["admin"])
def health():
    redis_ok = False
    try:
        r = redis_lib.from_url(settings.redis_url)
        r.ping()
        redis_ok = True
    except Exception:
        pass

    db_ok = False
    try:
        from app.database import SessionLocal
        db = SessionLocal()
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db.close()
        db_ok = True
    except Exception:
        pass

    worker_active = False
    try:
        from app.tasks.celery_app import celery_app
        insp = celery_app.control.inspect(timeout=1.0)
        stats = insp.stats()
        worker_active = bool(stats)
    except Exception:
        pass

    return HealthResponse(
        status="ok" if redis_ok and db_ok else "degraded",
        redis_connected=redis_ok,
        db_ok=db_ok,
        worker_active=worker_active,
    )


@app.post("/api/v1/admin/rescan", tags=["admin"])
def rescan_library():
    """Reconcile DB tracks with files on disk."""
    from app.database import SessionLocal
    from app.models import Track

    db = SessionLocal()
    removed = 0
    try:
        tracks = db.query(Track).all()
        for track in tracks:
            if not Path(track.file_path).exists():
                db.delete(track)
                removed += 1
        db.commit()
    finally:
        db.close()
    return {"removed": removed}


# Serve frontend static files (must be last to avoid shadowing API routes)
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
