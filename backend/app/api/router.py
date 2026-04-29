from fastapi import APIRouter

from app.api import urls, queue, tracks, stream, syncthing, youtube_playlists, settings

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(urls.router)
api_router.include_router(queue.router)
api_router.include_router(tracks.router)
api_router.include_router(stream.router)
api_router.include_router(syncthing.router)
api_router.include_router(youtube_playlists.router)
api_router.include_router(settings.router)
