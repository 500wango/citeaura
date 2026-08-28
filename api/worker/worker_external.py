"""Worker 外联发送与项目归档任务。"""

import json

from api.db import SessionLocal
from api.models import IntegrationCredential
from api.settings.crypto import decrypt_key
from api.worker.celery_app import celery_app


def _task_facade():
    from api.worker import tasks
    return tasks


@celery_app.task(name="citeaura.send_outreach")
def task_send_outreach(tenant_id: str, project_slug: str, draft_id: str, job_id=None):
    """领取已人工确认的草稿并通过租户 SMTP 发送。"""
    from api.adapters import outreach

    facade = _task_facade()
    action = "outreach_send"
    db = facade.SessionLocal()
    try:
        tenant = facade._tenant_record(db, tenant_id)
        if tenant is None:
            raise ValueError("tenant_not_found")
        tenant_name = tenant.directory_slug
        tenant_db_id = tenant.id
    finally:
        db.close()

    with facade._job_status(tenant_name, project_slug, action, job_id) as claim:
        if claim is facade._JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        try:
            credential_db = facade.SessionLocal()
            try:
                row = credential_db.query(IntegrationCredential).filter(
                    IntegrationCredential.tenant_id == tenant_db_id,
                    IntegrationCredential.provider == "outreach_smtp",
                ).first()
                if row is None:
                    raise outreach.OutreachError("smtp_not_configured")
                credentials = json.loads(facade.decrypt_key(row.encrypted_value))
                settings = json.loads(row.config_json or "{}")
            finally:
                credential_db.close()
        except Exception as exc:
            with facade.with_tenant_context(tenant_name, project_slug):
                outreach.mark_queued_failed(project_slug, draft_id, exc)
            raise
        with facade.with_tenant_context(tenant_name, project_slug):
            try:
                draft = outreach.claim_for_sending(project_slug, draft_id)
                result = outreach.send_smtp(draft, settings, credentials)
            except Exception as exc:
                outreach.mark_failed(project_slug, draft_id, exc)
                outreach.mark_queued_failed(project_slug, draft_id, exc)
                raise
            outreach.mark_sent(project_slug, draft_id)
            return {"status": "done", "draft_id": draft_id, **result}


@celery_app.task(name="citeaura.archive_project")
def task_archive_project(tenant_id: str, project_slug: str, job_id=None):
    """将本地活动项目写成经校验的对象存储快照。"""
    from api.adapters import archive

    facade = _task_facade()
    with facade._job_status(tenant_id, project_slug, "archive", job_id) as claim:
        if claim is facade._JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        result = archive.create_archive(tenant_id, project_slug)
        return {"status": "done", "project_slug": project_slug, "archive": result}


@celery_app.task(name="citeaura.restore_project")
def task_restore_project(
    tenant_id: str,
    project_slug: str,
    archive_id: str,
    overwrite: bool = False,
    job_id=None,
):
    """校验对象快照并恢复到本地活动项目。"""
    from api.adapters import archive

    facade = _task_facade()
    with facade._job_status(tenant_id, project_slug, "archive_restore", job_id) as claim:
        if claim is facade._JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        result = archive.restore_archive(tenant_id, project_slug, archive_id, overwrite=overwrite)
        return {"status": "done", "project_slug": project_slug, "restore": result}
