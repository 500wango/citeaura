"""项目 searchdata 目录下的快照文件读写；按文件名轮转历史，互不误删。"""

from datetime import datetime, timezone

from api.adapters.engine import geolib


SNAPSHOT_DIR = "searchdata"
HISTORY_KEEP = 5


def directory(project_slug):
    return geolib.project_dir(project_slug) / SNAPSHOT_DIR


def path(project_slug, filename):
    return directory(project_slug) / filename


def read(project_slug, filename, schema_version):
    data = geolib.read_json(path(project_slug, filename), None)
    return data if isinstance(data, dict) and data.get("schema_version") == schema_version else None


def write(project_slug, filename, snapshot):
    """新快照覆盖当前文件；只把同名的旧文件移入 history/，保留最近几份。"""
    target = path(project_slug, filename)
    if target.is_file():
        history = target.parent / "history"
        history.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target.replace(history / f"{target.stem}-{stamp}.json")
        for stale in sorted(history.glob(f"{target.stem}-*.json"))[:-HISTORY_KEEP]:
            stale.unlink(missing_ok=True)
    geolib.write_json(target, snapshot)
    return snapshot


def delete(project_slug, filename):
    """只删除指定快照及其历史；目录为空时才移除，避免误删另一类快照。"""
    directory_path = directory(project_slug)
    if directory_path.is_symlink():
        raise ValueError("searchdata directory must not be a symlink")
    target = path(project_slug, filename)
    existed = target.is_file()
    target.unlink(missing_ok=True)
    history = directory_path / "history"
    if history.is_dir():
        for stale in history.glob(f"{target.stem}-*.json"):
            stale.unlink(missing_ok=True)
        if not any(history.iterdir()):
            history.rmdir()
    if directory_path.is_dir() and not any(directory_path.iterdir()):
        directory_path.rmdir()
    return existed
