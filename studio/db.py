"""SQLite persistence: projects, per-stage status, event log and TTS usage."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path

from .contracts import ProjectRequest, now_iso

STAGES = ["plan", "demonstrate", "script", "narrate", "render", "qc"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    request TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS stages (
    project_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending|running|done|failed
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (project_id, stage)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    stage TEXT,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,          -- 'active' (seconds of human attention) | 'intervention'
    seconds REAL NOT NULL DEFAULT 0,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    provider TEXT NOT NULL,
    characters INTEGER NOT NULL,
    cached INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def _query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # projects --------------------------------------------------------------
    def create_project(self, title: str, request: ProjectRequest) -> str:
        pid = uuid.uuid4().hex[:12]
        ts = now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO projects (id,title,created_at,updated_at,request,state) VALUES (?,?,?,?,?,?)",
                (pid, title, ts, ts, request.model_dump_json(), "{}"),
            )
            for s in STAGES:
                self._conn.execute("INSERT INTO stages (project_id, stage) VALUES (?,?)", (pid, s))
            self._conn.commit()
        return pid

    def get_project(self, pid: str) -> dict | None:
        rows = self._query("SELECT * FROM projects WHERE id=?", (pid,))
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r["id"],
            "title": r["title"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "request": ProjectRequest.model_validate_json(r["request"]),
            "state": json.loads(r["state"]),
            "stages": self.get_stages(pid),
        }

    def list_projects(self) -> list[dict]:
        rows = self._query("SELECT id FROM projects ORDER BY created_at DESC")
        return [self.get_project(r["id"]) for r in rows]

    def update_request(self, pid: str, request: ProjectRequest) -> None:
        self._exec("UPDATE projects SET request=?, updated_at=? WHERE id=?", (request.model_dump_json(), now_iso(), pid))

    def set_state(self, pid: str, key: str, value) -> None:
        """Store one stage artifact (a pydantic model, dict or None) in project state."""
        with self._lock:
            row = self._conn.execute("SELECT state FROM projects WHERE id=?", (pid,)).fetchone()
            state = json.loads(row["state"])
            if value is None:
                state.pop(key, None)
            else:
                state[key] = json.loads(value.model_dump_json()) if hasattr(value, "model_dump_json") else value
            self._conn.execute("UPDATE projects SET state=?, updated_at=? WHERE id=?", (json.dumps(state), now_iso(), pid))
            self._conn.commit()

    # stages ----------------------------------------------------------------
    def get_stages(self, pid: str) -> dict[str, dict]:
        rows = self._query("SELECT * FROM stages WHERE project_id=?", (pid,))
        by = {r["stage"]: dict(r) for r in rows}
        return {s: by[s] for s in STAGES if s in by}

    def set_stage(self, pid: str, stage: str, status: str, error: str | None = None) -> None:
        ts = now_iso()
        if status == "running":
            self._exec("UPDATE stages SET status=?, error=NULL, started_at=?, finished_at=NULL WHERE project_id=? AND stage=?", (status, ts, pid, stage))
        elif status == "pending":
            self._exec("UPDATE stages SET status=?, error=NULL, started_at=NULL, finished_at=NULL WHERE project_id=? AND stage=?", (status, pid, stage))
        else:
            self._exec("UPDATE stages SET status=?, error=?, finished_at=? WHERE project_id=? AND stage=?", (status, error, ts, pid, stage))

    # events ----------------------------------------------------------------
    def log(self, pid: str, message: str, level: str = "info", stage: str | None = None) -> None:
        self._exec("INSERT INTO events (project_id, ts, level, stage, message) VALUES (?,?,?,?,?)", (pid, now_iso(), level, stage, message))

    def events(self, pid: str, limit: int = 200) -> list[dict]:
        rows = self._query("SELECT * FROM events WHERE project_id=? ORDER BY id DESC LIMIT ?", (pid, limit))
        return [dict(r) for r in rows]

    # human activity (automation measurement) --------------------------------
    def record_active(self, pid: str, seconds: float) -> None:
        self._exec("INSERT INTO activity (project_id, ts, kind, seconds) VALUES (?,?,?,?)",
                   (pid, now_iso(), "active", max(0.0, min(seconds, 60.0))))

    def record_intervention(self, pid: str, detail: str) -> None:
        self._exec("INSERT INTO activity (project_id, ts, kind, seconds, detail) VALUES (?,?,?,?,?)",
                   (pid, now_iso(), "intervention", 0, detail))

    def activity(self, pid: str) -> dict:
        active = self._query("SELECT COALESCE(SUM(seconds),0) AS s FROM activity WHERE project_id=? AND kind='active'", (pid,))
        inter = self._query("SELECT detail, COUNT(*) AS n FROM activity WHERE project_id=? AND kind='intervention' "
                            "GROUP BY detail ORDER BY n DESC", (pid,))
        return {"active_seconds": float(active[0]["s"]), "interventions": {r["detail"]: r["n"] for r in inter}}

    def recover_interrupted(self) -> list[tuple[str, str]]:
        """Stages left 'running' by a crash/restart are marked failed so they can be retried."""
        rows = self._query("SELECT project_id, stage FROM stages WHERE status='running'")
        for r in rows:
            self.set_stage(r["project_id"], r["stage"], "failed", "Interrupted: the app stopped while this stage was running. Retry it.")
            self.log(r["project_id"], f"Stage '{r['stage']}' was interrupted by an app restart", level="warning", stage=r["stage"])
        return [(r["project_id"], r["stage"]) for r in rows]

    # usage -----------------------------------------------------------------
    def record_usage(self, pid: str, provider: str, characters: int, cached: bool) -> None:
        self._exec("INSERT INTO usage (project_id, ts, provider, characters, cached) VALUES (?,?,?,?,?)", (pid, now_iso(), provider, characters, int(cached)))

    def billed_characters(self, pid: str, provider: str) -> int:
        rows = self._query("SELECT COALESCE(SUM(characters),0) AS n FROM usage WHERE project_id=? AND provider=? AND cached=0", (pid, provider))
        return int(rows[0]["n"])
