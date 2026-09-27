import os

import pytest
import zstandard

from backend.app.artifacts import create_artifact, decrypt_to_file


class BytesSource:
    def write_to(self, output):
        return output.write(b"backupforge-streaming-roundtrip")


def test_zstd_artifact_encrypts_and_decrypts_streamingly(tmp_path):
    artifact, original, _, checksum = create_artifact(BytesSource(), "zstd", os.urandom(32), tmp_path)
    assert original == len(b"backupforge-streaming-roundtrip")
    assert len(checksum) == 64


def test_tampered_artifact_is_not_accepted(tmp_path):
    key = os.urandom(32)
    artifact, *_ = create_artifact(BytesSource(), "zstd", key, tmp_path)
    payload = bytearray(artifact.read_bytes())
    payload[-1] ^= 1
    artifact.write_bytes(payload)
    with artifact.open("rb") as stream:
        with pytest.raises(Exception):
            decrypt_to_file(stream, key, tmp_path / "decrypted")
