"""Resolve saved media defaults without changing existing sources or syncs."""
from app.models import AppSetting
from app.tasks.scheduler import DEFAULTS


def apply_download_defaults(payload, db):
    from app.services.profiles import profile
    selected = profile(db, payload.profile_id) if getattr(payload, "profile_id", None) is not None else None
    for field in ("audio_format", "audio_quality"):
        if field not in payload.model_fields_set:
            key = "default_" + field
            row = db.get(AppSetting, key)
            setattr(payload, field, selected[field] if selected else row.value if row else DEFAULTS[key])
    return payload
