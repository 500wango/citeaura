"""可信边缘请求的国家归因。"""

import re

from api import config


COUNTRY_CODE_PATTERN = re.compile(r"^[A-Z]{2}$")


def normalize_country_code(value):
    code = str(value or "").strip().upper()
    if not COUNTRY_CODE_PATTERN.fullmatch(code) or code == "XX":
        return None
    return code


def request_country_code(request):
    """仅在显式信任 Cloudflare 代理时读取边缘国家码。"""
    if not config.trust_cloudflare_country_header():
        return None
    return normalize_country_code(request.headers.get("CF-IPCountry"))
