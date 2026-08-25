"""项目 API 路由兼容 facade。

按领域实现位于生命周期、采样、工单和交付子路由模块。
"""

from fastapi import APIRouter, status

from api.projects.project_route_support import *  # noqa: F401,F403
from api.projects.lifecycle_routes import *  # noqa: F401,F403
from api.projects.lifecycle_routes import router as lifecycle_router
from api.projects.sampling_routes import *  # noqa: F401,F403
from api.projects.sampling_routes import router as sampling_router
from api.projects.ticket_routes import *  # noqa: F401,F403
from api.projects.ticket_routes import router as ticket_router
from api.projects.delivery_routes import *  # noqa: F401,F403
from api.projects.delivery_routes import router as delivery_router

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])
router.add_api_route(
    "",
    create_project,
    methods=["POST"],
    status_code=status.HTTP_202_ACCEPTED,
)
router.add_api_route("", list_projects, methods=["GET"])
router.include_router(lifecycle_router)
router.include_router(sampling_router)
router.include_router(ticket_router)
router.include_router(delivery_router)

__all__ = tuple(name for name in globals() if not name.startswith("__"))
