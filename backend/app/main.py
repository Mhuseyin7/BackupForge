from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .artifacts import restore_filesystem
from .auth import current_user, make_token, password_hash, require, verify_password
from .config import settings
from .db import get_session, init_db
from .models import Artifact, AuditLog, BackupRun, Destination, Job, Role, RunState, User, VerificationState
from .security import decrypt_json, encrypt_json
from .retention import artifacts_to_delete
from .storage import backend_for
from .worker import backup_task

app = FastAPI(title="BackupForge", version="0.1.0", openapi_url="/api/v1/openapi.json", docs_url="/api/v1/docs")
app.add_middleware(CORSMiddleware, allow_origins=[], allow_credentials=False, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type"])


@app.on_event("startup")
def startup() -> None:
    settings().validate_security()
    settings().data_dir.mkdir(parents=True, exist_ok=True)
    init_db()


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
    return response


class RegisterInput(BaseModel):
    email: str
    password: str


class LoginInput(RegisterInput):
    pass


class DestinationInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str
    config: dict
    credentials: dict = Field(default_factory=dict, repr=False)


class JobInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_type: str
    source_config: dict
    source_credentials: dict = Field(default_factory=dict, repr=False)
    destination_id: UUID
    schedule: str | None = None
    timezone: str = "UTC"
    retention: dict = Field(default_factory=lambda: {"keep_latest": 7, "daily": 7, "weekly": 4, "monthly": 6})
    compression: str = "zstd"


class RestoreInput(BaseModel):
    target: str
    confirmation: str


def audit(session: Session, event: str, actor: User | str, resource_type: str, resource_id: UUID | str, detail: dict | None = None) -> None:
    session.add(AuditLog(event=event, actor=actor.email if isinstance(actor, User) else actor, resource_type=resource_type, resource_id=str(resource_id), detail=detail or {}))


def reject_embedded_secrets(config: dict) -> None:
    sensitive = {"password", "secret", "secret_key", "access_key", "token", "credential", "credentials"}
    if any(str(key).lower() in sensitive for key in config):
        raise HTTPException(422, "place credentials in the dedicated credentials field")


def job_view(job: Job) -> dict:
    return {"id": str(job.id), "name": job.name, "source_type": job.source_type, "destination_id": str(job.destination_id), "schedule": job.schedule, "timezone": job.timezone, "retention": job.retention, "compression": job.compression, "enabled": job.enabled}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready(session: Session = Depends(get_session)):
    session.execute(select(1))
    return {"status": "ready"}


@app.post("/api/v1/auth/register")
def register(payload: RegisterInput, session: Session = Depends(get_session)):
    # First account bootstrap only; subsequent identities must be owner-provisioned.
    if session.scalar(select(func.count()).select_from(User)):
        raise HTTPException(403, "initial owner already exists")
    user = User(email=payload.email.strip().lower(), password_hash=password_hash(payload.password), role=Role.OWNER)
    session.add(user)
    audit(session, "user.bootstrap", user, "user", user.id)
    session.commit()
    return {"access_token": make_token(user), "token_type": "bearer", "role": user.role.value}


@app.post("/api/v1/auth/login")
def login(payload: LoginInput, session: Session = Depends(get_session)):
    user = session.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "invalid credentials")
    audit(session, "auth.login", user, "user", user.id)
    session.commit()
    return {"access_token": make_token(user), "token_type": "bearer", "role": user.role.value}


@app.get("/api/v1/destinations")
def destinations(_: User = Depends(current_user), session: Session = Depends(get_session)):
    return [{"id": str(d.id), "name": d.name, "kind": d.kind, "config": d.config, "has_credentials": bool(d.encrypted_credentials)} for d in session.scalars(select(Destination).order_by(Destination.name))]


@app.post("/api/v1/destinations")
def create_destination(payload: DestinationInput, user: User = Depends(require(Role.OWNER, Role.ADMIN)), session: Session = Depends(get_session)):
    if payload.kind not in {"local", "s3"}:
        raise HTTPException(422, "destination kind must be local or s3")
    reject_embedded_secrets(payload.config)
    destination = Destination(name=payload.name, kind=payload.kind, config=payload.config, encrypted_credentials=encrypt_json(payload.credentials, settings().encryption_key()) if payload.credentials else None)
    session.add(destination)
    session.flush()
    audit(session, "destination.created", user, "destination", destination.id)
    session.commit()
    return {"id": str(destination.id), "name": destination.name, "kind": destination.kind}


@app.get("/api/v1/jobs")
def jobs(_: User = Depends(current_user), session: Session = Depends(get_session)):
    return [job_view(job) for job in session.scalars(select(Job).order_by(Job.name))]


@app.post("/api/v1/jobs")
def create_job(payload: JobInput, user: User = Depends(require(Role.OWNER, Role.ADMIN, Role.OPERATOR)), session: Session = Depends(get_session)):
    if not session.get(Destination, payload.destination_id):
        raise HTTPException(404, "destination not found")
    if payload.source_type not in {"filesystem", "postgresql", "mysql", "mariadb", "docker_volume"}:
        raise HTTPException(422, "unsupported source type")
    reject_embedded_secrets(payload.source_config)
    job = Job(**payload.model_dump(exclude={"source_credentials"}), encrypted_source_credentials=encrypt_json(payload.source_credentials, settings().encryption_key()) if payload.source_credentials else None)
    session.add(job)
    session.flush()
    audit(session, "job.created", user, "job", job.id)
    session.commit()
    return job_view(job)


@app.post("/api/v1/jobs/{job_id}/runs")
def start_run(job_id: UUID, user: User = Depends(require(Role.OWNER, Role.ADMIN, Role.OPERATOR)), session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job or not job.enabled:
        raise HTTPException(404, "active job not found")
    run = BackupRun(job_id=job.id)
    session.add(run)
    session.flush()
    audit(session, "backup.queued", user, "run", run.id)
    session.commit()
    backup_task.delay(str(run.id))
    return {"id": str(run.id), "state": run.state.value}


@app.get("/api/v1/runs")
def runs(_: User = Depends(current_user), session: Session = Depends(get_session)):
    return [{"id": str(r.id), "job_id": str(r.job_id), "state": r.state.value, "started_at": r.started_at, "completed_at": r.completed_at, "error_code": r.error_code} for r in session.scalars(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(100))]


@app.get("/api/v1/artifacts")
def artifacts(_: User = Depends(current_user), session: Session = Depends(get_session)):
    return [{"id": str(a.id), "job_id": str(a.job_id), "checksum": a.checksum, "original_size": a.original_size, "compressed_size": a.compressed_size, "destination": a.destination, "storage_key": a.storage_key, "verification_status": a.verification_status.value, "completed_at": a.completed_at} for a in session.scalars(select(Artifact).order_by(Artifact.completed_at.desc()).limit(200))]


@app.post("/api/v1/artifacts/{artifact_id}/restore")
def restore(artifact_id: UUID, payload: RestoreInput, user: User = Depends(require(Role.OWNER, Role.ADMIN)), session: Session = Depends(get_session)):
    artifact = session.get(Artifact, artifact_id)
    if not artifact or artifact.verification_status != VerificationState.VERIFIED:
        raise HTTPException(404, "verified artifact not found")
    if payload.confirmation != f"RESTORE {artifact.id}":
        raise HTTPException(422, "confirmation must exactly match RESTORE <artifact-id>")
    job = session.get(Job, artifact.job_id)
    if job.source_type != "filesystem":
        raise HTTPException(422, "database and volume restores require their dedicated guided workflows")
    destination = job.destination
    credentials = decrypt_json(destination.encrypted_credentials, settings().encryption_key()) if destination.encrypted_credentials else {}
    backend = backend_for(destination.kind, destination.config, credentials)
    target = __import__("pathlib").Path(payload.target).resolve()
    if not any(target == root or root in target.parents for root in settings().restore_roots):
        raise HTTPException(422, "restore target is outside BACKUPFORGE_ALLOWED_RESTORE_ROOTS")
    audit(session, "restore.started", user, "artifact", artifact.id, {"target": str(target)})
    session.commit()
    try:
        with backend.open(artifact.storage_key) as stream:
            restore_filesystem(stream, settings().encryption_key(), target, settings().data_dir / "tmp")
        audit(session, "restore.finished", user, "artifact", artifact.id)
        session.commit()
        return {"status": "restored"}
    except Exception:
        audit(session, "restore.failed", user, "artifact", artifact.id)
        session.commit()
        raise HTTPException(500, "restore failed")


@app.post("/api/v1/jobs/{job_id}/retention")
def apply_retention(job_id: UUID, dry_run: bool = True, user: User = Depends(require(Role.OWNER, Role.ADMIN)), session: Session = Depends(get_session)):
    """Deterministic, verification-only retention. Dry-run defaults to true."""
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    valid = list(session.scalars(select(Artifact).where(Artifact.job_id == job.id, Artifact.verification_status == VerificationState.VERIFIED).order_by(Artifact.completed_at.desc())))
    candidates = artifacts_to_delete(valid, job.retention)
    response = [{"id": str(item.id), "storage_key": item.storage_key, "completed_at": item.completed_at} for item in candidates]
    if dry_run:
        return {"dry_run": True, "delete": response}
    credentials = decrypt_json(job.destination.encrypted_credentials, settings().encryption_key()) if job.destination.encrypted_credentials else {}
    backend = backend_for(job.destination.kind, job.destination.config, credentials)
    for item in candidates:
        backend.delete(item.storage_key)
        session.delete(item)
        audit(session, "backup.deleted", user, "artifact", item.id, {"retention": True})
    session.commit()
    return {"dry_run": False, "deleted": response}


@app.get("/api/v1/audit")
def audit_log(_: User = Depends(require(Role.OWNER, Role.ADMIN)), session: Session = Depends(get_session)):
    return [{"event": item.event, "actor": item.actor, "resource_type": item.resource_type, "resource_id": item.resource_id, "detail": item.detail, "created_at": item.created_at} for item in session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(250))]


@app.get("/metrics", response_class=PlainTextResponse)
def metrics(session: Session = Depends(get_session)):
    completed = session.scalar(select(func.count()).select_from(BackupRun).where(BackupRun.state == RunState.COMPLETED)) or 0
    failed = session.scalar(select(func.count()).select_from(BackupRun).where(BackupRun.state == RunState.FAILED)) or 0
    bad = session.scalar(select(func.count()).select_from(Artifact).where(Artifact.verification_status == VerificationState.FAILED)) or 0
    bytes_done = session.scalar(select(func.coalesce(func.sum(Artifact.compressed_size), 0))) or 0
    queued = session.scalar(select(func.count()).select_from(BackupRun).where(BackupRun.state == RunState.QUEUED)) or 0
    return f"backupforge_runs_completed_total {completed}\nbackupforge_runs_failed_total {failed}\nbackupforge_verification_failures_total {bad}\nbackupforge_transferred_bytes_total {bytes_done}\nbackupforge_queue_depth {queued}\n"
