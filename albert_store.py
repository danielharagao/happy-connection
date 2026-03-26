from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fcntl

ALBERT_ALLOWED_STATES = {
    "created",
    "joining",
    "waiting_admit",
    "joined",
    "recording",
    "processing",
    "done",
    "failed",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AlbertStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.sessions_file = self.data_dir / "albert_sessions.json"
        self.jobs_file = self.data_dir / "albert_jobs.json"
        self.artifacts_dir = self.data_dir / "albert_artifacts"
        self.lock_file = self.data_dir / ".albert_store.lock"
        self.jobs_lock_file = self.data_dir / ".albert_jobs.lock"

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        if not self.sessions_file.exists():
            self.sessions_file.write_text("[]\n", encoding="utf-8")
        if not self.jobs_file.exists():
            self.jobs_file.write_text("[]\n", encoding="utf-8")
        for p in [self.lock_file, self.jobs_lock_file]:
            if not p.exists():
                p.write_text("lock\n", encoding="utf-8")

    @contextmanager
    def _locked_json(self, file_path: Path, lock_path: Path):
        self.ensure()
        with lock_path.open("r+", encoding="utf-8") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
            try:
                raw = file_path.read_text(encoding="utf-8") if file_path.exists() else "[]"
                data = json.loads(raw or "[]")
                if not isinstance(data, list):
                    data = []
                yield data
                file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            finally:
                fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._locked_json(self.sessions_file, self.lock_file) as items:
            return [x for x in items if isinstance(x, dict)]

    def add_session(self, item: dict[str, Any]) -> None:
        with self._locked_json(self.sessions_file, self.lock_file) as items:
            items.append(item)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        for x in self.list_sessions():
            if str(x.get("id") or "") == str(session_id):
                return x
        return None

    def timeline_push(self, session: dict[str, Any], status: str, detail: str) -> None:
        timeline = session.get("timeline") if isinstance(session.get("timeline"), list) else []
        timeline.append({"status": status, "detail": detail, "at": utc_now_iso()})
        session["timeline"] = timeline[-50:]

    def update_session(self, session_id: str, status: str, detail: str, extra: dict[str, Any] | None = None) -> bool:
        if status not in ALBERT_ALLOWED_STATES:
            return False
        with self._locked_json(self.sessions_file, self.lock_file) as items:
            found = next((x for x in items if str(x.get("id") or "") == str(session_id)), None)
            if not found:
                return False
            found["status"] = status
            found["updatedAt"] = utc_now_iso()
            self.timeline_push(found, status, detail)
            if isinstance(extra, dict):
                found.update(extra)
        return True

    def patch_session(self, session_id: str, extra: dict[str, Any]) -> bool:
        with self._locked_json(self.sessions_file, self.lock_file) as items:
            found = next((x for x in items if str(x.get("id") or "") == str(session_id)), None)
            if not found:
                return False
            found.update(extra)
            found["updatedAt"] = utc_now_iso()
        return True

    def enqueue_job(self, session_id: str, meet_link: str, run_at: str | None = None, trigger: str = "now") -> None:
        job = {
            "id": f"job-{os.urandom(4).hex()}",
            "sessionId": session_id,
            "meetLink": meet_link,
            "trigger": trigger,
            "runAt": run_at,
            "createdAt": utc_now_iso(),
            "status": "queued",
            "pickedAt": None,
            "error": "",
        }
        with self._locked_json(self.jobs_file, self.jobs_lock_file) as items:
            items.append(job)

    def pop_due_job(self) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        with self._locked_json(self.jobs_file, self.jobs_lock_file) as items:
            for idx, job in enumerate(items):
                if not isinstance(job, dict):
                    continue
                if str(job.get("status") or "queued") != "queued":
                    continue
                run_at = str(job.get("runAt") or "").strip()
                due = True
                if run_at:
                    try:
                        dt = datetime.fromisoformat(run_at.replace("Z", "+00:00")).astimezone(timezone.utc)
                        due = dt <= now
                    except Exception:
                        due = True
                if not due:
                    continue
                job["status"] = "picked"
                job["pickedAt"] = utc_now_iso()
                return dict(job)
        return None
