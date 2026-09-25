from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

import zstandard
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .security import ArtifactEncryptor, TAG_BYTES, parse_header
from .sources import BackupSourceAdapter


def _ensure_space(directory: Path, required: int = 64 * 1024 * 1024) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(directory).free < required:
        raise RuntimeError("insufficient temporary disk space")


def create_artifact(source: BackupSourceAdapter, compression: str, key: bytes, temp_dir: Path) -> tuple[Path, int, int, str]:
    """Creates a streamed, encrypted artifact; no source archive is accumulated in memory."""
    _ensure_space(temp_dir)
    fd, generated = tempfile.mkstemp(prefix="backupforge-", suffix=".bforge", dir=temp_dir)
    os.close(fd)
    artifact = Path(generated)
    try:
        with artifact.open("wb") as raw:
            encryptor = ArtifactEncryptor(raw, key, {"version": 1, "compression": compression, "cipher": "AES-256-GCM"})
            if compression == "zstd":
                compressed = zstandard.ZstdCompressor(level=3).stream_writer(encryptor, closefd=False)
            elif compression == "gzip":
                compressed = gzip.GzipFile(fileobj=encryptor, mode="wb", mtime=0)
            else:
                raise ValueError("compression must be zstd or gzip")
            try:
                original_size = source.write_to(compressed)
            finally:
                compressed.close()
            encryptor.finalize()
        digest = hashlib.sha256()
        with artifact.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return artifact, original_size, artifact.stat().st_size, digest.hexdigest()
    except Exception:
        artifact.unlink(missing_ok=True)
        raise


def decrypt_to_file(artifact: BinaryIO, key: bytes, output: Path) -> dict:
    """Authenticates before returning. Unauthenticated temporary bytes are removed on every error."""
    nonce, metadata_bytes, header_length = parse_header(artifact)
    import json
    metadata = json.loads(metadata_bytes)
    artifact.seek(0, os.SEEK_END)
    size = artifact.tell()
    ciphertext_length = size - header_length - TAG_BYTES
    if ciphertext_length < 0:
        raise ValueError("truncated artifact")
    artifact.seek(header_length)
    artifact.seek(header_length + ciphertext_length)
    tag = artifact.read(TAG_BYTES)
    artifact.seek(header_length)
    decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
    decryptor.authenticate_additional_data(metadata_bytes)
    try:
        with output.open("wb") as destination:
            remaining = ciphertext_length
            while remaining:
                chunk = artifact.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("truncated ciphertext")
                destination.write(decryptor.update(chunk))
                remaining -= len(chunk)
            destination.write(decryptor.finalize())
        return metadata
    except Exception:
        output.unlink(missing_ok=True)
        raise


def restore_filesystem(artifact: BinaryIO, key: bytes, target: Path, temp_dir: Path) -> None:
    """Safe restore: must be explicitly invoked by an authorized destructive restore flow."""
    _ensure_space(temp_dir)
    fd, temp_name = tempfile.mkstemp(prefix="restore-", dir=temp_dir)
    os.close(fd)
    compressed = Path(temp_name)
    try:
        metadata = decrypt_to_file(artifact, key, compressed)
        target = target.resolve()
        target.mkdir(parents=True, exist_ok=True)
        if metadata["compression"] == "zstd":
            reader = zstandard.ZstdDecompressor().stream_reader(compressed.open("rb"))
        elif metadata["compression"] == "gzip":
            reader = gzip.open(compressed, "rb")
        else:
            raise ValueError("unsupported compression")
        with reader, __import__("tarfile").open(fileobj=reader, mode="r|") as archive:
            for member in archive:
                destination = (target / member.name).resolve()
                if destination != target and target not in destination.parents:
                    raise ValueError("archive contains traversal path")
                if member.issym() or member.islnk():
                    raise ValueError("symlink restore requires a separate reviewed workflow")
                archive.extract(member, target, filter="data")
    finally:
        compressed.unlink(missing_ok=True)

