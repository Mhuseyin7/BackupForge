# BackupForge

> **A backup that cannot be restored is not a valid backup.**

BackupForge, self-hosted backup orchestration, verification, retention ve restore platformudur. Açık kaynak kodlu bir software olarak geliştirilmektedir; **[muhammedkoca.com.tr](https://muhammedkoca.com.tr)** tarafından tasarlanmış ve geliştirilmiştir.

Projenin odağı yalnızca backup oluşturmak değildir. Her artifact; encrypt edilir, hedef storage'a upload edilir ve checksum doğrulamasından geçer. Required verification tamamlanmadan bir run **COMPLETED** olarak raporlanmaz.

## Highlights

- Filesystem directory/file backup workflow
- PostgreSQL için trusted `pg_dump` custom-format adapter
- MySQL/MariaDB için `mariadb-dump --single-transaction` adapter
- Named Docker volume backup adapter (review edilmiş helper image ile)
- Local filesystem / mounted NAS ve S3-compatible storage (MinIO dahil)
- Streaming tar → zstd/gzip → AES-256-GCM pipeline
- SHA-256 remote checksum verification
- Redis distributed lock ve Celery worker orchestration
- Deterministic, dry-run destekli retention
- Guided ve path-safe filesystem restore
- Role-gated FastAPI API, audit log, health/readiness ve metrics endpoint'leri
- Docker Compose ile non-root deployment

## Core workflow

```text
Schedule → Distributed lock → Backup source → Compress + encrypt → Checksum
       → Upload → Remote verification → Retention / notification
```

Bir artifact'in success status alabilmesi için local SHA-256 değeri, upload sonrasında destination üzerinden tekrar hesaplanan SHA-256 ile aynı olmalıdır.

## Technology stack

| Area | Technology |
| --- | --- |
| API | FastAPI, Python, SQLAlchemy |
| Database | PostgreSQL |
| Queue / lock | Redis, Celery |
| Crypto | `cryptography` AES-256-GCM |
| Compression | zstd (preferred), gzip |
| Storage | Local/NAS, S3-compatible APIs |
| Web UI | Next.js, TypeScript, React, Tailwind |
| Deployment | Docker, Docker Compose |

## Quick start

### 1. Configuration

`.env.example` dosyasını `.env` olarak kopyalayın ve her değeri production için güvenli şekilde tanımlayın.

```bash
BACKUPFORGE_MASTER_KEY=<32-byte-base64-key>
BACKUPFORGE_AUTH_SECRET=<at-least-32-characters>
POSTGRES_PASSWORD=<strong-password>
BACKUP_SOURCE_PATH=/absolute/path/to/trusted/source
```

`BACKUPFORGE_MASTER_KEY` database içine yazılmaz. Bu key kaybolursa encrypted backup artifact'leri recover edilemez.

Generate example:

```bash
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

### 2. Start the platform

```bash
docker compose up --build
```

API default olarak `http://localhost:8000` üzerinden erişilebilir.

### 3. Bootstrap owner

İlk owner account, yalnızca bir kez oluşturulabilir:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"owner@example.com","password":"use-a-long-unique-password"}'
```

Response içindeki Bearer token ile destination ve job resources yönetilir.

## Security model

- Credentials API'de ayrı `credentials` payload alanından alınır ve database'e AES-GCM encrypted blob olarak kaydedilir.
- Plaintext password/secret değerlerinin source veya storage config içerisine konması reject edilir.
- Artifact data metadata database'e kaydedilmez.
- Crypto için custom algorithm yoktur: standard AES-256-GCM ve unique random nonce kullanılır.
- Backup command'leri shell ile çalıştırılmaz; password values command-line argument veya worker failure record içine yazılmaz.
- Local storage keys ve restore archive paths traversal saldırılarına karşı validate edilir.
- Restore endpoint yalnızca `BACKUPFORGE_ALLOWED_RESTORE_ROOTS` altında hedef kabul eder ve explicit confirmation ister.
- Docker API socket'i API service'e mount edilmez.

Detaylar için [SECURITY.md](SECURITY.md) dokümanına bakın.

## Source adapters

### Filesystem

`FilesystemSource`, trusted source root altında include/exclude patterns ve symlink policy ile tar stream üretir. Source path, `BACKUPFORGE_ALLOWED_SOURCE_ROOTS` dışına çıkamaz.

### PostgreSQL

`PostgreSQLSource`, `pg_dump --format=custom --no-password` kullanır. Database password yalnızca process environment üzerinden geçer; log veya command argument olarak kullanılmaz.

### MySQL / MariaDB

`MySQLSource`, transactional InnoDB tables için `mariadb-dump --single-transaction` kullanır. Non-transactional tables için consistent snapshot garantisi yoktur; maintenance window veya database-specific strategy uygulanmalıdır.

### Docker volumes

`DockerVolumeSource`, generic privileged container çalıştırmaz. Dedicated ve security-reviewed helper image gerektirir. Docker socket erişimini yalnızca isolated worker environment'a, explicit risk review sonrasında verin.

## Storage backends

- **LocalStorage**: Atomic temporary upload + rename ile local filesystem ve mounted NAS desteği.
- **S3Storage**: Endpoint, region, bucket, prefix, access key ve secret key ile S3/MinIO desteği.

Architecture, gelecekte SFTP, WebDAV, Cloudflare R2 ve Backblaze B2 adapters eklenebilecek şekilde `StorageBackend` abstraction kullanır.

## Retention

Retention policy örneği:

```json
{
  "keep_latest": 7,
  "daily": 7,
  "weekly": 4,
  "monthly": 6
}
```

Retention yalnızca `VERIFIED` artifact'leri değerlendirir. En yeni valid artifact hiçbir koşulda delete listesine alınmaz. Endpoint default olarak `dry_run=true` davranır.

## API overview

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Liveness health check |
| `GET /ready` | Database readiness check |
| `GET /metrics` | Prometheus-style metrics |
| `/api/v1/auth/*` | Owner bootstrap ve login |
| `/api/v1/destinations` | Storage destination management |
| `/api/v1/jobs` | Backup job management |
| `/api/v1/jobs/{id}/runs` | Backup run queue |
| `/api/v1/artifacts` | Verified artifact inventory |
| `/api/v1/artifacts/{id}/restore` | Explicit-confirmation filesystem restore |
| `/api/v1/jobs/{id}/retention` | Dry-run veya actual retention |
| `/api/v1/audit` | Security-sensitive audit trail |

Interactive OpenAPI documentation: `/api/v1/docs`

## Development

```powershell
py -m pip install -e ".[dev]"
py -m pytest
py -m ruff check backend
```

Docker ile tested flows:

- Container image build
- Backend / migration syntax validation
- AES-GCM credential encryption round-trip
- Local storage checksum verification
- Stream encryption/decryption round-trip
- Filesystem backup → artifact → restore smoke test

## Disaster recovery

BackupForge application unavailable olsa bile, artifact dosyası, recorded SHA-256 checksum ve master key ile recovery mümkündür. Full procedure için [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) belgesini okuyun.

> Master key kalıcı olarak kaybolursa encrypted backup'lar recover edilemez. Recovery key material'ı BackupForge database ve destination'dan ayrı, access-controlled bir yerde saklayın.

## Open source & attribution

BackupForge açık kaynak kodludur ve [Apache-2.0 License](LICENSE) ile lisanslanmıştır.

Built and maintained by **[muhammedkoca.com.tr](https://muhammedkoca.com.tr)**.

Contributions, security reporting ve development guidelines için [CONTRIBUTING.md](CONTRIBUTING.md) ve [SECURITY.md](SECURITY.md) dosyalarına göz atın.
