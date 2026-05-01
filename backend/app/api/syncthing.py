import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import syncthing_service
from app.services.syncthing_service import _ConfigError

router = APIRouter(prefix="/syncthing", tags=["syncthing"])


class SyncthingConfig(BaseModel):
    url: str
    api_key_set: bool


class SyncthingConfigUpdate(BaseModel):
    url: str | None = Field(default=None)
    api_key: str | None = Field(default=None)


class SyncthingConfigTest(BaseModel):
    url: str
    api_key: str


@router.get("/status")
async def syncthing_status(db: Session = Depends(get_db)):
    return await syncthing_service.get_syncthing_status(db)


@router.get("/config", response_model=SyncthingConfig)
def get_config(db: Session = Depends(get_db)):
    url, api_key = syncthing_service.get_effective_config(db)
    return SyncthingConfig(url=url, api_key_set=bool(api_key))


@router.patch("/config", response_model=SyncthingConfig)
def update_config(payload: SyncthingConfigUpdate, db: Session = Depends(get_db)):
    syncthing_service.update_config(db, url=payload.url, api_key=payload.api_key)
    url, api_key = syncthing_service.get_effective_config(db)
    return SyncthingConfig(url=url, api_key_set=bool(api_key))


@router.post("/config/test")
async def test_config(payload: SyncthingConfigTest):
    return await syncthing_service.test_connection(payload.url, payload.api_key)


@router.get("/folders")
async def list_folders(db: Session = Depends(get_db)):
    try:
        return await syncthing_service.list_folders(db)
    except _ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (httpx.ConnectError, httpx.TimeoutException):
        raise HTTPException(status_code=502, detail="Syncthing not reachable")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Syncthing HTTP {e.response.status_code}")


@router.get("/devices")
async def list_devices(db: Session = Depends(get_db)):
    try:
        return await syncthing_service.list_devices(db)
    except _ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (httpx.ConnectError, httpx.TimeoutException):
        raise HTTPException(status_code=502, detail="Syncthing not reachable")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Syncthing HTTP {e.response.status_code}")


@router.post("/folders/{folder_id}/rescan")
async def rescan_folder(folder_id: str, db: Session = Depends(get_db)):
    try:
        return await syncthing_service.rescan_folder(db, folder_id)
    except _ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (httpx.ConnectError, httpx.TimeoutException):
        raise HTTPException(status_code=502, detail="Syncthing not reachable")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Syncthing HTTP {e.response.status_code}")
