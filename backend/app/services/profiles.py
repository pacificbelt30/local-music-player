"""Named media preferences; syncs keep snapshots until explicitly reapplied."""

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from typing import Literal

from app.models import MediaProfile
from app.schemas import MediaFormat, AudioQuality


class ProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    audio_format: MediaFormat = "mp3"
    audio_quality: AudioQuality = "192"
    target_folder_id: str | None = Field(default=None, max_length=128)
    target_device_id: str | None = Field(default=None, max_length=128)
    target_scope: Literal["downloads", "playlist"] = "downloads"

    @model_validator(mode="after")
    def destination(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("名前を入力してください")
        if bool(self.target_folder_id) != bool(self.target_device_id):
            raise ValueError("共有フォルダと端末を両方選択してください")
        return self


BUILTINS = {
    -1: ProfileInput(name="スマホ用", audio_format="m4a", audio_quality="192"),
    -2: ProfileInput(name="音質優先", audio_format="flac", audio_quality="best"),
    -3: ProfileInput(name="動画保存", audio_format="mp4", audio_quality="best"),
}


def profile(db, profile_id):
    if profile_id in BUILTINS:
        return {"id": profile_id, **BUILTINS[profile_id].model_dump(), "builtin": True}
    row = db.get(MediaProfile, profile_id)
    if row is None:
        raise HTTPException(404, "プロファイルが見つかりません")
    return {
        "id": row.id,
        **{key: getattr(row, key) for key in ProfileInput.model_fields},
        "builtin": False,
    }


def snapshot(db, profile_id):
    if profile_id is None:
        return {}
    value = profile(db, profile_id)
    return {
        "profile_id": value["id"],
        "profile_name": value["name"],
        **{
            key: value[key]
            for key in ("target_folder_id", "target_device_id", "target_scope")
        },
    }
