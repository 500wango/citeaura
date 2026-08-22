"""Unauthenticated client download for Agency delivery-share tokens."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.adapters import delivery, delivery_share
from api.adapters.engine import geolib, with_tenant_context
from api.adapters.exceptions import GeoEngineError
from api.db import get_db
from api.models import Project, Tenant
from api.projects.router import _delivery_package_kind, _stream_delivery_zip


router = APIRouter(prefix="/api/v1/public", tags=["public"])


def _error(status_code, message):
    raise HTTPException(status_code=status_code, detail={"error": message})


@router.get("/delivery-packs/{token}")
def download_shared_delivery(token: str, db: Session = Depends(get_db)):
    """Download a sendable diagnostic ZIP with a time-limited Agency share token."""
    share = delivery_share.resolve_share(db, token)
    if share is None:
        _error(status.HTTP_404_NOT_FOUND, "delivery_share_not_found")
    project = db.get(Project, share.project_id)
    tenant = db.get(Tenant, project.tenant_id) if project is not None else None
    if project is None or tenant is None or project.archived_at is not None:
        _error(status.HTTP_404_NOT_FOUND, "delivery_share_not_found")
    with with_tenant_context(tenant.directory_slug, project.slug):
        directory = geolib.project_dir(project.slug) / "delivery" / share.delivery_date
        if not directory.is_dir():
            _error(status.HTTP_404_NOT_FOUND, "delivery_not_found")
        try:
            directory = delivery.validate_existing_delivery_contract(directory)
        except GeoEngineError as exc:
            try:
                directory = delivery.ensure_delivery_contract(project.slug, directory)
            except GeoEngineError as rebuild_exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "delivery_contract_invalid", "detail": str(rebuild_exc)},
                ) from rebuild_exc
        asset_index = geolib.read_json(directory / "assets" / "index.json", {}) or {}
        readiness = str(asset_index.get("readiness") or "unknown")
        package_kind = _delivery_package_kind(asset_index, readiness)
        source_revision = str(asset_index.get("source_revision") or "unknown")
        return _stream_delivery_zip(directory, package_kind, share.delivery_date, readiness, source_revision)
