"""Manual-capture fallback. Fixture videos are synthetic FFmpeg test patterns
(explicitly labeled test media), standing in for a user's own recording."""
import time
from pathlib import Path

import pytest

from studio.manual_capture import ManualCaptureError, parse_steps, steps_to_text
from studio.media import probe, run_ffmpeg


def fixture_recording(path: Path, seconds=12, size="640x480"):
    run_ffmpeg(["-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])
    return path


def test_parse_steps():
    steps = parse_steps("# comment\n0:02 | Open the file | Open your workbook.\n1:05.5 | Insert | | Table inserted")
    assert [(s.start, s.title, s.narration, s.expected) for s in steps] == [
        (2.0, "Open the file", "Open your workbook.", ""), (65.5, "Insert", "", "Table inserted")]
    assert parse_steps(steps_to_text(steps)) == steps
    for bad in ("", "abc | x", "0:05 | a\n0:03 | b", "0:01"):
        with pytest.raises(ManualCaptureError):
            parse_steps(bad)


def create_manual(client):
    r = client.post("/create", data={"topic": "How to Insert a Table in Example Writer", "capture_mode": "manual",
                                     "manual_app_name": "Example Writer", "resolution": "1280x720",
                                     "allow_dev_tts": "true", "start": "true"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r.headers["location"].rsplit("/", 1)[1]


def wait_idle(client, pid, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        s = client.get(f"/api/projects/{pid}/status").json()
        if not s["running"] and s["status"] != "running":
            return s
        time.sleep(0.5)
    raise TimeoutError


def test_manual_capture_end_to_end_is_labelled_human_attested(client, tmp_path):
    pid = create_manual(client)
    wait_idle(client, pid)
    assert client.app_state.db.get_stages(pid)["plan"]["status"] == "done"
    # without a recording the demonstration stage fails clearly
    client.post(f"/projects/{pid}/run")
    s = wait_idle(client, pid)
    assert "Waiting for manual capture" in s["stages"]["demonstrate"]["error"]

    rec = fixture_recording(tmp_path / "my-recording.mp4")
    steps = "0:01 | Open the Insert menu | Open the Insert menu.\n0:05 | Choose Table | Choose Table and set two columns."
    # attesting before upload is refused
    assert client.post(f"/projects/{pid}/manual-capture", data={"steps": steps, "attest": "true"}).status_code == 400
    with open(rec, "rb") as f:
        r = client.post(f"/projects/{pid}/manual-capture", files={"recording": ("my-recording.mp4", f, "video/mp4")},
                        data={"steps": steps, "os_name": "Windows 11", "attest": "true"}, follow_redirects=False)
    assert r.status_code == 303
    s = wait_idle(client, pid)
    assert all(v["status"] == "done" for v in s["stages"].values()), s
    st = client.app_state.db.get_project(pid)["state"]
    v = st["execution"]["verification"]
    assert v["method"] == "human_attested" and v["outcome"] == "passed"
    assert v["environment"]["app_version"] is None and v["environment"]["os"] == "Windows 11"
    assert v["environment"]["browser_name"] is None  # nothing invented
    assert [x["text"] for x in st["script"]["segments"][1:3]] == ["Open the Insert menu.", "Choose Table and set two columns."]
    qc_ids = {i["id"]: i for i in st["qc"]["items"]}
    assert qc_ids["verification-human"]["automated"] is False
    assert qc_ids["media-licensing"]["severity"] == "warning"
    info = probe(Path(st["render"]["video_path"]))
    vs = next(x for x in info["streams"] if x["codec_type"] == "video")
    assert (vs["width"], vs["height"]) == (1280, 720)  # 4:3 recording padded, not stretched
    page = client.get(f"/projects/{pid}").text
    assert "human attestation" in page
    # still blocked: dev voice + unknown version not acknowledged
    assert client.post(f"/projects/{pid}/approve", data={"confirm": "true"}).status_code == 409

    # changing the steps clears the attestation and invalidates downstream stages
    client.post(f"/projects/{pid}/manual-capture", data={"steps": steps + "\n0:09 | Done | Done.", "os_name": "Windows 11"})
    p = client.app_state.db.get_project(pid)
    assert "attested_at" not in p["state"]["manual_capture"]
    assert p["stages"]["demonstrate"]["status"] == "pending" and "render" not in p["state"]


def test_manual_upload_rejects_non_video(client, tmp_path):
    pid = create_manual(client)
    wait_idle(client, pid)
    bad = tmp_path / "notes.mp4"
    bad.write_text("not a video")
    with open(bad, "rb") as f:
        r = client.post(f"/projects/{pid}/manual-capture", files={"recording": ("notes.mp4", f, "video/mp4")})
    assert r.status_code == 400 and "not a readable video" in r.text
    with open(bad, "rb") as f:
        r = client.post(f"/projects/{pid}/manual-capture", files={"recording": ("x.exe", f, "application/octet-stream")})
    assert r.status_code == 400


def test_manual_mode_requires_app_name(client):
    r = client.post("/create", data={"topic": "x", "capture_mode": "manual"})
    assert r.status_code == 400
