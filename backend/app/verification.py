"""Optional isolated PostgreSQL restore verification. Requires a dedicated worker with Docker access."""
from __future__ import annotations

import gzip
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import zstandard

from .artifacts import decrypt_to_file


def _run(command: list[str], timeout: int = 60) -> None:
    completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    if completed.returncode:
        raise RuntimeError(f"restore-verification command failed ({command[0]})")


def verify_postgresql_artifact(artifact_path: Path, key: bytes, config: dict, temp_dir: Path) -> None:
    """Restore custom pg_dump into a disposable container, run allowlisted read-only checks, remove it."""
    if not config.get("verify_restore"):
        return
    if not config.get("verification_queries"):
        raise ValueError("verify_restore requires at least one validation query")
    temp_dir.mkdir(parents=True, exist_ok=True)
    name = f"backupforge-verify-{uuid4().hex[:12]}"
    fd, compressed_name = tempfile.mkstemp(prefix="verify-", dir=temp_dir)
    os.close(fd)
    fd, dump_name = tempfile.mkstemp(prefix="verify-", suffix=".dump", dir=temp_dir)
    os.close(fd)
    fd, env_name = tempfile.mkstemp(prefix="verify-", suffix=".env", dir=temp_dir)
    os.close(fd)
    compressed, dump, env_file = Path(compressed_name), Path(dump_name), Path(env_name)
    password = secrets.token_urlsafe(32)
    try:
        with artifact_path.open("rb") as stream:
            metadata = decrypt_to_file(stream, key, compressed)
        if metadata["compression"] == "zstd":
            with compressed.open("rb") as source, dump.open("wb") as target:
                zstandard.ZstdDecompressor().copy_stream(source, target)
        elif metadata["compression"] == "gzip":
            with gzip.open(compressed, "rb") as source, dump.open("wb") as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
        else:
            raise ValueError("unsupported artifact compression")
        env_file.write_text(f"POSTGRES_PASSWORD={password}\n", encoding="utf-8")
        image = config.get("verification_image", "postgres:16-alpine")
        _run(["docker", "run", "-d", "--rm", "--name", name, "--env-file", str(env_file), image], timeout=30)
        ready = False
        for _ in range(30):
            check = subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if check.returncode == 0:
                ready = True
                break
            time.sleep(1)
        if not ready:
            raise RuntimeError("temporary PostgreSQL verification instance did not become ready")
        _run(["docker", "cp", str(dump), f"{name}:/tmp/backup.dump"])
        _run(["docker", "exec", name, "pg_restore", "-U", "postgres", "-d", "postgres", "--clean", "--if-exists", "/tmp/backup.dump"], timeout=int(config.get("verification_timeout_seconds", 900)))
        for query in config["verification_queries"]:
            if not isinstance(query, str) or not query.strip().lower().startswith("select"):
                raise ValueError("verification queries must be SELECT statements")
            _run(["docker", "exec", name, "psql", "-U", "postgres", "-d", "postgres", "--no-psqlrc", "--set", "ON_ERROR_STOP=1", "--command", query])
    finally:
        subprocess.run(["docker", "rm", "-f", name], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        for path in (compressed, dump, env_file):
            path.unlink(missing_ok=True)
