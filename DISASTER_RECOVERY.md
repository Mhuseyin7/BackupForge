# Disaster Recovery

## If BackupForge is unavailable

You need three things: an artifact (`.bforge`), its 32-byte base64 master key, and a trusted copy of the BackupForge restore implementation matching the artifact format. The PostgreSQL database is helpful for finding artifacts but is not required to decrypt one.

1. Obtain the artifact from its local/NAS location or S3-compatible bucket.
2. Verify its recorded SHA-256 checksum before attempting recovery.
3. Recover the master key from the separate secret-management / Docker-secret / KMS process.
4. Decrypt with AES-256-GCM and validate the authentication tag. Do not use any output if tag validation fails.
5. Decompress its header-specified zstd/gzip stream and restore only into a newly provisioned target.

The current `BFG1` format is a small header followed by nonce, metadata authenticated as AES-GCM AAD, ciphertext, and the 16-byte authentication tag. Keep a release archive of the restoration code and test this procedure routinely.

## Key loss

If the master key is permanently lost, encrypted artifacts cannot be recovered. This is expected cryptographic behavior, not a product failure. Keep access-controlled, offline recovery copies and test their retrieval.

## Database recovery

The BackupForge metadata database contains encrypted credential blobs and artifact metadata. Treat its backup as sensitive. Restoring it without the master key does not recover credentials or artifacts.

