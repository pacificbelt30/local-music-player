"""Short-lived server-side previews with durable per-item intake results."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from uuid import uuid4

from fastapi import HTTPException
from app.models import AppSetting


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def save_plan(db, kind, details):
    token = uuid4().hex
    data = {
        "kind": kind,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        **details,
    }
    db.add(AppSetting(key="plan:" + token, value=json.dumps(data, ensure_ascii=False)))
    db.commit()
    return token, data


def get_plan(db, token, kind):
    row = db.get(AppSetting, "plan:" + token)
    if row is None:
        raise HTTPException(404, "確認結果がありません。もう一度確認してください")
    data = json.loads(row.value)
    if data.get("kind") != kind:
        raise HTTPException(422, "確認結果の種類が一致しません")
    committed_intake = kind == "intake" and any(
        value.get("state") == "created" for value in data.get("results", {}).values()
    )
    if (
        datetime.fromisoformat(data["expires_at"]) < datetime.now(timezone.utc)
        and not data.get("complete")
        and not committed_intake
    ):
        raise HTTPException(409, "確認結果の期限が切れました。もう一度確認してください")
    return row, data


def update_plan(db, row, data):
    row.value = json.dumps(data, ensure_ascii=False)
