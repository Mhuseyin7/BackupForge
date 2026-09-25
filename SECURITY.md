# Security Policy

Report vulnerabilities privately to the repository maintainers. Do not open public issues for credential exposure, authentication bypass, encryption defects, traversal vulnerabilities, or destination deletion defects.

## Security invariants

- `BACKUPFORGE_MASTER_KEY` is external to the database and required at startup.
- Credentials and artifacts use authenticated AES-256-GCM; every encryption receives a fresh random 96-bit nonce.
- Completion is impossible until destination bytes hash to the locally computed SHA-256.
- Secrets, database command stderr, and source credential values are excluded from application failure records.
- The worker invokes fixed trusted command names without a shell.
- Storage keys and restored tar paths are checked against traversal.

## Deployment responsibilities

Use TLS at the reverse proxy, a non-root runtime, restricted source mounts, short-lived backups credentials, private object buckets, network policies, and separately retained master-key recovery material. Rotate the master key only through a planned re-encryption migration; changing it makes prior encrypted material unreadable.

