from __future__ import annotations

import base64
import json
import os
from io import BufferedWriter

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"BFG1"
NONCE_BYTES = 12
TAG_BYTES = 16


class ArtifactEncryptor:
    """Chunked AES-256-GCM writer. The authentication tag is appended at EOF."""

    def __init__(self, raw: BufferedWriter, key: bytes, metadata: dict):
        self.raw = raw
        self.nonce = os.urandom(NONCE_BYTES)
        self.metadata = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
        if len(self.metadata) > 65535:
            raise ValueError("artifact metadata exceeds header limit")
        self.raw.write(MAGIC + bytes([len(self.nonce)]) + len(self.metadata).to_bytes(2, "big"))
        self.raw.write(self.nonce + self.metadata)
        self.encryptor = Cipher(algorithms.AES(key), modes.GCM(self.nonce)).encryptor()
        self.encryptor.authenticate_additional_data(self.metadata)

    def write(self, data: bytes) -> int:
        if data:
            self.raw.write(self.encryptor.update(data))
        return len(data)

    def flush(self, *_args) -> None:
        self.raw.flush()

    def writable(self) -> bool:
        return True

    def finalize(self) -> None:
        self.raw.write(self.encryptor.finalize())
        self.raw.write(self.encryptor.tag)
        self.raw.flush()


def parse_header(stream) -> tuple[bytes, bytes, int]:
    if stream.read(4) != MAGIC:
        raise ValueError("not a BackupForge artifact")
    nonce_len = int.from_bytes(stream.read(1), "big")
    metadata_len = int.from_bytes(stream.read(2), "big")
    if nonce_len != NONCE_BYTES or not 0 < metadata_len <= 65535:
        raise ValueError("invalid artifact header")
    nonce, metadata = stream.read(nonce_len), stream.read(metadata_len)
    if len(nonce) != nonce_len or len(metadata) != metadata_len:
        raise ValueError("truncated artifact header")
    return nonce, metadata, 7 + nonce_len + metadata_len


def encrypt_json(value: dict, key: bytes) -> str:
    """Small credential records use AES-GCM with new random nonce each time."""
    nonce = os.urandom(NONCE_BYTES)
    encrypted = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encrypted.authenticate_additional_data(b"backupforge-credentials-v1")
    blob = encrypted.update(json.dumps(value, separators=(",", ":")).encode()) + encrypted.finalize()
    return base64.urlsafe_b64encode(nonce + encrypted.tag + blob).decode("ascii")


def decrypt_json(value: str, key: bytes) -> dict:
    raw = base64.urlsafe_b64decode(value.encode("ascii"))
    nonce, tag, blob = raw[:NONCE_BYTES], raw[NONCE_BYTES:NONCE_BYTES + TAG_BYTES], raw[NONCE_BYTES + TAG_BYTES:]
    decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
    decryptor.authenticate_additional_data(b"backupforge-credentials-v1")
    return json.loads(decryptor.update(blob) + decryptor.finalize())
