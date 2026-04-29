from fastapi import APIRouter

from app.services.syncthing_service import get_syncthing_status

router = APIRouter(prefix="/syncthing", tags=["syncthing"])


@router.get("/status")
async def syncthing_status():
    return await get_syncthing_status()
