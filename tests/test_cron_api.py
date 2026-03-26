from pathlib import Path

import app as cockpit_app


def _setup_tmp_store(tmp_path: Path):
    cockpit_app.DATA_DIR = tmp_path
    cockpit_app.CRON_JOBS_FILE = tmp_path / "cron_jobs.json"
    cockpit_app.PERMISSIONS_FILE = tmp_path / "permissions_matrix.json"
    cockpit_app.OFFICE_LAYOUT_FILE = tmp_path / "office_layout.json"
    cockpit_app.AGENT_PROFILES_FILE = tmp_path / "agent_profiles.json"
    cockpit_app.KANBAN_TASKS_FILE = tmp_path / "kanban_tasks.json"


def test_add_list_delete_job(tmp_path):
    _setup_tmp_store(tmp_path)
    client = cockpit_app.app.test_client()

    resp = client.post(
        "/api/cron/jobs",
        json={
            "name": "Test Job",
            "schedule": "*/5 * * * *",
            "command": "echo hello",
            "enabled": True,
        },
    )
    assert resp.status_code == 201
    job = resp.get_json()
    assert job["id"] == "job-1"

    resp = client.get("/api/cron/jobs")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "Test Job"

    resp = client.delete("/api/cron/jobs/job-1")
    assert resp.status_code == 200

    resp = client.get("/api/cron/jobs")
    assert resp.status_code == 200
    assert resp.get_json()["items"] == []


def test_run_job_updates_execution_fields(tmp_path):
    _setup_tmp_store(tmp_path)
    client = cockpit_app.app.test_client()

    resp = client.post(
        "/api/cron/jobs",
        json={
            "name": "Run Job",
            "schedule": "0 * * * *",
            "command": "echo run-ok",
            "enabled": True,
        },
    )
    assert resp.status_code == 201

    run_resp = client.post("/api/cron/jobs/job-1/run", json={"confirm": True})
    assert run_resp.status_code == 200
    run_data = run_resp.get_json()
    assert run_data["exitCode"] == 0
    assert run_data["status"] == "success"
    assert run_data["startedAt"] is not None
    assert run_data["finishedAt"] is not None
    assert run_data["durationMs"] >= 0
    assert "run-ok" in run_data["output"]

    list_resp = client.get("/api/cron/jobs")
    job = list_resp.get_json()["items"][0]
    assert job["lastRunAt"] is not None
    assert job["lastExitCode"] == 0
    assert "run-ok" in job["lastOutput"]
    assert len(job["runHistory"]) == 1
    assert job["runHistory"][0]["status"] == "success"


def test_run_history_endpoint_and_truncation(tmp_path):
    _setup_tmp_store(tmp_path)
    client = cockpit_app.app.test_client()

    create_resp = client.post(
        "/api/cron/jobs",
        json={
            "name": "Long Output",
            "schedule": "*/10 * * * *",
            "command": "python3 -c \"print('x'*400)\"",
            "enabled": True,
        },
    )
    assert create_resp.status_code == 201

    run_resp = client.post("/api/cron/jobs/job-1/run", json={"confirm": True})
    assert run_resp.status_code == 200
    assert run_resp.get_json()["outputTruncated"] is True

    hist_resp = client.get("/api/cron/jobs/job-1/history?limit=3")
    assert hist_resp.status_code == 200
    items = hist_resp.get_json()["items"]
    assert len(items) == 1
    assert items[0]["outputTruncated"] is True
    assert len(items[0]["outputSummary"]) <= cockpit_app.OUTPUT_SUMMARY_CHARS


def test_validation_errors(tmp_path):
    _setup_tmp_store(tmp_path)
    client = cockpit_app.app.test_client()

    resp = client.post("/api/cron/jobs", json={"name": "", "schedule": "", "command": ""})
    assert resp.status_code == 400
    assert "required" in resp.get_json()["error"]


def test_toggle_enabled_and_manual_run_confirmation(tmp_path):
    _setup_tmp_store(tmp_path)
    client = cockpit_app.app.test_client()

    create_resp = client.post(
        "/api/cron/jobs",
        json={
            "name": "Toggle Job",
            "schedule": "*/10 * * * *",
            "command": "echo toggle",
            "enabled": True,
        },
    )
    assert create_resp.status_code == 201

    toggle_resp = client.patch("/api/cron/jobs/job-1/enabled", json={"enabled": False})
    assert toggle_resp.status_code == 200
    assert toggle_resp.get_json()["enabled"] is False

    run_without_confirm = client.post("/api/cron/jobs/job-1/run")
    assert run_without_confirm.status_code == 400
    assert "confirm=true" in run_without_confirm.get_json()["error"]

    run_while_disabled = client.post("/api/cron/jobs/job-1/run", json={"confirm": True})
    assert run_while_disabled.status_code == 409
    assert "disabled" in run_while_disabled.get_json()["error"]
