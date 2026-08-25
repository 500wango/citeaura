"""Build and enforce the English-only SaaS delivery contract.

This module is the compatibility facade for the domain-specific delivery modules.
"""

from api.adapters.delivery_common import *  # noqa: F401,F403
from api.adapters.delivery_documents import *  # noqa: F401,F403
from api.adapters.delivery_generated_assets import *  # noqa: F401,F403
from api.adapters.delivery_package import *  # noqa: F401,F403

__all__ = tuple(name for name in globals() if not name.startswith("__"))
