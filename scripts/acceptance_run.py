"""LIVE end-to-end acceptance run (Master prompt §14) — drives the real dashboard in a browser.

Requires real Azure AI Speech credentials (AZURE_SPEECH_KEY / AZURE_SPEECH_REGION) and runs
the app in production mode, so no development voice can be used. Nothing is mocked.

    python scripts/acceptance_run.py --out acceptance-output

Steps: create project via the Create form -> pipeline (plan, real Playwright demonstration,
verification, script, Azure narration, render, QC) -> review pages -> approve narration ->
final approval -> export -> download and inspect the export ZIP.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="acceptance-output")
    ap.add_argument("--resolution", default="1920x1080")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not os.environ.get("AZURE_SPEECH_KEY") or not os.environ.get("AZURE_SPEECH_REGION"):
        print("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION are required for the live acceptance run.")
        return 2

    port = free_port()
    env = {**os.environ, "STUDIO_MODE": "production", "STUDIO_DATA_DIR": str(out / "data"),
           "STUDIO_PORT": str(port), "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    server = subprocess.Popen([sys.executable, "-m", "studio"], cwd=ROOT, env=env,
                              stdout=open(out / "server.log", "w"), stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    report: dict = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "steps": []}

    def step(name, ok, detail=""):
        report["steps"].append({"step": name, "ok": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")
        if not ok:
            raise SystemExit(1)

    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(60):
            try:
                opener.open(base + "/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1366, "height": 900})
            shot = lambda name: page.screenshot(path=str(out / f"{name}.png"), full_page=True)

            # 1-2. create project, select target software environment
            page.goto(base + "/create")
            page.fill("#topic", "How to Remove Duplicate Rows from a Spreadsheet")
            page.select_option("#workflow_id", "sandbox-sheet.remove-duplicates")
            page.select_option("#voice", "en-US-AndrewNeural")
            page.select_option("#difficulty", "beginner")
            page.select_option("#resolution", args.resolution)
            shot("01-create")
            page.click("button[type=submit]")
            page.wait_for_url("**/projects/*")
            pid = page.url.rstrip("/").split("/")[-1]
            step("Project created through dashboard", True, pid)

            # 3-10. pipeline
            deadline = time.time() + 900
            while time.time() < deadline:
                st = json.load(opener.open(f"{base}/api/projects/{pid}/status"))
                if not st["running"] and st["status"] != "running":
                    break
                time.sleep(2)
            stages = {k: v["status"] for k, v in st["stages"].items()}
            step("All pipeline stages completed", all(v == "done" for v in stages.values()),
                 json.dumps({k: (v["status"], v["error"]) for k, v in st["stages"].items()}))
            page.goto(f"{base}/projects/{pid}")
            shot("02-project-after-pipeline")
            html = page.content()
            step("Plan generated", "Outline" in html)
            step("Real actions executed and verified", "Verification <b>PASSED</b>" in html)
            step("Demonstration footage recorded", page.locator("#demo video").count() == 1)
            step("Narration produced by Azure Neural TTS", "azure-neural" in html and "development only" not in html)
            step("Tutorial video rendered", page.locator("#final-video").count() == 1)
            step("Captions and publishing metadata produced", "captions burned in" in html and "Chapters" in html)
            step("Verification and QC reports displayed", "Environment record" in html and "Quality control" in html)

            # 11-12. human review & approval
            page.click("text=I listened to the narration")
            page.wait_for_load_state()
            step("Narration approved by human", "Narration approved at" in page.content())
            shot("03-narration-approved")
            if page.locator("text=I acknowledge the software version is unknown").count():
                page.click("text=I acknowledge the software version is unknown")
            page.check("input[name=confirm]")
            page.click("text=Grant final approval")
            page.wait_for_load_state()
            step("Final human approval granted", "Final approval granted" in page.content())

            # 13. export
            page.click("text=Build export package")
            page.wait_for_load_state()
            shot("04-exported")
            href = page.locator("a:has-text('Download export')").get_attribute("href")
            zpath = out / "export.zip"
            zpath.write_bytes(opener.open(base + href).read())
            with zipfile.ZipFile(zpath) as z:
                names = set(z.namelist())
                z.extractall(out / "export")
            need = {"tutorial.mp4", "captions.srt", "narration.m4a", "youtube_metadata.json", "qc_report.json",
                    "version_verification.json", "approval.json"}
            step("Export package complete", need <= names, ", ".join(sorted(names)))
            approval = json.loads((out / "export" / "approval.json").read_text())
            step("Export records production narration provider", approval["narration_provider"] == "azure-neural")
            browser.close()
        report["result"] = "PASSED"
        return 0
    except SystemExit:
        report["result"] = "FAILED"
        return 1
    finally:
        (out / "acceptance_report.json").write_text(json.dumps(report, indent=2))
        server.terminate()
        server.wait(10)


if __name__ == "__main__":
    sys.exit(main())
