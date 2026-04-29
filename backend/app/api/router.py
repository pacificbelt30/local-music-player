from fastapi import APIRouter

from app.api import urls, queue, tracks, stream, syncthing

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(urls.router)
api_router.include_router(queue.router)
api_router.include_router(tracks.router)
api_router.include_router(stream.router)
api_router.include_router(syncthing.router)
