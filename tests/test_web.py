"""Phase 1 dashboard foundations."""


def test_health_and_pages(client):
    assert client.get("/health").json()["ok"]
    for url in ("/", "/create", "/registry", "/settings"):
        assert client.get(url).status_code == 200, url
    assert "not supported" in client.get("/registry").text


def test_create_project_through_dashboard(client):
    r = client.post("/create", data={"topic": "How to Remove Duplicate Rows from a Spreadsheet",
                                     "workflow_id": "sandbox-sheet.remove-duplicates"}, follow_redirects=False)
    assert r.status_code == 303
    pid = r.headers["location"].rsplit("/", 1)[1]
    page = client.get(f"/projects/{pid}")
    assert page.status_code == 200 and "Publishing blocked" in page.text
    assert client.get(f"/api/projects/{pid}/status").json()["status"] == "new"
    assert pid in client.get("/").text


def test_unsupported_workflow_rejected(client):
    r = client.post("/create", data={"topic": "Pivot table in Excel", "workflow_id": "excel-desktop.pivot"})
    assert r.status_code == 400


def test_settings_never_echo_secret(client, settings):
    client.post("/settings", data={"azure_key": "abc-SECRET-xyz", "azure_region": "westeurope", "max_chars": "5000"})
    html = client.get("/settings").text
    assert "abc-SECRET-xyz" not in html and "configured" in html and "westeurope" in html
    assert (settings.data_dir / "secrets.env").read_text().strip() == "AZURE_SPEECH_KEY=abc-SECRET-xyz"
    assert "abc-SECRET-xyz" not in (settings.data_dir / "preferences.json").read_text()


def test_media_path_traversal_blocked(client):
    assert client.get("/media/abc/../../secrets.env").status_code == 404
