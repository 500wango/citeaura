"""将租户项目目录归档到 S3 兼容对象存储。"""

import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from api import config
from api.adapters import engine as engine_adapter


STATE_VERSION = 1
STATE_RELATIVE_PATH = Path(".disvorai") / "archives.json"
SNAPSHOT_MANIFEST_NAME = ".disvorai-snapshot.json"
EXCLUDED_ROOTS = frozenset((".disvorai", ".jobs"))
MAX_FILES = 100000
PREFIX_PATTERN = re.compile(r"[A-Za-z0-9._/-]+")


class ArchiveError(RuntimeError):
    pass


def _settings(require_configured=True):
    value = config.object_storage_settings()
    prefix = value["prefix"]
    if prefix and (not PREFIX_PATTERN.fullmatch(prefix) or ".." in PurePosixPath(prefix).parts):
        raise ArchiveError("object_storage_prefix_invalid")
    if require_configured and not value["bucket"]:
        raise ArchiveError("object_storage_not_configured")
    return value


def storage_status():
    """返回不含凭证的对象存储配置状态。"""
    value = _settings(require_configured=False)
    return {
        "configured": bool(value["bucket"]),
        "bucket": value["bucket"] or None,
        "endpoint_type": "s3_compatible" if value["endpoint_url"] else "aws_s3",
        "region": value["region"],
        "prefix": value["prefix"],
        "retention_count": value["retention_count"],
        "server_side_encryption": value["server_side_encryption"],
        "filesystem_ssot": True,
    }


def _client(settings=None):
    settings = settings or _settings()
    import boto3
    from botocore.config import Config

    style = "path" if settings["force_path_style"] else "auto"
    return boto3.client(
        "s3",
        endpoint_url=settings["endpoint_url"],
        region_name=settings["region"],
        aws_access_key_id=settings["access_key_id"],
        aws_secret_access_key=settings["secret_access_key"],
        config=Config(signature_version="s3v4", s3={"addressing_style": style}),
    )


def _project_directory(tenant_name, project_slug):
    tenant_slug = engine_adapter.tenant_slug(tenant_name)
    project_slug = engine_adapter._valid_slug(project_slug, "project")
    work_root = engine_adapter.WORK_ROOT.resolve()
    project_directory = work_root / tenant_slug / project_slug
    try:
        project_directory.resolve().relative_to(work_root)
    except ValueError as exc:
        raise ArchiveError("project_directory_invalid") from exc
    return project_directory


def _state_path(project_directory):
    return project_directory / STATE_RELATIVE_PATH


def _read_state(project_directory):
    path = _state_path(project_directory)
    if path.is_symlink() or path.parent.is_symlink():
        raise ArchiveError("archive_state_invalid")
    if not path.exists():
        return {"version": STATE_VERSION, "archives": []}
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveError("archive_state_invalid") from exc
    if value.get("version") != STATE_VERSION or not isinstance(value.get("archives"), list):
        raise ArchiveError("archive_state_invalid")
    return value


def _write_state(project_directory, state):
    path = _state_path(project_directory)
    if path.is_symlink() or path.parent.is_symlink():
        raise ArchiveError("archive_state_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", "utf-8")
    os.replace(temporary, path)


def list_archives(tenant_name, project_slug):
    project_directory = _project_directory(tenant_name, project_slug)
    state = _read_state(project_directory)
    return sorted(state["archives"], key=lambda item: item.get("created_at", ""), reverse=True)


def _hash_file(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _source_files(project_directory):
    files = []
    if not project_directory.is_dir():
        raise ArchiveError("project_files_not_found")
    for path in sorted(project_directory.rglob("*")):
        relative = path.relative_to(project_directory)
        if not relative.parts or relative.parts[0] in EXCLUDED_ROOTS:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        sha256, size = _hash_file(path)
        files.append({"path": relative.as_posix(), "sha256": sha256, "size_bytes": size})
        if len(files) > MAX_FILES:
            raise ArchiveError("archive_file_limit_exceeded")
    if not files:
        raise ArchiveError("archive_has_no_files")
    return files


def _build_snapshot(project_directory, tenant_slug, project_slug, archive_id, created_at, temporary_path):
    files = _source_files(project_directory)
    snapshot_manifest = {
        "version": STATE_VERSION,
        "archive_id": archive_id,
        "tenant_slug": tenant_slug,
        "project_slug": project_slug,
        "created_at": created_at,
        "files": files,
    }
    manifest_bytes = json.dumps(snapshot_manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with tarfile.open(temporary_path, "w:gz") as archive:
        manifest_info = tarfile.TarInfo(SNAPSHOT_MANIFEST_NAME)
        manifest_info.size = len(manifest_bytes)
        manifest_info.mode = 0o600
        archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
        for item in files:
            archive.add(project_directory / item["path"], arcname=item["path"], recursive=False)
    with tempfile.TemporaryDirectory() as verification_name:
        _extract_verified(
            temporary_path,
            Path(verification_name),
            archive_id,
            tenant_slug,
            project_slug,
        )
    sha256, size = _hash_file(temporary_path)
    return snapshot_manifest, sha256, size


def _object_key(settings, tenant_slug, project_slug, created_at, archive_id):
    timestamp = created_at.replace("-", "").replace(":", "").replace("+00:00", "Z")
    parts = [settings["prefix"], tenant_slug, project_slug, f"{timestamp}-{archive_id}.tar.gz"]
    return "/".join(part for part in parts if part)


def _apply_retention(client, settings, state):
    active = sorted(
        (item for item in state["archives"] if item.get("status") == "available"),
        key=lambda item: item.get("created_at", ""),
        reverse=True,
    )
    for item in active[settings["retention_count"]:]:
        try:
            client.delete_object(Bucket=settings["bucket"], Key=item["object_key"])
        except Exception as exc:  # noqa: BLE001 - 新归档成功不应被保留清理失败覆盖
            item["retention_error"] = type(exc).__name__
            continue
        item["status"] = "expired"
        item["expired_at"] = datetime.now(timezone.utc).isoformat()
        item.pop("retention_error", None)


def create_archive(tenant_name, project_slug):
    """创建并校验一个不可变项目快照。"""
    settings = _settings()
    tenant_slug = engine_adapter.tenant_slug(tenant_name)
    project_slug = engine_adapter._valid_slug(project_slug, "project")
    project_directory = _project_directory(tenant_slug, project_slug)
    created_at = datetime.now(timezone.utc).isoformat()
    archive_id = uuid.uuid4().hex[:16]
    object_key = _object_key(settings, tenant_slug, project_slug, created_at, archive_id)
    client = _client(settings)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as temporary:
        manifest, sha256, size = _build_snapshot(
            project_directory,
            tenant_slug,
            project_slug,
            archive_id,
            created_at,
            Path(temporary.name),
        )
        temporary.seek(0)
        extra_args = {
            "ContentType": "application/gzip",
            "Metadata": {
                "sha256": sha256,
                "archive-id": archive_id,
                "tenant-slug": tenant_slug,
                "project-slug": project_slug,
            },
        }
        if settings["server_side_encryption"]:
            extra_args["ServerSideEncryption"] = settings["server_side_encryption"]
        client.upload_fileobj(
            temporary,
            settings["bucket"],
            object_key,
            ExtraArgs=extra_args,
        )
    head = client.head_object(Bucket=settings["bucket"], Key=object_key)
    metadata = {str(key).lower(): str(value) for key, value in (head.get("Metadata") or {}).items()}
    if int(head.get("ContentLength", -1)) != size or metadata.get("sha256") != sha256:
        try:
            client.delete_object(Bucket=settings["bucket"], Key=object_key)
        except Exception:  # noqa: BLE001 - 保留原始校验错误
            pass
        raise ArchiveError("archive_upload_verification_failed")
    entry = {
        "id": archive_id,
        "status": "available",
        "created_at": created_at,
        "object_key": object_key,
        "sha256": sha256,
        "size_bytes": size,
        "file_count": len(manifest["files"]),
    }
    state = _read_state(project_directory)
    state["archives"].append(entry)
    _apply_retention(client, settings, state)
    _write_state(project_directory, state)
    return entry


def _archive_entry(project_directory, archive_id):
    state = _read_state(project_directory)
    entry = next((item for item in state["archives"] if item.get("id") == archive_id), None)
    if entry is None:
        raise ArchiveError("archive_not_found")
    if entry.get("status") != "available":
        raise ArchiveError("archive_not_available")
    return state, entry


def _safe_members(archive, manifest):
    files = manifest.get("files")
    if manifest.get("version") != STATE_VERSION or not isinstance(files, list):
        raise ArchiveError("archive_manifest_invalid")
    expected = {}
    for item in files:
        if not isinstance(item, dict):
            raise ArchiveError("archive_manifest_invalid")
        path = item.get("path")
        sha256 = item.get("sha256")
        size = item.get("size_bytes")
        pure_path = PurePosixPath(path) if isinstance(path, str) else None
        if (
            pure_path is None
            or pure_path.is_absolute()
            or ".." in pure_path.parts
            or not pure_path.parts
            or pure_path.parts[0] in EXCLUDED_ROOTS
            or not re.fullmatch(r"[0-9a-f]{64}", str(sha256 or ""))
            or not isinstance(size, int)
            or size < 0
            or path in expected
        ):
            raise ArchiveError("archive_manifest_invalid")
        expected[path] = item
    if not expected or len(expected) > MAX_FILES:
        raise ArchiveError("archive_manifest_invalid")
    members = {}
    all_members = archive.getmembers()
    manifest_members = [member for member in all_members if member.name == SNAPSHOT_MANIFEST_NAME]
    if len(manifest_members) != 1 or not manifest_members[0].isfile():
        raise ArchiveError("archive_manifest_invalid")
    for member in all_members:
        if member.name == SNAPSHOT_MANIFEST_NAME:
            continue
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not member.isfile() or member.name not in expected:
            raise ArchiveError("archive_member_invalid")
        if member.name in members:
            raise ArchiveError("archive_member_invalid")
        members[member.name] = member
    if set(members) != set(expected):
        raise ArchiveError("archive_manifest_invalid")
    return expected, members


def _extract_verified(archive_path, extraction_directory, expected_archive_id, tenant_slug, project_slug):
    try:
        source_context = tarfile.open(archive_path, "r:gz")
    except (OSError, tarfile.TarError) as exc:
        raise ArchiveError("archive_format_invalid") from exc
    with source_context as source:
        try:
            manifest_member = source.getmember(SNAPSHOT_MANIFEST_NAME)
        except KeyError as exc:
            raise ArchiveError("archive_manifest_invalid") from exc
        manifest_handle = source.extractfile(manifest_member)
        if manifest_handle is None:
            raise ArchiveError("archive_manifest_invalid")
        try:
            manifest = json.loads(manifest_handle.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArchiveError("archive_manifest_invalid") from exc
        if (
            manifest.get("archive_id") != expected_archive_id
            or manifest.get("tenant_slug") != tenant_slug
            or manifest.get("project_slug") != project_slug
        ):
            raise ArchiveError("archive_identity_mismatch")
        expected, members = _safe_members(source, manifest)
        for name, member in members.items():
            handle = source.extractfile(member)
            if handle is None:
                raise ArchiveError("archive_member_invalid")
            target = extraction_directory / Path(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with target.open("wb") as output:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
            if digest.hexdigest() != expected[name]["sha256"] or size != expected[name]["size_bytes"]:
                raise ArchiveError("archive_file_verification_failed")
    return manifest


def _restore_target(project_directory, relative_path):
    current = project_directory
    parts = PurePosixPath(relative_path).parts
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ArchiveError("archive_restore_path_invalid")
    return project_directory / Path(*parts)


def restore_archive(tenant_name, project_slug, archive_id, overwrite=False):
    """下载、校验并把快照合并回本地项目目录。"""
    settings = _settings()
    tenant_slug = engine_adapter.tenant_slug(tenant_name)
    project_slug = engine_adapter._valid_slug(project_slug, "project")
    archive_id = str(archive_id or "")
    if not re.fullmatch(r"[0-9a-f]{16}", archive_id):
        raise ArchiveError("archive_id_invalid")
    project_directory = _project_directory(tenant_slug, project_slug)
    state, entry = _archive_entry(project_directory, archive_id)
    client = _client(settings)
    with tempfile.TemporaryDirectory() as temporary_name:
        temporary_directory = Path(temporary_name)
        archive_path = temporary_directory / "snapshot.tar.gz"
        with archive_path.open("wb") as output:
            client.download_fileobj(settings["bucket"], entry["object_key"], output)
        sha256, size = _hash_file(archive_path)
        if sha256 != entry["sha256"] or size != entry["size_bytes"]:
            raise ArchiveError("archive_download_verification_failed")
        extraction_directory = temporary_directory / "extracted"
        extraction_directory.mkdir()
        manifest = _extract_verified(
            archive_path,
            extraction_directory,
            archive_id,
            tenant_slug,
            project_slug,
        )
        conflicts = []
        for item in manifest["files"]:
            target = _restore_target(project_directory, item["path"])
            if target.exists():
                if not target.is_file() or _hash_file(target)[0] != item["sha256"]:
                    conflicts.append(item["path"])
        if conflicts and not overwrite:
            raise ArchiveError("archive_restore_conflict")
        for item in manifest["files"]:
            source = extraction_directory / Path(*PurePosixPath(item["path"]).parts)
            target = _restore_target(project_directory, item["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary_target = target.with_name(f".{target.name}.{uuid.uuid4().hex}.restore")
            shutil.copyfile(source, temporary_target)
            os.replace(temporary_target, target)
    entry["restored_at"] = datetime.now(timezone.utc).isoformat()
    entry["last_restore_overwrote"] = bool(overwrite)
    _write_state(project_directory, state)
    return {
        "id": archive_id,
        "status": "restored",
        "restored_at": entry["restored_at"],
        "file_count": entry["file_count"],
        "overwrote": bool(overwrite),
    }
