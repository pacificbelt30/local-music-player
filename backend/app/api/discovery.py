"""Optional discovery providers; credentials never leave the server."""

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import discovery
from app.services.discovery_config import (
    ConfigUpdate,
    DiscoveryConfigurationError,
    Provider,
    public_config,
    update_config,
)

router = APIRouter(prefix="/discovery", tags=["discovery"])


class TrackSeed(BaseModel):
    artist: str = Field(min_length=1, max_length=160)
    track: str = Field(min_length=1, max_length=300)


def no_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"


@router.get("/config", dependencies=[Depends(no_cache)])
def configuration(db: Session = Depends(get_db)):
    return {provider: public_config(db, provider) for provider in ("youtube", "lastfm")}


@router.patch("/config/{provider}", dependencies=[Depends(no_cache)])
def configure(
    provider: Provider, payload: Any = Body(...), db: Session = Depends(get_db)
):
    try:
        parsed = ConfigUpdate.model_validate(payload)
    except ValidationError as exc:
        # Pydantic's normal validation response can include raw secret inputs.
        raise HTTPException(
            422, detail=[{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        ) from None
    try:
        return update_config(db, provider, parsed)
    except DiscoveryConfigurationError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/config/{provider}/test", dependencies=[Depends(no_cache)])
def test_connection(provider: Provider, db: Session = Depends(get_db)):
    return discovery.fetch(db, provider, check=True)


@router.get("/popular/{provider}", dependencies=[Depends(no_cache)])
def popular(provider: Provider, refresh: bool = False, db: Session = Depends(get_db)):
    return discovery.fetch(db, provider, force=refresh)


@router.get("/similar/lastfm", dependencies=[Depends(no_cache)])
def similar(
    artist: str = Query(min_length=1, max_length=160),
    track: str = Query(min_length=1, max_length=300),
    db: Session = Depends(get_db),
):
    if not artist.strip() or not track.strip():
        raise HTTPException(422, "曲名とアーティスト名を入力してください。")
    return discovery.fetch(
        db, "lastfm", kind="similar", artist=artist.strip(), track=track.strip()
    )


@router.post("/source/lastfm", dependencies=[Depends(no_cache)])
def source(payload: TrackSeed, db: Session = Depends(get_db)):
    if not payload.artist.strip() or not payload.track.strip():
        raise HTTPException(422, "曲名とアーティスト名を入力してください。")
    return discovery.fetch(
        db,
        "lastfm",
        kind="source",
        artist=payload.artist.strip(),
        track=payload.track.strip(),
    )
