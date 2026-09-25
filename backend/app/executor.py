from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import redis
from sqlalchemy import select

from .artifacts import create_artifact
from .config import settings
from .db import SessionLocal
from .models import Artifact, AuditLog, BackupRun, RunState, VerificationState
from .security import decrypt_json
from .sources import source_for
from .storage import backend_for

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def execute_backup(run_id: str) -> None:
    """State-changing worker task. A run can complete only after remote byte verification."""
    app_settings = settings()
    client = redis.Redis.from_url(app_settings.redis_url)
    with SessionLocal() as session:
        run = session.get(BackupRun, UUID(run_id))
        if run is None or run.state != RunState.QUEUED:
            return
        job = run.job
        lock = client.lock(f"backupforge:job:{job.id}", timeout=24 * 3600, blocking_timeout=0)
        if not lock.acquire(blocking=False):
            run.state, run.error_code, run.error_detail = RunState.CANCELLED, "CONCURRENT_RUN", "A run for this job is already active"
            session.commit()
            return
        artifact_path: Path | None = None
        try:
            run.state, run.started_at = RunState.RUNNING, _now()
            session.commit()
            source_config = {**job.source_config, **(decrypt_json(job.encrypted_source_credentials, app_settings.encryption_key()) if job.encrypted_source_credentials else {})}
            source = source_for(job.source_type, source_config, app_settings)
            artifact_path, original, packed, digest = create_artifact(source, job.compression, app_settings.encryption_key(), app_settings.data_dir / "tmp")
            destination_credentials = decrypt_json(job.destination.encrypted_credentials, app_settings.encryption_key()) if job.destination.encrypted_credentials else {}
            backend = backend_for(job.destination.kind, job.destination.config, destination_credentials)
            storage_key = f"jobs/{job.id}/{run.id}.bforge"
            run.state = RunState.UPLOADING
            session.commit()
            with artifact_path.open("rb") as stream:
                backend.upload(storage_key, stream)
            run.state = RunState.VERIFYING
            session.commit()
            if backend.checksum(storage_key) != digest:
                try:
                    backend.delete(storage_key)
                finally:
                    raise RuntimeError("remote checksum mismatch")
            completed = _now()
            session.add(Artifact(job_id=job.id, run_id=run.id, started_at=run.started_at, completed_at=completed, original_size=original, compressed_size=packed, checksum=digest, destination=job.destination.name, storage_key=storage_key, verification_status=VerificationState.VERIFIED))
            run.state, run.completed_at = RunState.COMPLETED, completed
            session.add(AuditLog(event="backup.completed", resource_type="run", resource_id=str(run.id), detail={"artifact_checksum": digest}))
            session.commit()
        except Exception as exc:
            session.rollback()
            run = session.get(BackupRun, UUID(run_id))
            if run:
                run.state, run.completed_at, run.error_code = RunState.FAILED, _now(), type(exc).__name__
                # Do not persist exception strings; db client errors can include passwords.
                run.error_detail = "Backup failed. Consult worker logs; secret-bearing command output is suppressed."
                session.add(AuditLog(event="backup.failed", resource_type="run", resource_id=str(run.id), detail={"code": type(exc).__name__}))
                session.commit()
            logger.exception("Backup run failed id=%s type=%s", run_id, type(exc).__name__)
        finally:
            if artifact_path:
                artifact_path.unlink(missing_ok=True)
            try:
                lock.release()
            except Exception:
                logger.warning("Could not release distributed lock for run id=%s", run_id)

