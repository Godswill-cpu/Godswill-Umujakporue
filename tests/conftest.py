import pytest

from studio.config import load_settings


ISOLATED_VARS = ("AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION", "AZURE_SPEECH_TRANSPORT", "ANTHROPIC_API_KEY",
                 "STUDIO_MODE", "STUDIO_LLM_PROVIDER", "STUDIO_DATA_DIR")


@pytest.fixture(autouse=True)
def _isolate_from_host_credentials(request, monkeypatch):
    """Tests never pick up the developer's real keys, except tests explicitly marked as live."""
    if request.node.get_closest_marker("azure_live"):
        return
    for var in ISOLATED_VARS:
        monkeypatch.delenv(var, raising=False)


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
