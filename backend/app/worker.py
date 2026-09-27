from celery import Celery

from .config import settings

celery_app = Celery("backupforge", broker=settings().redis_url, backend=settings().redis_url)
celery_app.conf.task_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.beat_schedule = {"backupforge-schedule-tick": {"task": "backupforge.schedule_tick", "schedule": 60.0}}


@celery_app.task(name="backupforge.execute_backup")
def backup_task(run_id: str) -> None:
    from .executor import execute_backup
    execute_backup(run_id)


@celery_app.task(name="backupforge.schedule_tick")
def schedule_tick() -> int:
    from .scheduler import queue_due_jobs
    return queue_due_jobs()

