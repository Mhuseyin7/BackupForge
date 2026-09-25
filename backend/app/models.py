from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RunState(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    UPLOADING = "UPLOADING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VerificationState(str, enum.Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"


class Role(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.VIEWER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    source_type: Mapped[str] = mapped_column(String(32))
    source_config: Mapped[dict] = mapped_column(JSON, default=dict)
    encrypted_source_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    destination_id: Mapped[UUID] = mapped_column(ForeignKey("destinations.id"))
    schedule: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    retention: Mapped[dict] = mapped_column(JSON, default=dict)
    compression: Mapped[str] = mapped_column(String(12), default="zstd")
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    destination: Mapped["Destination"] = relationship(back_populates="jobs")
    runs: Mapped[list["BackupRun"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Destination(Base):
    __tablename__ = "destinations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    # This is encrypted application data, never plaintext credential JSON.
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    jobs: Mapped[list[Job]] = relationship(back_populates="destination")


class BackupRun(Base):
    __tablename__ = "backup_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    state: Mapped[RunState] = mapped_column(Enum(RunState), default=RunState.QUEUED, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    job: Mapped[Job] = relationship(back_populates="runs")
    artifact: Mapped["Artifact | None"] = relationship(back_populates="run", cascade="all, delete-orphan", uselist=False)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("backup_runs.id"), unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    original_size: Mapped[int] = mapped_column(Integer)
    compressed_size: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(128))
    checksum_algorithm: Mapped[str] = mapped_column(String(32), default="sha256")
    encryption: Mapped[str] = mapped_column(String(32), default="AES-256-GCM")
    destination: Mapped[str] = mapped_column(String(200))
    storage_key: Mapped[str] = mapped_column(String(1024), unique=True)
    verification_status: Mapped[VerificationState] = mapped_column(Enum(VerificationState), default=VerificationState.NOT_RUN)
    run: Mapped[BackupRun] = relationship(back_populates="artifact")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event: Mapped[str] = mapped_column(String(100), index=True)
    actor: Mapped[str] = mapped_column(String(200), default="system")
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
