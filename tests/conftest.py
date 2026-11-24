import pytest

from studio.config import load_settings


@pytest.fixture
def settings(tmp_path):
    return load_settings({"STUDIO_DATA_DIR": str(tmp_path / "data"), "STUDIO_MODE": "development"})


@pytest.fixture
def client(settings):
    from fastapi.testclient import TestClient
    from studio.web.app import create_app
    app = create_app(settings)
    with TestClient(app) as c:
        c.app_state = app.state
        yield c
