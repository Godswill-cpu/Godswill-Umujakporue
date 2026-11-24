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


def test_unmatched_topic_is_refused_not_substituted(client):
    """A topic without a tested recipe must never produce a different tutorial under the user's title."""
    before = len(client.app_state.db.list_projects())
    r = client.post("/create", data={"topic": "How to run a CVS file on JupyterLab", "workflow_id": "jupyterlab.first-notebook"})
    assert r.status_code == 200 and "No tested recipe for this topic yet" in r.text
    assert "/create?mode=manual&topic=How%20to%20run%20a%20CVS%20file%20on%20JupyterLab" in r.text
    assert len(client.app_state.db.list_projects()) == before
    # manual-capture link prefills the form
    form = client.get("/create?mode=manual&topic=How%20to%20run%20a%20CVS%20file%20on%20JupyterLab").text
    assert 'value="How to run a CVS file on JupyterLab"' in form and 'value="manual" checked' in form


def test_matching_topic_variants_accepted(client):
    from studio.planning import topic_matches_workflow as m
    t = "How to Create and Run Your First Notebook in JupyterLab"
    assert m(t, t) and m("create and run your first notebook in JupyterLab - tutorial", t)
    assert not m("How to run a CSV file on JupyterLab", t) and not m("", t)
    r = client.post("/create", data={"topic": "", "workflow_id": "jupyterlab.first-notebook"}, follow_redirects=False)
    assert r.status_code == 303
