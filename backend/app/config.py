from __future__ import annotations

import base64
import re
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BACKUPFORGE_", extra="ignore")

    database_url: str = "sqlite:///./backupforge.db"
    redis_url: str = "redis://localhost:6379/0"
    data_dir: Path = Path("./data")
    # Deliberately has no default: production must explicitly provide key material.
    master_key: str | None = None
    auth_secret: str | None = None
    bootstrap_token: str | None = None
    allowed_source_roots: str = "/data"
    allowed_restore_roots: str = "/restore"
    max_upload_bytes: int | None = None
    enable_docker_verification: bool = False
    docker_volume_helper_image: str | None = None
    postgres_verification_image: str | None = None
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

    @property
    def source_roots(self) -> tuple[Path, ...]:
        return tuple(Path(value).resolve() for value in self.allowed_source_roots.split(",") if value)

    @property
    def restore_roots(self) -> tuple[Path, ...]:
        return tuple(Path(value).resolve() for value in self.allowed_restore_roots.split(",") if value)

    def encryption_key(self) -> bytes:
        if not self.master_key:
            raise RuntimeError("BACKUPFORGE_MASTER_KEY is required; refusing insecure startup")
        try:
            key = base64.urlsafe_b64decode(self.master_key.encode("ascii"))
        except Exception as exc:
            raise RuntimeError("BACKUPFORGE_MASTER_KEY must be base64-encoded") from exc
        if len(key) != 32:
            raise RuntimeError("BACKUPFORGE_MASTER_KEY must decode to exactly 32 bytes")
        return key

    def validate_security(self) -> None:
        self.encryption_key()
        if not self.auth_secret or len(self.auth_secret) < 32:
            raise RuntimeError("BACKUPFORGE_AUTH_SECRET must be at least 32 characters")
        if not self.bootstrap_token or len(self.bootstrap_token) < 32:
            raise RuntimeError("BACKUPFORGE_BOOTSTRAP_TOKEN must be at least 32 characters")
        if self.enable_docker_verification:
            self.require_pinned_image(self.postgres_verification_image, "BACKUPFORGE_POSTGRES_VERIFICATION_IMAGE")

    @staticmethod
    def require_pinned_image(image: str | None, setting_name: str) -> str:
        if not image or not re.fullmatch(r"[A-Za-z0-9./_-]+@sha256:[a-f0-9]{64}", image):
            raise RuntimeError(f"{setting_name} must be a sha256 digest-pinned image reference")
        return image


@lru_cache
def settings() -> Settings:
    return Settings()
