from fastapi import APIRouter, Depends

from app.api import urls, queue, tracks, stream, syncthing, youtube_playlists, settings, debug
from app.api.deps import verify_token
from app.api import ytdlp_updates

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_token)])
api_router.include_router(urls.router)
api_router.include_router(queue.router)
api_router.include_router(tracks.router)
api_router.include_router(stream.router)
api_router.include_router(syncthing.router)
api_router.include_router(youtube_playlists.router)
api_router.include_router(settings.router)
api_router.include_router(debug.router)
api_router.include_router(ytdlp_updates.router)
