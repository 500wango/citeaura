"""SaaS 管线动作的唯一运行时目录。"""


ACTION_CATALOG = {
    "crawl": {
        "label": "Crawl Website",
        "args": ["--max-pages"],
        "method": "cmd_crawl",
        "defaults": {"max_pages": None},
        "retryable": True,
    },
    "audit": {
        "label": "Site Audit",
        "args": [],
        "method": "cmd_audit",
        "defaults": {},
        "retryable": True,
    },
    "sample": {
        "label": "AI Sampling",
        "args": ["--limit", "--repeat", "--platforms", "--question-ids"],
        "method": "cmd_sample",
        "defaults": {"limit": None, "repeat": 1, "platforms": None, "question_ids": None},
        "retryable": True,
    },
    "bootstrap": {
        "label": "Auto-bootstrap Baseline",
        "args": ["--skip-llm"],
        "method": "cmd_bootstrap",
        "defaults": {"skip_llm": False},
        "retryable": True,
    },
    "deliverables": {
        "label": "Generate Three Deliverables",
        "args": [],
        "method": "cmd_deliverables",
        "defaults": {},
        "retryable": True,
    },
    "plan": {
        "label": "Build Action Tickets",
        "args": [],
        "method": "cmd_plan",
        "defaults": {},
        "retryable": True,
    },
    "expand": {
        "label": "Query Expansion",
        "args": ["--no-llm"],
        "method": "cmd_expand",
        "defaults": {"no_llm": False},
        "retryable": True,
    },
    "blueprint": {
        "label": "Build Blueprint",
        "args": [],
        "method": "cmd_blueprint",
        "defaults": {},
        "retryable": True,
    },
    "generate": {
        "label": "Generate Assets",
        "args": ["--asset", "--draft", "--draft-limit"],
        "method": "cmd_generate",
        "defaults": {"asset": None, "draft": False, "draft_limit": None},
        "retryable": True,
    },
    "lint": {
        "label": "Draft Risk Inspection",
        "args": [],
        "method": "cmd_lint",
        "defaults": {},
        "retryable": True,
    },
    "report": {
        "label": "Generate Diagnostic Report",
        "args": [],
        "method": "cmd_report",
        "defaults": {},
        "retryable": True,
    },
    "verify": {
        "label": "Closed-Loop Verify",
        "args": ["--no-recrawl"],
        "method": "cmd_verify",
        "defaults": {"no_recrawl": False},
        "retryable": True,
    },
    "deliver": {
        "label": "Compile Delivery Pack",
        "args": [],
        "method": "cmd_deliver",
        "defaults": {},
        "retryable": True,
    },
    "sample-sheet": {
        "label": "Export Manual Sample Sheet",
        "args": [],
        "method": "cmd_sheet",
        "defaults": {},
        "retryable": True,
    },
    "autopilot": {
        "label": "Autopilot Bootstrap",
        "args": ["--no-sample", "--limit", "--skip-llm"],
        "method": "cmd_autopilot",
        "defaults": {"no_sample": False, "limit": None, "skip_llm": False, "no_delivery": True},
        "retryable": True,
    },
    "serve": {
        "label": "Run Full Optimization Cycle",
        "args": ["--max-pages", "--limit", "--no-sample", "--draft", "--draft-limit"],
        "method": "cmd_serve",
        "defaults": {"max_pages": None, "limit": None, "no_sample": False, "draft": False, "draft_limit": None, "no_delivery": True},
        "retryable": True,
    },
}

# Keep the public action response compact while deriving all execution metadata
# from the same catalog.
PIPELINE_ACTIONS = {
    action: {"label": value["label"], "args": list(value["args"])}
    for action, value in ACTION_CATALOG.items()
}
ACTION_METHODS = {action: value["method"] for action, value in ACTION_CATALOG.items()}
ACTION_DEFAULTS = {action: dict(value["defaults"]) for action, value in ACTION_CATALOG.items()}
RETRYABLE_ACTIONS = frozenset(action for action, value in ACTION_CATALOG.items() if value["retryable"])

# Actions implemented by dedicated adapters rather than geo.cmd_* methods.
RETRYABLE_ACTIONS = RETRYABLE_ACTIONS | frozenset((
    "cycle", "archive", "archive_restore", "outreach_send",
))
