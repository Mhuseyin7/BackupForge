"""Timezone-aware, bounded scheduler. Each tick can queue at most one run per job."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from sqlalchemy import select

from .db import SessionLocal
from .models import AuditLog, BackupRun, Job, RunState


def queue_due_jobs() -> int:
    queued = 0
    queued_ids: list[str] = []
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        for job in session.scalars(select(Job).where(Job.enabled.is_(True), Job.schedule.is_not(None))):
            try:
                local_now = now.astimezone(ZoneInfo(job.timezone))
                due_at = croniter(job.schedule, local_now).get_prev(datetime).astimezone(timezone.utc)
            except (ValueError, KeyError, ZoneInfoNotFoundError):
                session.add(AuditLog(event="schedule.invalid", resource_type="job", resource_id=str(job.id), detail={}))
                continue
            last_run = session.scalar(
                select(BackupRun).where(BackupRun.job_id == job.id).order_by(BackupRun.queued_at.desc()).limit(1)
            )
            # One missed occurrence becomes one run; old downtime occurrences never form a backlog.
            if last_run and last_run.queued_at and last_run.queued_at >= due_at:
                continue
            if session.scalar(select(BackupRun).where(BackupRun.job_id == job.id, BackupRun.state.in_([RunState.QUEUED, RunState.RUNNING, RunState.UPLOADING, RunState.VERIFYING])).limit(1)):
                continue
            run = BackupRun(job_id=job.id)
            session.add(run)
            session.flush()
            session.add(AuditLog(event="backup.queued.schedule", resource_type="run", resource_id=str(run.id), detail={"due_at": due_at.isoformat()}))
            queued_ids.append(str(run.id))
            queued += 1
        session.commit()
    # Dispatch only after every queued run is durable, so fast workers never see a missing row.
    from .worker import backup_task
    for run_id in queued_ids:
        backup_task.delay(run_id)
    return queued
