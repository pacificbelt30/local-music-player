"""Opt-in discovery credentials. Only encrypted keys are stored in SQLite."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Literal
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

from app.config import settings
from app.models import AppSetting

Provider = Literal["youtube", "lastfm"]
REGIONS = {"JP": "Japan", "US": "United States", "GB": "United Kingdom"}


class DiscoveryConfigurationError(Exception):
    pass


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    region: Literal["JP", "US", "GB"] | None = None
    api_key: SecretStr | None = None
    clear_key: bool = False

    @field_validator("api_key")
    @classmethod
    def key_length(cls, value):
        if value is None:
            return value
        raw = value.get_secret_value().strip()
        if len(raw) > 512 or any(ord(c) < 33 or ord(c) > 126 for c in raw):
            raise ValueError("APIキーの形式を確認してください")
        return SecretStr(raw)


def _cipher(create=False):
    directory = settings.data_path
    path = directory / ".discovery-key"
    if create and not path.exists():
        directory.mkdir(parents=True, exist_ok=True)
        # Publish a fully written key with an exclusive link. Other API processes
        # can never read an empty/partially written encryption key.
        handle, name = tempfile.mkstemp(prefix=".discovery-key-", dir=directory)
        try:
            with os.fdopen(handle, "wb") as file:
                os.fchmod(file.fileno(), 0o600)
                file.write(Fernet.generate_key())
                file.flush()
                os.fsync(file.fileno())
            try:
                os.link(name, path)
            except FileExistsError:
                pass
        finally:
            Path(name).unlink(missing_ok=True)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as file:
            return Fernet(file.read(128))
    except (OSError, ValueError):
        raise DiscoveryConfigurationError(
            "暗号鍵を読み込めません。データ領域を確認し、必要ならAPIキーを設定し直してください。"
        ) from None


def read_config(db, provider):
    row = db.get(AppSetting, "discovery:config:" + provider)
    return (
        json.loads(row.value)
        if row
        else {
            "enabled": False,
            "region": "JP",
            "key_ciphertext": "",
            "generation": "initial",
        }
    )


def public_config(db, provider):
    config = read_config(db, provider)
    return {
        "provider": provider,
        "enabled": config["enabled"],
        "region": config["region"],
        "api_key_set": bool(config["key_ciphertext"]),
    }


def api_key(config):
    try:
        return _cipher().decrypt(config["key_ciphertext"].encode()).decode()
    except (InvalidToken, KeyError, UnicodeError):
        raise DiscoveryConfigurationError(
            "保存済みのAPIキーを復号できません。APIキーを設定し直してください。"
        ) from None


def update_config(db, provider, payload):
    config = read_config(db, provider)
    raw = payload.api_key.get_secret_value() if payload.api_key is not None else ""
    if payload.clear_key and raw:
        raise DiscoveryConfigurationError("キーの入力と削除は同時に指定できません。")
    if payload.enabled is not None:
        config["enabled"] = payload.enabled
    if payload.region is not None:
        config["region"] = payload.region
    if raw:
        config["key_ciphertext"] = _cipher(create=True).encrypt(raw.encode()).decode()
    if payload.clear_key:
        config["key_ciphertext"] = ""
        config["enabled"] = False
    if config["enabled"] and not config["key_ciphertext"]:
        raise DiscoveryConfigurationError("APIキーを保存してから有効にしてください。")
    config["generation"] = uuid4().hex
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.merge(AppSetting(key="discovery:config:" + provider, value=json.dumps(config)))
    # Old data is not displayed after disable, key replacement or region changes.
    db.query(AppSetting).filter(
        AppSetting.key.like("discovery:cache:" + provider + ":%")
    ).delete(synchronize_session=False)
    db.commit()
    return public_config(db, provider)
