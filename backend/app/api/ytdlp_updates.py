from fastapi import APIRouter, HTTPException

from app.services import ytdlp_updates as updates

router = APIRouter(prefix="/ytdlp", tags=["yt-dlp updates"])


@router.get("")
def get_status():
    return updates.status()


@router.patch("/config")
def configure(payload: updates.UpdateConfig):
    try:
        return updates.configure(payload)
    except updates.UpdateBusy as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/check", status_code=202)
def check_now():
    if updates.status()["busy"]:
        raise HTTPException(409, "更新処理が実行中です")
    from app.tasks.ytdlp_update import check_ytdlp_update
    try:
        job = check_ytdlp_update.apply_async(kwargs={"force": True}, expires=300)
    except Exception as exc:
        raise HTTPException(503, "更新ワーカーに接続できません") from exc
    return {"task_id": job.id, "status": "queued"}


@router.post("/rollback")
def rollback():
    try:
        return updates.rollback()
    except updates.UpdateBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

