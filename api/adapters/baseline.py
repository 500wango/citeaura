"""规范模型生成的项目底座元数据。"""

import re

from api.adapters.engine import geolib
from api.adapters import global_scope


_CJK = re.compile(r"[一-鿿]")
_UNCERTAINTY_RULES = (
    (re.compile(r"成立|创立|创建|创办"), "Founding date and company history"),
    (re.compile(r"工商|运营主体|法律主体|公司主体|注册地|注册信息"),
     "Legal entity, registration jurisdiction, and company registration details"),
    (re.compile(r"客户|案例|效果|业绩|成功案例"),
     "Named customers, customer count, and verified outcome case studies"),
    (re.compile(r"AI.*(?:提供商|模型|引擎)|支持.*(?:AI|模型|引擎)|测量范围|采样范围|平台范围", re.I),
     "Supported AI providers, models, and measurement coverage"),
    (re.compile(r"套餐|定价|价格|权益|收费"),
     "Plan pricing, entitlements, and intended customer segments"),
    (re.compile(r"创始人|管理层|核心团队|团队成员"), "Founders and leadership team"),
    (re.compile(r"联系|地址|邮箱|电话"), "Official contact details"),
    (re.compile(r"资质|认证|奖项"), "Certifications and awards"),
    (re.compile(r"隐私|合规|安全"), "Security, privacy, and compliance claims"),
    (re.compile(r"目标用户|适用对象|适用范围"), "Target customers and usage boundaries"),
    (re.compile(r"产品|功能|能力|服务范围"), "Verified product capabilities and service scope"),
    (re.compile(r"数据|指标|规模|用户数量"), "Verified operating metrics and scale"),
)


def normalize_uncertainty(value):
    """无需再次调用模型，把待核验项映射为稳定英文。"""
    text = " ".join(str(value or "").split())
    if not text or not _CJK.search(text):
        return text
    for pattern, replacement in _UNCERTAINTY_RULES:
        if pattern.search(text):
            return replacement
    return "Additional material brand information requiring manual verification"


def normalize_uncertainties(values):
    normalized = []
    for value in values if isinstance(values, list) else []:
        item = normalize_uncertainty(value)
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def normalize_bootstrap_metadata(project_slug):
    """保存英文待核验项，并把底座收敛到国际市场。"""
    with geolib.project_lock(project_slug):
        original = geolib.load_config(project_slug)
        config = global_scope.normalize_config_data(original)
        bootstrap = config.get("bootstrap")
        if not isinstance(bootstrap, dict) or not isinstance(bootstrap.get("uncertain"), list):
            if config != original:
                geolib.save_config(project_slug, config)
            return config
        normalized = normalize_uncertainties(bootstrap["uncertain"])
        if normalized != bootstrap["uncertain"] or config != original:
            bootstrap["uncertain"] = normalized
            geolib.save_config(project_slug, config)
        return config
