from __future__ import annotations

import fnmatch
import os
import subprocess
import tarfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from .config import Settings


class BackupSourceAdapter(ABC):
    @abstractmethod
    def write_to(self, output: BinaryIO) -> int:
        """Write source bytes incrementally and return uncompressed byte count."""


class FilesystemSource(BackupSourceAdapter):
    def __init__(self, config: dict, settings: Settings):
        self.root = Path(config["path"]).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("filesystem source must be a directory")
        if not any(self.root == allowed or allowed in self.root.parents for allowed in settings.source_roots):
            raise ValueError("source is outside BACKUPFORGE_ALLOWED_SOURCE_ROOTS")
        self.includes = tuple(config.get("include", ["**"]))
        self.excludes = tuple(config.get("exclude", []))
        self.symlinks = config.get("symlinks", "preserve")
        if self.symlinks not in {"preserve", "skip", "follow"}:
            raise ValueError("symlinks must be preserve, skip, or follow")

    def _selected(self, relative: Path) -> bool:
        name = relative.as_posix()
        return any(fnmatch.fnmatch(name, rule) for rule in self.includes) and not any(
            fnmatch.fnmatch(name, rule) for rule in self.excludes
        )

    def write_to(self, output: BinaryIO) -> int:
        total = 0
        with tarfile.open(fileobj=output, mode="w|") as archive:
            for directory, names, files in os.walk(self.root, followlinks=self.symlinks == "follow"):
                directory_path = Path(directory)
                # Never traverse excluded child directories.
                names[:] = [n for n in names if self._selected((directory_path / n).relative_to(self.root))]
                for name in [*names, *files]:
                    item = directory_path / name
                    relative = item.relative_to(self.root)
                    if not self._selected(relative):
                        continue
                    if item.is_symlink() and self.symlinks == "skip":
                        continue
                    try:
                        archive.add(item, arcname=relative.as_posix(), recursive=False)
                        if item.is_file() and not item.is_symlink():
                            total += item.stat().st_size
                    except FileNotFoundError:
                        # A concurrent deletion should fail safe rather than archive a partial entry.
                        raise RuntimeError(f"source changed while reading: {relative}")
        return total


class _CommandSource(BackupSourceAdapter):
    command: list[str]

    def write_to(self, output: BinaryIO) -> int:
        # No shell means source values cannot become shell syntax. Passwords are env-only.
        environment = {"PATH": os.environ.get("PATH", ""), **self.environment}
        process = subprocess.Popen(self.command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment)
        assert process.stdout is not None
        size = 0
        try:
            for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
                output.write(chunk)
                size += len(chunk)
            process.communicate(timeout=self.timeout)
        except Exception:
            process.kill()
            process.wait()
            raise
        if process.returncode:
            # Avoid returning command/environment values; database tools can echo DSNs.
            raise RuntimeError(f"trusted database dump tool failed with exit code {process.returncode}")
        return size


class PostgreSQLSource(_CommandSource):
    def __init__(self, config: dict):
        database = config["database"]
        if not database.replace("_", "").replace("-", "").isalnum():
            raise ValueError("invalid PostgreSQL database name")
        self.command = ["pg_dump", "--format=custom", "--no-password", "--dbname", database]
        if config.get("host"):
            self.command += ["--host", config["host"]]
        if config.get("port"):
            self.command += ["--port", str(int(config["port"]))]
        if config.get("user"):
            self.command += ["--username", config["user"]]
        self.environment = {"PGPASSWORD": config["password"]} if config.get("password") else {}
        self.timeout = int(config.get("timeout_seconds", 3600))


class MySQLSource(_CommandSource):
    def __init__(self, config: dict):
        database = config["database"]
        if not database.replace("_", "").replace("-", "").isalnum():
            raise ValueError("invalid MySQL database name")
        self.command = ["mariadb-dump", "--single-transaction", "--routines", "--events", "--databases", database]
        if config.get("host"):
            self.command += ["--host", config["host"]]
        if config.get("port"):
            self.command += ["--port", str(int(config["port"]))]
        if config.get("user"):
            self.command += ["--user", config["user"]]
        self.environment = {"MYSQL_PWD": config["password"]} if config.get("password") else {}
        self.timeout = int(config.get("timeout_seconds", 3600))


class DockerVolumeSource(BackupSourceAdapter):
    def __init__(self, config: dict):
        self.volume = config["volume"]
        if not self.volume.replace("_", "").replace("-", "").isalnum():
            raise ValueError("invalid Docker volume name")

    def write_to(self, output: BinaryIO) -> int:
        # Explicitly require a reviewed, dedicated helper image. The API container never mounts Docker.
        command = ["docker", "run", "--rm", "--read-only", "-v", f"{self.volume}:/source:ro", "backupforge-volume-helper:latest"]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert process.stdout is not None
        size = 0
        for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
            output.write(chunk)
            size += len(chunk)
        process.communicate()
        if process.returncode:
            raise RuntimeError("dedicated Docker volume helper failed")
        return size


def source_for(kind: str, config: dict, app_settings: Settings) -> BackupSourceAdapter:
    if kind == "filesystem":
        return FilesystemSource(config, app_settings)
    if kind == "postgresql":
        return PostgreSQLSource(config)
    if kind in {"mysql", "mariadb"}:
        return MySQLSource(config)
    if kind == "docker_volume":
        return DockerVolumeSource(config)
    raise ValueError(f"unsupported source type: {kind}")
