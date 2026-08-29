

def list_prs(project_slug, config, token, *, refresh=False):
    """Return saved PR metadata, optionally refreshing status from GitHub."""
    rows = _read_state(project_slug)
    if not refresh or not token or not config.get("repo"):
        return rows
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    for row in rows:
        number = row.get("number")
        if not number:
            continue
        data, error = _api(session, "GET", f"https://api.github.com/repos/{config['repo']}/pulls/{number}")
        if error:
            continue
        if data.get("merged_at"):
            row["status"] = "merged"
        else:
            row["status"] = str(data.get("state") or row.get("status") or "open")
        row["updated_at"] = data.get("updated_at") or row.get("updated_at")
    if refresh:
        with geolib.project_lock(project_slug):
            geolib.write_json(_state_path(project_slug), rows[-100:])
    return rows
