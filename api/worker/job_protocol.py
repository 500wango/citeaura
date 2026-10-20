"""父进程与一次性引擎子进程之间的 JSON 行协议。"""

import json


PROTOCOL_VERSION = 1


def encode_job_request(payload):
    document = dict(payload or {})
    document["protocol"] = PROTOCOL_VERSION
    return json.dumps(document, ensure_ascii=False, sort_keys=True)


def decode_job_request(text):
    document = json.loads(text or "{}")
    if document.get("protocol") != PROTOCOL_VERSION:
        raise ValueError("unsupported job protocol")
    document.pop("protocol", None)
    return document


def event(kind, **payload):
    return json.dumps({"type": kind, **payload}, ensure_ascii=False, sort_keys=True)


def progress_event(stage, progress=None):
    return event("progress", stage=str(stage), progress=progress)


def result_event(result, usage=None):
    return event("result", result=result if isinstance(result, dict) else {}, usage=dict(usage or {}))


def error_event(message):
    return event("error", error=str(message)[:2000])


def parse_events(text):
    """返回 (result, usage, errors, progress)；无法解析的行直接忽略。"""
    result = None
    usage = {}
    errors = []
    progress = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict):
            continue
        kind = message.get("type")
        if kind == "result":
            result = message.get("result") or {}
            usage = message.get("usage") or {}
        elif kind == "error":
            errors.append(str(message.get("error") or "engine job failed"))
        elif kind == "progress":
            progress.append(message)
    return result, usage, errors, progress
