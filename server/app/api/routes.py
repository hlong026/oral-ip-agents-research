"""业务路由注册表，集中维护公开端与管理端的挂载边界。"""

from fastapi import FastAPI

from app.modules.activation.router import admin_router as activation_admin_router
from app.modules.activation.router import router as activation_router
from app.modules.activation.router import subscription_router
from app.modules.admin.router import router as admin_router
from app.modules.auth.router import admin_router as auth_admin_router
from app.modules.auth.router import router as auth_router
from app.modules.avatar.router import router as avatar_router
from app.modules.billing.router import router as billing_router
from app.modules.catalog.router import admin_router as catalog_admin_router
from app.modules.catalog.router import router as catalog_router
from app.modules.content.router import router as content_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.im.router import admin_router as im_admin_router
from app.modules.im.router import router as im_router
from app.modules.ipasset.router import router as ipasset_router
from app.modules.notify.router import router as notify_router
from app.modules.notify.ws import ws_router
from app.modules.pipeline.router import router as pipeline_router
from app.modules.publish.router import router as publish_router
from app.modules.settings.router import provider_router
from app.modules.voice.router import router as voice_router
from app.modules.webhook.router import router as webhook_router


def register_business_routes(app: FastAPI, *, api_prefix: str, im_enabled: bool) -> None:
    """挂载所有业务路由；main 只保留应用装配职责。"""
    user_routers = (
        auth_router,
        activation_router,
        subscription_router,
        billing_router,
        catalog_router,
        ipasset_router,
        voice_router,
        avatar_router,
        content_router,
        pipeline_router,
        publish_router,
        notify_router,
        dashboard_router,
        webhook_router,
    )
    for router in user_routers:
        app.include_router(router, prefix=api_prefix)
    if im_enabled:
        app.include_router(im_router, prefix=api_prefix)

    admin_routers = (
        auth_admin_router,
        activation_admin_router,
        catalog_admin_router,
        provider_router,
        admin_router,
        im_admin_router,
    )
    for router in admin_routers:
        app.include_router(router, prefix="/api/admin/v1")
    app.include_router(ws_router)
