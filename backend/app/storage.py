from __future__ import annotations

import hashlib
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO


def safe_storage_key(key: str) -> str:
    if not key or key.startswith(("/", "\\")) or ".." in Path(key).parts or not re.fullmatch(r"[A-Za-z0-9._/=-]+", key):
        raise ValueError("unsafe storage key")
    return key


class StorageBackend(ABC):
    @abstractmethod
    def upload(self, key: str, data: BinaryIO) -> None: ...

    @abstractmethod
    def open(self, key: str) -> BinaryIO: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    def checksum(self, key: str) -> str:
        digest = hashlib.sha256()
        with self.open(key) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


class LocalStorage(StorageBackend):
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / safe_storage_key(key)).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError("storage path escapes destination")
        return path

    def upload(self, key: str, data: BinaryIO) -> None:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.partial")
        try:
            with temporary.open("wb") as output:
                shutil.copyfileobj(data, output, 1024 * 1024)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def delete(self, key: str) -> None:
        self._path(key).unlink()


class S3Storage(StorageBackend):
    def __init__(self, config: dict, credentials: dict):
        import boto3
        self.bucket = config["bucket"]
        self.prefix = config.get("prefix", "").strip("/")
        self.client = boto3.client("s3", endpoint_url=config.get("endpoint"), region_name=config.get("region"), aws_access_key_id=credentials.get("access_key"), aws_secret_access_key=credentials.get("secret_key"))

    def _key(self, key: str) -> str:
        safe = safe_storage_key(key)
        return f"{self.prefix}/{safe}" if self.prefix else safe

    def upload(self, key: str, data: BinaryIO) -> None:
        self.client.upload_fileobj(data, self.bucket, self._key(key))

    def open(self, key: str) -> BinaryIO:
        # Caller gets a closeable streaming response body.
        return self.client.get_object(Bucket=self.bucket, Key=self._key(key))["Body"]

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))


def backend_for(kind: str, config: dict, credentials: dict) -> StorageBackend:
    if kind == "local":
        return LocalStorage(config["path"])
    if kind == "s3":
        return S3Storage(config, credentials)
    raise ValueError(f"unsupported destination kind: {kind}")

