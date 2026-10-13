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
    default_url: str
    overridden: bool


class SyncthingConfigUpdate(BaseModel):
    url: str | None = Field(default=None)
    api_key: str | None = Field(default=None)


class SyncthingConfigTest(BaseModel):
    url: str
    api_key: str | None = None


def _config_response(db):
    from app.config import settings
    from app.models import AppSetting
    url, api_key = syncthing_service.get_effective_config(db)
    overridden = any((row := db.get(AppSetting, key)) and bool(row.value) for key in
                     (syncthing_service.URL_KEY, syncthing_service.API_KEY_KEY))
    return SyncthingConfig(url=url, api_key_set=bool(api_key), default_url=settings.syncthing_url,
                           overridden=overridden)


@router.get("/status")
async def syncthing_status(db: Session = Depends(get_db)):
    return await syncthing_service.get_syncthing_status(db)


@router.get("/config", response_model=SyncthingConfig)
def get_config(db: Session = Depends(get_db)):
    return _config_response(db)


@router.patch("/config", response_model=SyncthingConfig)
def update_config(payload: SyncthingConfigUpdate, db: Session = Depends(get_db)):
    syncthing_service.update_config(db, url=payload.url, api_key=payload.api_key)
    return _config_response(db)


@router.post("/config/test")
async def test_config(payload: SyncthingConfigTest, db: Session = Depends(get_db)):
    api_key = payload.api_key
    if api_key is None:
        _, api_key = syncthing_service.get_effective_config(db)
    return await syncthing_service.test_connection(payload.url, api_key)


@router.get("/folders")
async def list_folders(db: Session = Depends(get_db)):
    try:
        return await syncthing_service.list_folders(db)
    except _ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Syncthing not reachable")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Syncthing HTTP {e.response.status_code}")
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=502, detail="Invalid response from Syncthing")


@router.get("/devices")
async def list_devices(db: Session = Depends(get_db)):
    try:
        return await syncthing_service.list_devices(db)
    except _ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Syncthing not reachable")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Syncthing HTTP {e.response.status_code}")
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=502, detail="Invalid response from Syncthing")


@router.post("/folders/{folder_id}/rescan")
async def rescan_folder(folder_id: str, db: Session = Depends(get_db)):
    try:
        return await syncthing_service.rescan_folder(db, folder_id)
    except _ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Syncthing not reachable")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Syncthing HTTP {e.response.status_code}")
