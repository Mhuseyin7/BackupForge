import io
import os
import tarfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.app.security import decrypt_json, encrypt_json
from backend.app.storage import LocalStorage, safe_storage_key
from backend.app.retention import artifacts_to_delete
from backend.app.config import Settings
from backend.app.sources import FilesystemSource
from backend.app.notifications import _validate_public_https_url


def test_credentials_are_authenticated_and_not_plaintext():
    key = os.urandom(32)
    encrypted = encrypt_json({"password": "do-not-log-me"}, key)
    assert "do-not-log-me" not in encrypted
    assert decrypt_json(encrypted, key) == {"password": "do-not-log-me"}
    with pytest.raises(Exception):
        decrypt_json(encrypted[:-2] + "xx", key)


def test_local_storage_rejects_traversal_and_upload_is_atomic(tmp_path):
    store = LocalStorage(str(tmp_path))
    store.upload("jobs/a.bforge", io.BytesIO(b"encrypted"))
    assert store.checksum("jobs/a.bforge")
    with pytest.raises(ValueError):
        store.upload("../escape", io.BytesIO(b"no"))
    with pytest.raises(ValueError):
        safe_storage_key("/absolute")


@dataclass
class Candidate:
    id: object
    completed_at: datetime


def test_retention_never_selects_newest_valid_artifact():
    now = datetime.now(timezone.utc)
    newest, middle, oldest = (Candidate(uuid4(), now - timedelta(days=days)) for days in (0, 1, 30))
    result = artifacts_to_delete([oldest, middle, newest], {"keep_latest": 1}, now)
    assert newest not in result
    assert {item.id for item in result} == {middle.id, oldest.id}


def test_filesystem_include_pattern_descends_into_selected_directory(tmp_path):
    selected = tmp_path / "database"
    selected.mkdir()
    (selected / "dump.sql").write_text("fixture", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("ignore", encoding="utf-8")
    source = FilesystemSource(
        {"path": str(tmp_path), "include": ["database/**"]},
        Settings(allowed_source_roots=str(tmp_path)),
    )
    output = io.BytesIO()
    source.write_to(output)
    output.seek(0)
    with tarfile.open(fileobj=output) as archive:
        assert "database/dump.sql" in archive.getnames()
        assert "ignore.txt" not in archive.getnames()


def test_notification_target_rejects_private_network_address():
    with pytest.raises(ValueError):
        _validate_public_https_url("https://127.0.0.1/internal-hook")

