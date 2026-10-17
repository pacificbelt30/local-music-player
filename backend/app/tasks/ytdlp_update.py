from app.tasks.celery_app import celery_app
from app.services.ytdlp_updates import check


@celery_app.task(name="app.tasks.ytdlp_update.check")
def check_ytdlp_update(force: bool = False):
    return check(force=force)

