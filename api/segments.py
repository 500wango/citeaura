"""客群归类：把租户分成 solo/brand 与 agency/consultant 两类。

漏斗必须按客群拆分才有意义——个人品牌和代理商的首次价值路径不同。
注册时可显式声明；未声明时按可观察行为推断，而不是猜测邮箱域名。
"""

SOLO = "solo"
AGENCY = "agency"
UNKNOWN = "unknown"

SEGMENTS = (SOLO, AGENCY, UNKNOWN)

# 代理商在注册表单里的自述选项，以及等价的营销活动标签。
_AGENCY_DECLARATIONS = frozenset((
    "agency", "consultant", "consultancy", "freelancer",
    "reseller", "partner", "white_label",
))
_SOLO_DECLARATIONS = frozenset((
    "solo", "brand", "in_house", "inhouse", "startup", "founder",
))

# 超过这个项目数的工作区在服务多个客户，按代理商统计。
AGENCY_PROJECT_THRESHOLD = 3


def normalize(value):
    """把注册表单或活动标签里的自述归到已知客群，无法归类时返回 unknown。"""
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")[:32]
    if text in _AGENCY_DECLARATIONS:
        return AGENCY
    if text in _SOLO_DECLARATIONS:
        return SOLO
    return UNKNOWN


def from_signup(declared=None, acquisition_source=None):
    """注册时归类：显式自述优先，其次看获客来源标签。"""
    segment = normalize(declared)
    if segment != UNKNOWN:
        return segment
    return normalize(acquisition_source)


def infer(plan, project_count, declared_segment=UNKNOWN):
    """已声明的客群不被行为覆盖；未声明时按套餐和项目数推断。"""
    if declared_segment in (SOLO, AGENCY):
        return declared_segment
    if plan in ("agency", "enterprise"):
        return AGENCY
    if (project_count or 0) > AGENCY_PROJECT_THRESHOLD:
        return AGENCY
    if plan in ("trial", "starter", "pro") and project_count:
        return SOLO
    return UNKNOWN
