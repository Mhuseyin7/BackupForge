from celery import Celery

from .config import settings

celery_app = Celery("backupforge", broker=settings().redis_url, backend=settings().redis_url)
celery_app.conf.task_serializer = "json"
celery_app.conf.accept_content = ["json"]


@celery_app.task(name="backupforge.execute_backup")
def backup_task(run_id: str) -> None:
    from .executor import execute_backup
    execute_backup(run_id)

