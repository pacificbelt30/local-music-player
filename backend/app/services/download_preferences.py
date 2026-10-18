"""Resolve saved media defaults without changing existing sources or syncs."""
from app.models import AppSetting
from app.tasks.scheduler import DEFAULTS


def apply_download_defaults(payload, db):
    for field in ("audio_format", "audio_quality"):
        if field not in payload.model_fields_set:
            key = "default_" + field
            row = db.get(AppSetting, key)
            setattr(payload, field, row.value if row else DEFAULTS[key])
    return payload
