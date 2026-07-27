"""应用组合回归：路由拆分后仍由入口完整挂载。"""

from collections.abc import Iterable

from app.main import app


def _paths(routes: Iterable[object], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for route in routes:
        path = getattr(route, "path", None)
        if path:
            paths.add(f"{prefix}{path}")
        nested_routes = getattr(route, "routes", None)
        if nested_routes:
            paths.update(_paths(nested_routes, prefix))
        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        if original_router and include_context:
            paths.update(_paths(original_router.routes, f"{prefix}{include_context.prefix}"))
    return paths


def test_app_composes_health_media_and_business_routes() -> None:
    paths = _paths(app.routes)

    assert {"/healthz", "/readyz", "/media/{key:path}"} <= paths
    assert any(path.startswith("/api/v1/") for path in paths)
    assert any(path.startswith("/api/admin/v1/") for path in paths)
    assert any(path.startswith("/ws/") for path in paths)
