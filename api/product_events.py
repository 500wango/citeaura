"""平台产品事件追加记录。"""

import json

from api.models import ProductEvent


def record_product_event(db, name, tenant_id=None, user_id=None, anonymous_id=None, country_code=None, properties=None):
    event = ProductEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        anonymous_id=anonymous_id,
        name=name,
        country_code=country_code,
        properties=json.dumps(properties or {}, ensure_ascii=False, sort_keys=True),
    )
    db.add(event)
    return event
