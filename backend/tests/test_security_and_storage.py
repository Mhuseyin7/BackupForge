import io
import os

import pytest

from backend.app.security import decrypt_json, encrypt_json
from backend.app.storage import LocalStorage, safe_storage_key


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

