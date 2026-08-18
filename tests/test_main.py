import pytest
from fastapi.testclient import TestClient


def test_app_metadata():
    from app.main import app

    assert app.title == "Flight API"
    assert app.version == "1.0.0"


def test_flight_router_is_included():
    from app.main import app

    paths: set[str] = set()
    for route in app.routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            paths.update(r.path for r in original_router.routes)
        else:
            path = getattr(route, "path", None)
            if path is not None:
                paths.add(path)

    assert "/flight/search" in paths


def test_lifespan_calls_bootstrap_startup_then_shutdown(monkeypatch):
    import app.main as main_module

    calls = []

    class FakeBootstrapApplication:
        async def startup(self, app):
            assert app is main_module.app
            calls.append("startup")

        async def shutdown(self):
            calls.append("shutdown")

    monkeypatch.setattr(main_module, "BootstrapApplication", FakeBootstrapApplication)

    with TestClient(main_module.app):
        assert calls == ["startup"]

    assert calls == ["startup", "shutdown"]


def test_lifespan_configures_logging_before_startup(monkeypatch):
    import app.main as main_module

    calls = []

    monkeypatch.setattr(
        main_module, "configure_logging", lambda: calls.append("configure_logging")
    )

    class FakeBootstrapApplication:
        async def startup(self, app):
            calls.append("startup")

        async def shutdown(self):
            calls.append("shutdown")

    monkeypatch.setattr(main_module, "BootstrapApplication", FakeBootstrapApplication)

    with TestClient(main_module.app):
        pass

    assert calls == ["configure_logging", "startup", "shutdown"]


def test_lifespan_propagates_startup_exception(monkeypatch):
    import app.main as main_module

    class FailingBootstrapApplication:
        async def startup(self, app):
            raise RuntimeError("boom")

        async def shutdown(self):
            pytest.fail("shutdown should not be called when startup fails")

    monkeypatch.setattr(
        main_module, "BootstrapApplication", FailingBootstrapApplication
    )

    with pytest.raises(RuntimeError, match="boom"), TestClient(main_module.app):
        pass


def test_lifespan_propagates_shutdown_exception(monkeypatch):
    import app.main as main_module

    class FailingShutdownBootstrapApplication:
        async def startup(self, app):
            pass

        async def shutdown(self):
            raise RuntimeError("shutdown failed")

    monkeypatch.setattr(
        main_module, "BootstrapApplication", FailingShutdownBootstrapApplication
    )

    with pytest.raises(RuntimeError, match="shutdown failed"), TestClient(
        main_module.app
    ):
        pass
