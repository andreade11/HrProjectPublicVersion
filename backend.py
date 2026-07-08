from __future__ import annotations

import ast
import datetime as dt
import importlib
import json
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, request, send_file
from env_loader import load_env_file
from language_context import detect_language_from_url, normalize_language
from retrieval_sources import delete_source, load_sources, reset_running_sources_to_idle, upsert_source

load_env_file()


app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
JOBS_DIR = BASE_DIR / "FichesJobs"
CANDIDATES_DIR = BASE_DIR / "FichesCandidats"
STATE_PATH = BASE_DIR / "backend_state.json"
HEADHUNTER_DOMAIN_MARKERS = ("academicwork", "michaelpage", "finders")
DEFAULT_MAIN_MODE = "Yes"
DEFAULT_LISTING_PAGES = 1
LISTING_SCHEDULE_OPTIONS = {1, 2, 3}

STATE_LOCK = threading.Lock()
STATE: dict[str, Any] = {}
LISTING_ACTIVE = False
LISTING_STOP_EVENT = threading.Event()
SCHEDULER_THREAD: threading.Thread | None = None
SCHEDULER_STOP_EVENT = threading.Event()
APPLICATION_RUNS_LOCK = threading.Lock()
ACTIVE_APPLICATION_RUNS: set[str] = set()
APPLICATION_PAUSE_EVENTS: dict[str, threading.Event] = {}
APPLICATION_STOP_EVENTS: dict[str, threading.Event] = {}
APPLICATION_TIMEOUT_SECONDS = 300


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def default_state() -> dict[str, Any]:
    return {
        "application_runs": [],
        "listing_runs": [],
        "scheduler": {
            "enabled": False,
            "interval_hours": None,
            "pages": DEFAULT_LISTING_PAGES,
            "source_ids": ["jobup_main"],
            "next_run_at": None,
            "last_run_at": None,
            "status": "idle",
        },
    }


def _normalize_stale_application_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw_run in runs:
        if not isinstance(raw_run, dict):
            continue
        run = dict(raw_run)
        status = str(run.get("status") or "").strip().lower()
        if status in {"running", "paused", "pausing"}:
            run["status"] = "completed_with_errors"
            run["finished_at"] = run.get("finished_at") or utc_now_iso()
            run["error"] = str(run.get("error") or "Backend restarted before automation finished")
            items = []
            for raw_item in run.get("items", []):
                if not isinstance(raw_item, dict):
                    continue
                item = dict(raw_item)
                item_status = str(item.get("status") or "").strip().lower()
                if item_status in {"running", "in_progress"}:
                    item["status"] = "failed"
                    item["error"] = str(item.get("error") or "Backend restarted before automation finished")
                    item["finished_at"] = item.get("finished_at") or utc_now_iso()
                items.append(item)
            run["items"] = items
        normalized.append(run)
    return normalized


def _normalize_stale_listing_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw_run in runs:
        if not isinstance(raw_run, dict):
            continue
        run = dict(raw_run)
        status = str(run.get("status") or "").strip().lower()
        if status == "running":
            run["status"] = "stopped"
            run["stop_requested"] = True
            run["finished_at"] = run.get("finished_at") or utc_now_iso()
            run["error"] = str(run.get("error") or "Backend restarted before retrieval finished")
        normalized.append(run)
    return normalized


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return default_state()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return default_state()
    if not isinstance(data, dict):
        return default_state()
    merged = default_state()
    merged.update(data)
    if not isinstance(merged.get("application_runs"), list):
        merged["application_runs"] = []
    if not isinstance(merged.get("listing_runs"), list):
        merged["listing_runs"] = []
    merged["application_runs"] = _normalize_stale_application_runs(merged.get("application_runs", []))
    merged["listing_runs"] = _normalize_stale_listing_runs(merged.get("listing_runs", []))
    scheduler_defaults = default_state()["scheduler"]
    existing_scheduler = merged.get("scheduler") if isinstance(merged.get("scheduler"), dict) else {}
    scheduler_defaults.update(existing_scheduler)
    merged["scheduler"] = scheduler_defaults
    return merged


def save_state() -> None:
    STATE_PATH.write_text(json.dumps(STATE, ensure_ascii=False, indent=2), encoding="utf-8")


def mutate_state(callback):
    with STATE_LOCK:
        callback(STATE)
        save_state()


STATE = load_state()
save_state()
reset_running_sources_to_idle()


def load_job_record(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _ats_blocks_from_record(data: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return blocks
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        if not str(key).startswith("ats"):
            continue
        blocks.append(value)
    return blocks


def _application_status_from_record(data: dict[str, Any]) -> tuple[bool, str]:
    application_done = False
    application_status = ""
    for block in _ats_blocks_from_record(data):
        if not application_done:
            application_done = bool(block.get("application_done"))
        if not application_status:
            application_status = str(block.get("application_status") or "").strip()
    if application_done and not application_status:
        application_status = "completed"
    return application_done, application_status


def _question_key(question: dict[str, Any]) -> str:
    question_id = str(question.get("question_id") or "").strip()
    if question_id:
        return question_id
    label = str(question.get("label") or "").strip().lower()
    field_type = str(question.get("field_type") or "").strip().lower()
    options = tuple(str(option or "").strip().lower() for option in list(question.get("options", [])))
    return f"{field_type}|{label}|{'|'.join(options)}"


def _append_normalized_question(
    target: list[dict[str, Any]],
    seen: set[str],
    raw_question: dict[str, Any],
    fallback_field_type: str = "",
) -> None:
    if not isinstance(raw_question, dict):
        return
    label = str(raw_question.get("label") or raw_question.get("question") or "").strip()
    if not label:
        return
    field_type = str(raw_question.get("field_type") or fallback_field_type or "text").strip().lower()
    if not field_type:
        field_type = "text"
    options = [
        str(option or "").strip()
        for option in list(raw_question.get("options", []))
        if str(option or "").strip()
    ]
    normalized = {
        "question_id": str(raw_question.get("question_id") or "").strip(),
        "label": label,
        "field_type": field_type,
        "options": options,
        "reason": str(raw_question.get("reason") or "").strip(),
        "confidence": raw_question.get("confidence"),
    }
    key = _question_key(normalized)
    if key in seen:
        return
    seen.add(key)
    target.append(normalized)


def _questions_from_ats_block(block: dict[str, Any]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()
    if not isinstance(block, dict):
        return questions

    for raw_question in list(block.get("user_questions", [])):
        _append_normalized_question(questions, seen, raw_question)

    for raw_question in list(block.get("required_questions", [])):
        _append_normalized_question(questions, seen, raw_question)

    for raw_question in list(block.get("required_dropdowns", [])):
        _append_normalized_question(questions, seen, raw_question, fallback_field_type="dropdown")

    for raw_question in list(block.get("required_text_fields", [])):
        _append_normalized_question(questions, seen, raw_question, fallback_field_type="text")

    for raw_question in list(block.get("required_checkboxes", [])):
        _append_normalized_question(questions, seen, raw_question, fallback_field_type="checkbox")

    for raw_question in list(block.get("required_segments", [])):
        _append_normalized_question(questions, seen, raw_question, fallback_field_type="segment")

    return questions


def _questions_from_record(data: dict[str, Any]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in _ats_blocks_from_record(data):
        for question in _questions_from_ats_block(block):
            key = _question_key(question)
            if key in seen:
                continue
            seen.add(key)
            questions.append(question)
    return questions


def _questions_for_job_key(job_key: str) -> list[dict[str, Any]]:
    key = str(job_key or "").strip()
    if not key:
        return []
    path = JOBS_DIR / f"{key}.json"
    if not path.exists():
        return []
    return _questions_from_record(load_job_record(path))


def _detect_ats_program(application_url: str) -> str:
    url = str(application_url or "").strip().lower()
    if "greenhouse.io" in url:
        return "greenhouse"
    if "smartrecruiters" in url:
        return "smartrecruiters"
    if "workday" in url:
        return "workday"
    if "successfactors" in url:
        return "successfactors"
    if "jobup.ch" in url:
        return "jobup"
    if url:
        return "generalats"
    return "unknown"


def _detect_application_language_for_display(application_url: str) -> str:
    url = str(application_url or "").strip()
    if not url:
        return "unknown"
    detected = detect_language_from_url(url)
    return normalize_language(detected, default="fr")


def load_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    if not JOBS_DIR.exists():
        return jobs
    for path in JOBS_DIR.glob("*.json"):
        data = load_job_record(path)
        job = data.get("job") if isinstance(data.get("job"), dict) else {}
        if not job:
            continue
        app_url = str(job.get("url_application") or job.get("application_url") or "").strip()
        try:
            parsed = urlparse(app_url.lower()) if app_url else None
            haystack = f"{(parsed.netloc or '')}{(parsed.path or '')}" if parsed else ""
        except Exception:
            haystack = app_url.lower()
        headhunter_agency = bool(job.get("headhunter_agency")) or any(
            marker in haystack for marker in HEADHUNTER_DOMAIN_MARKERS
        )
        application_done, application_status = _application_status_from_record(data)
        try:
            created_ts = int(path.stat().st_ctime)
        except Exception:
            created_ts = 0
        entry = dict(job)
        entry["file_name"] = path.name
        entry["job_key"] = str(job.get("job_key") or path.stem)
        entry["created_ts"] = created_ts
        entry["application_url"] = app_url
        entry["automation_possible"] = bool(app_url) and not headhunter_agency
        entry["headhunter_agency"] = headhunter_agency
        entry["application_done"] = application_done
        entry["application_status"] = "headhunter_agency" if headhunter_agency else application_status
        jobs.append(entry)
    jobs.sort(key=lambda item: item.get("created_ts", 0), reverse=True)
    return jobs


def load_job_by_key(job_key: str) -> dict[str, Any] | None:
    path = JOBS_DIR / f"{job_key}.json"
    if not path.exists():
        return None
    data = load_job_record(path)
    job = data.get("job") if isinstance(data.get("job"), dict) else {}
    if not job:
        return None
    application_done, application_status = _application_status_from_record(data)
    app_url = str(job.get("url_application") or job.get("application_url") or "").strip()
    job_entry = dict(job)
    job_entry["job_key"] = str(job.get("job_key") or job_key)
    job_entry["application_url"] = app_url
    job_entry["application_done"] = application_done
    job_entry["application_status"] = application_status
    return job_entry


def _replace_run(run_id: str, collection_name: str, new_run: dict[str, Any]) -> None:
    def callback(state: dict[str, Any]) -> None:
        runs = state.get(collection_name, [])
        for idx, item in enumerate(runs):
            if item.get("id") == run_id:
                runs[idx] = new_run
                break

    mutate_state(callback)


def _append_run(collection_name: str, payload: dict[str, Any]) -> None:
    def callback(state: dict[str, Any]) -> None:
        state.setdefault(collection_name, [])
        state[collection_name].insert(0, payload)
        state[collection_name] = state[collection_name][:50]

    mutate_state(callback)


def _clear_runs(collection_name: str) -> None:
    def callback(state: dict[str, Any]) -> None:
        state[collection_name] = []

    mutate_state(callback)


def _clear_application_runs(origin: str | None = None) -> None:
    def callback(state: dict[str, Any]) -> None:
        runs = list(state.get("application_runs", []))
        if origin:
            state["application_runs"] = [run for run in runs if str(run.get("origin") or "") != origin]
        else:
            state["application_runs"] = []

    mutate_state(callback)


def _has_running_application_run(origin: str | None = None) -> bool:
    with APPLICATION_RUNS_LOCK:
        active_run_ids = set(ACTIVE_APPLICATION_RUNS)
    if not active_run_ids:
        return False
    with STATE_LOCK:
        runs = list(STATE.get("application_runs", []))
    for run in runs:
        if str(run.get("id") or "") not in active_run_ids:
            continue
        if str(run.get("status") or "").strip().lower() not in {"running", "pausing", "paused"}:
            continue
        if origin and str(run.get("origin") or "") != origin:
            continue
        return True
    return False


def _read_scheduler() -> dict[str, Any]:
    with STATE_LOCK:
        return dict(STATE.get("scheduler", {}))


def _update_scheduler(**updates: Any) -> None:
    def callback(state: dict[str, Any]) -> None:
        scheduler = state.setdefault("scheduler", {})
        scheduler.update(updates)

    mutate_state(callback)


def _normalize_requested_source_ids(source_ids: Any) -> list[str]:
    available = {str(source.get("source_id") or "") for source in load_sources()}
    if not isinstance(source_ids, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in source_ids:
        source_id = str(raw or "").strip()
        if not source_id or source_id in seen or source_id not in available:
            continue
        seen.add(source_id)
        normalized.append(source_id)
    return normalized


def _application_item_status(job: dict[str, Any], result: subprocess.CompletedProcess | None, error: str = "") -> dict[str, Any]:
    refreshed = load_job_by_key(str(job.get("job_key") or "")) or job
    status_text = str(refreshed.get("application_status") or "").strip().lower()
    application_done = bool(refreshed.get("application_done"))
    application_url = refreshed.get("application_url") or job.get("application_url") or ""
    application_language = (
        refreshed.get("application_language")
        or job.get("application_language")
        or _detect_application_language_for_display(application_url)
    )
    if error:
        status = "failed"
    elif application_done or status_text in {"completed", "done", "success"}:
        status = "success"
    elif result is not None and result.returncode != 0:
        status = "failed"
    elif status_text in {"failed", "error"}:
        status = "failed"
    else:
        status = "in_progress"
    questions = _questions_for_job_key(str(refreshed.get("job_key") or job.get("job_key") or ""))
    return {
        "job_key": refreshed.get("job_key") or job.get("job_key"),
        "title": refreshed.get("title") or job.get("title") or "Untitled",
        "company": refreshed.get("hiring_org") or job.get("hiring_org") or "",
        "application_url": application_url,
        "ats_program": _detect_ats_program(application_url),
        "application_language": application_language,
        "status": status,
        "application_done": application_done,
        "application_status": refreshed.get("application_status") or "",
        "return_code": None if result is None else result.returncode,
        "error": error,
        "finished_at": utc_now_iso(),
        "questions": questions,
        "question_count": len(questions),
    }


def _application_run_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "jobs_total": len(items or []),
        "jobs_success": 0,
        "jobs_failed": 0,
        "jobs_skipped": 0,
        "jobs_running": 0,
    }
    for item in items or []:
        status = str(item.get("status") or "").strip().lower()
        if status == "success":
            summary["jobs_success"] += 1
        elif status == "failed":
            summary["jobs_failed"] += 1
        elif status == "skipped":
            summary["jobs_skipped"] += 1
        elif status in {"running", "in_progress", "pausing", "paused"}:
            summary["jobs_running"] += 1
    return summary


def _apply_application_run_summary(run: dict[str, Any]) -> dict[str, Any]:
    run.update(_application_run_summary(list(run.get("items", []))))
    return run


def _enrich_application_run(run: dict[str, Any]) -> dict[str, Any]:
    items = []
    for raw_item in list(run.get("items", [])):
        item = dict(raw_item)
        item["ats_program"] = item.get("ats_program") or _detect_ats_program(item.get("application_url") or "")
        item["application_language"] = item.get("application_language") or _detect_application_language_for_display(item.get("application_url") or "")
        questions = _questions_for_job_key(str(item.get("job_key") or ""))
        item["questions"] = questions
        item["question_count"] = len(questions)
        items.append(item)
    run["items"] = items
    return _apply_application_run_summary(run)


def _run_main_for_job(job: dict[str, Any], *, stream_to_terminal: bool = False) -> subprocess.CompletedProcess:
    command = [
        sys.executable,
        str(BASE_DIR / "main.py"),
        str(job.get("application_url") or ""),
        str(job.get("job_key") or ""),
        "--mode",
        DEFAULT_MAIN_MODE,
    ]
    if stream_to_terminal:
        return subprocess.run(
            command,
            cwd=str(BASE_DIR),
            timeout=APPLICATION_TIMEOUT_SECONDS,
            text=True,
            errors="replace",
        )
    return subprocess.run(
        command,
        cwd=str(BASE_DIR),
        timeout=APPLICATION_TIMEOUT_SECONDS,
        capture_output=True,
        text=True,
        errors="replace",
    )


def _manual_url_job(application_url: str) -> dict[str, Any]:
    parsed = urlparse(application_url)
    host = str(parsed.netloc or "").strip()
    haystack = f"{host.lower()}{(parsed.path or '').lower()}"
    headhunter_agency = any(marker in haystack for marker in HEADHUNTER_DOMAIN_MARKERS)
    return {
        "job_key": f"url_{uuid.uuid4().hex[:12]}",
        "title": "Direct URL",
        "hiring_org": host or "Manual URL",
        "application_url": application_url,
        "url_application": application_url,
        "url": application_url,
        "url_add": application_url,
        "headhunter_agency": headhunter_agency,
        "source_id": "manual_url",
        "source_name": "Direct URL",
        "source_type": "manual",
    }


def _get_application_pause_event(run_id: str) -> threading.Event | None:
    with APPLICATION_RUNS_LOCK:
        if run_id not in ACTIVE_APPLICATION_RUNS:
            return None
        event = APPLICATION_PAUSE_EVENTS.get(run_id)
        if event is None:
            event = threading.Event()
            APPLICATION_PAUSE_EVENTS[run_id] = event
        return event


def _get_application_stop_event(run_id: str) -> threading.Event | None:
    with APPLICATION_RUNS_LOCK:
        if run_id not in ACTIVE_APPLICATION_RUNS:
            return None
        event = APPLICATION_STOP_EVENTS.get(run_id)
        if event is None:
            event = threading.Event()
            APPLICATION_STOP_EVENTS[run_id] = event
        return event


def _application_stop_requested(run_id: str) -> bool:
    event = _get_application_stop_event(run_id)
    return bool(event and event.is_set())


def _update_application_run_pause_request(run_id: str, paused: bool) -> bool:
    updated = False

    def callback(state: dict[str, Any]) -> None:
        nonlocal updated
        for run in state.get("application_runs", []):
            if str(run.get("id") or "") != run_id:
                continue
            status = str(run.get("status") or "").strip().lower()
            if status not in {"running", "pausing", "paused"}:
                continue
            run["pause_requested"] = paused
            if paused and status == "running":
                run["status"] = "pausing"
            elif not paused and status in {"pausing", "paused"}:
                run["status"] = "running"
            updated = True
            break

    mutate_state(callback)
    return updated


def pause_application_run(run_id: str) -> bool:
    event = _get_application_pause_event(run_id)
    if event is None:
        return False
    event.set()
    return _update_application_run_pause_request(run_id, True)


def resume_application_run(run_id: str) -> bool:
    event = _get_application_pause_event(run_id)
    if event is None:
        return False
    event.clear()
    return _update_application_run_pause_request(run_id, False)


def stop_application_run(run_id: str) -> bool:
    stop_event = _get_application_stop_event(run_id)
    pause_event = _get_application_pause_event(run_id)
    if stop_event is None:
        return False
    stop_event.set()
    if pause_event is not None:
        pause_event.clear()

    updated = False

    def callback(state: dict[str, Any]) -> None:
        nonlocal updated
        for run in state.get("application_runs", []):
            if str(run.get("id") or "") != run_id:
                continue
            status = str(run.get("status") or "").strip().lower()
            if status not in {"running", "pausing", "paused"}:
                continue
            run["status"] = "stopped"
            run["pause_requested"] = False
            run["stop_requested"] = True
            run["finished_at"] = run.get("finished_at") or utc_now_iso()
            updated = True
            break

    mutate_state(callback)
    return updated


def restart_bulk_application_run(run_id: str) -> tuple[str | None, str]:
    with STATE_LOCK:
        runs = list(STATE.get("application_runs", []))
    target = next((run for run in runs if str(run.get("id") or "") == run_id), None)
    if not target:
        return None, "Application run not found"
    if str(target.get("origin") or "").strip().lower() != "bulk":
        return None, "Only bulk automation can be started again from the Jobs page"
    if str(target.get("status") or "").strip().lower() != "paused":
        return None, "Start Again is available once automation is paused"
    if not stop_application_run(run_id):
        return None, "No paused application run found"
    jobs = [job for job in load_jobs() if bool(job.get("automation_possible"))]
    if not jobs:
        return None, "No automatable jobs found"
    return start_application_run(jobs, "bulk"), ""


def _wait_if_application_paused(run_id: str, run: dict[str, Any]) -> None:
    pause_event = _get_application_pause_event(run_id)
    stop_event = _get_application_stop_event(run_id)
    if stop_event is not None and stop_event.is_set():
        return
    if pause_event is None or not pause_event.is_set():
        return
    run["status"] = "paused"
    run["pause_requested"] = True
    _apply_application_run_summary(run)
    _replace_run(run_id, "application_runs", run)
    while pause_event.is_set():
        if stop_event is not None and stop_event.is_set():
            run["status"] = "stopped"
            run["pause_requested"] = False
            run["stop_requested"] = True
            run["finished_at"] = run.get("finished_at") or utc_now_iso()
            _apply_application_run_summary(run)
            _replace_run(run_id, "application_runs", run)
            return
        time.sleep(0.5)
    if stop_event is not None and stop_event.is_set():
        run["status"] = "stopped"
        run["pause_requested"] = False
        run["stop_requested"] = True
        run["finished_at"] = run.get("finished_at") or utc_now_iso()
        _apply_application_run_summary(run)
        _replace_run(run_id, "application_runs", run)
        return
    run["status"] = "running"
    run["pause_requested"] = False
    _apply_application_run_summary(run)
    _replace_run(run_id, "application_runs", run)


def _application_worker(run_id: str, jobs: list[dict[str, Any]], origin: str) -> None:
    run = {
        "id": run_id,
        "origin": origin,
        "status": "running",
        "started_at": utc_now_iso(),
        "finished_at": None,
        "items": [],
        "jobs_total": 0,
        "jobs_success": 0,
        "jobs_failed": 0,
        "jobs_skipped": 0,
        "jobs_running": 0,
        "pause_requested": False,
        "stop_requested": False,
    }
    with APPLICATION_RUNS_LOCK:
        ACTIVE_APPLICATION_RUNS.add(run_id)
        APPLICATION_PAUSE_EVENTS[run_id] = threading.Event()
        APPLICATION_STOP_EVENTS[run_id] = threading.Event()
    _append_run("application_runs", run)
    stream_to_terminal = origin in {"single", "url", "bulk"}
    try:
        for job in jobs:
            _wait_if_application_paused(run_id, run)
            if _application_stop_requested(run_id):
                break
            item = {
                "job_key": job.get("job_key"),
                "title": job.get("title") or "Untitled",
                "company": job.get("hiring_org") or "",
                "application_url": job.get("application_url") or "",
                "ats_program": _detect_ats_program(job.get("application_url") or ""),
                "application_language": (
                    job.get("application_language")
                    or _detect_application_language_for_display(job.get("application_url") or "")
                ),
                "status": "running",
                "application_done": False,
                "application_status": "in_progress",
                "return_code": None,
                "error": "",
                "started_at": utc_now_iso(),
                "finished_at": None,
            }
            run["items"].append(item)
            _apply_application_run_summary(run)
            _replace_run(run_id, "application_runs", run)

            app_url = str(job.get("application_url") or "").strip()
            if not app_url:
                item.update(
                    {
                        "status": "skipped",
                        "application_status": "missing_application_url",
                        "error": "No application URL found",
                        "finished_at": utc_now_iso(),
                    }
                )
                _apply_application_run_summary(run)
                _replace_run(run_id, "application_runs", run)
                continue

            if bool(job.get("headhunter_agency")):
                item.update(
                    {
                        "status": "skipped",
                        "application_status": "headhunter_agency",
                        "error": "Skipped because the application URL belongs to a headhunter agency",
                        "finished_at": utc_now_iso(),
                    }
                )
                _apply_application_run_summary(run)
                _replace_run(run_id, "application_runs", run)
                continue

            try:
                result = _run_main_for_job(job, stream_to_terminal=stream_to_terminal)
                item.update(_application_item_status(job, result))
            except subprocess.TimeoutExpired:
                item.update(_application_item_status(job, None, error="Automation timed out"))
            except Exception as exc:
                item.update(_application_item_status(job, None, error=str(exc)))
            _apply_application_run_summary(run)
            _replace_run(run_id, "application_runs", run)

        if _application_stop_requested(run_id):
            run["status"] = "stopped"
            run["pause_requested"] = False
            run["stop_requested"] = True
        else:
            statuses = {str(item.get("status") or "") for item in run["items"]}
            if statuses and statuses <= {"success", "skipped"}:
                run["status"] = "completed"
            elif "running" in statuses:
                run["status"] = "running"
            elif "failed" in statuses:
                run["status"] = "completed_with_errors"
            else:
                run["status"] = "completed"
        run["finished_at"] = run.get("finished_at") or utc_now_iso()
        _apply_application_run_summary(run)
        _replace_run(run_id, "application_runs", run)
    finally:
        with APPLICATION_RUNS_LOCK:
            ACTIVE_APPLICATION_RUNS.discard(run_id)
            APPLICATION_PAUSE_EVENTS.pop(run_id, None)
            APPLICATION_STOP_EVENTS.pop(run_id, None)


def start_application_run(jobs: list[dict[str, Any]], origin: str) -> str:
    run_id = uuid.uuid4().hex
    thread = threading.Thread(target=_application_worker, args=(run_id, jobs, origin), daemon=True)
    thread.start()
    return run_id


def _listing_worker(run_id: str, pages: int, origin: str, source_ids: list[str]) -> None:
    global LISTING_ACTIVE
    run = {
        "id": run_id,
        "origin": origin,
        "pages": pages,
        "selected_source_ids": list(source_ids),
        "status": "running",
        "started_at": utc_now_iso(),
        "finished_at": None,
        "jobs_before": len(load_jobs()),
        "jobs_after": None,
        "jobs_added": None,
        "jobs_found": 0,
        "jobs_saved": 0,
        "jobs_skipped_existing": 0,
        "jobs_failed": 0,
        "items": [],
        "error": "",
        "stop_requested": False,
    }
    _append_run("listing_runs", run)
    LISTING_ACTIVE = True
    LISTING_STOP_EVENT.clear()
    _update_scheduler(status="running", last_run_at=run["started_at"])

    try:
        listing_module = importlib.import_module("ListingJob")
        result = listing_module.retrieve_jobs(
            pages=pages,
            term="",
            source_ids=source_ids,
            run_id=run_id,
            stop_requested=LISTING_STOP_EVENT.is_set,
        )
        run["selected_source_ids"] = list(result.get("selected_source_ids") or source_ids)
        run["jobs_found"] = int(result.get("jobs_found") or 0)
        run["jobs_saved"] = int(result.get("jobs_saved") or 0)
        run["jobs_skipped_existing"] = int(result.get("jobs_skipped_existing") or 0)
        run["jobs_failed"] = int(result.get("jobs_failed") or 0)
        run["items"] = list(result.get("items") or [])
        run["status"] = "stopped" if LISTING_STOP_EVENT.is_set() else "completed"
    except Exception as exc:
        if exc.__class__.__name__ == "RetrievalStopRequested":
            run["status"] = "stopped"
            run["stop_requested"] = True
            run["error"] = "Retrieval stop requested"
        else:
            run["status"] = "failed"
            run["error"] = traceback.format_exc(limit=3)
    finally:
        run["stop_requested"] = bool(LISTING_STOP_EVENT.is_set())
        run["jobs_after"] = len(load_jobs())
        run["jobs_added"] = max(0, int(run["jobs_after"] or 0) - int(run["jobs_before"] or 0))
        run["finished_at"] = utc_now_iso()
        _replace_run(run_id, "listing_runs", run)
        LISTING_ACTIVE = False
        LISTING_STOP_EVENT.clear()
        _update_scheduler(status="idle", last_run_at=run["finished_at"])


def start_listing_run(pages: int, origin: str, source_ids: list[str] | None = None) -> str | None:
    global LISTING_ACTIVE
    if LISTING_ACTIVE:
        return None
    LISTING_ACTIVE = True
    LISTING_STOP_EVENT.clear()
    run_id = uuid.uuid4().hex
    normalized_source_ids = _normalize_requested_source_ids(source_ids)
    thread = threading.Thread(
        target=_listing_worker,
        args=(run_id, pages, origin, normalized_source_ids),
        daemon=True,
    )
    thread.start()
    return run_id


def _scheduler_loop() -> None:
    while not SCHEDULER_STOP_EVENT.is_set():
        scheduler = _read_scheduler()
        if not scheduler.get("enabled"):
            break

        interval_hours = int(scheduler.get("interval_hours") or 1)
        pages = int(scheduler.get("pages") or DEFAULT_LISTING_PAGES)
        source_ids = _normalize_requested_source_ids(scheduler.get("source_ids"))
        next_run_at = scheduler.get("next_run_at")
        now = dt.datetime.now(dt.timezone.utc)
        target = None
        if next_run_at:
            try:
                target = dt.datetime.fromisoformat(str(next_run_at))
            except Exception:
                target = None
        if target is None:
            target = now + dt.timedelta(hours=interval_hours)
            _update_scheduler(next_run_at=target.isoformat(), status="scheduled")

        if now >= target:
            run_id = start_listing_run(pages, "scheduled", source_ids=source_ids)
            next_target = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=interval_hours)
            _update_scheduler(next_run_at=next_target.isoformat(), status="scheduled")
            if run_id is None:
                time.sleep(5)
                continue
        time.sleep(1)


def start_scheduler(interval_hours: int, pages: int, source_ids: list[str] | None = None) -> None:
    global SCHEDULER_THREAD
    SCHEDULER_STOP_EVENT.clear()
    next_run_at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=interval_hours)).isoformat()
    normalized_source_ids = _normalize_requested_source_ids(source_ids)
    _update_scheduler(
        enabled=True,
        interval_hours=interval_hours,
        pages=pages,
        source_ids=normalized_source_ids,
        next_run_at=next_run_at,
        status="scheduled",
    )
    if SCHEDULER_THREAD and SCHEDULER_THREAD.is_alive():
        return
    SCHEDULER_THREAD = threading.Thread(target=_scheduler_loop, daemon=True)
    SCHEDULER_THREAD.start()


def stop_scheduler() -> None:
    SCHEDULER_STOP_EVENT.set()
    _update_scheduler(enabled=False, next_run_at=None, status="idle")


def stop_listing_run() -> bool:
    if not LISTING_ACTIVE:
        return False
    LISTING_STOP_EVENT.set()
    return True


def parse_candidate_file(path: Path) -> dict[str, Any]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    values: dict[str, Any] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            continue
        try:
            values[target.attr] = ast.literal_eval(node.value)
        except Exception:
            continue
    return values


def load_candidates() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not CANDIDATES_DIR.exists():
        return rows
    for path in CANDIDATES_DIR.glob("FCandidate_*/*.py"):
        values = parse_candidate_file(path)
        if not values:
            continue
        experiences = int(values.get("nb_experience") or 0)
        educations = int(values.get("nb_education") or 0)
        languages = int(values.get("nb_language") or 0)
        if "free_version" in values:
            plan_label = "Free" if values.get("free_version") else "Paid"
        else:
            plan_label = "Unknown"
        rows.append(
            {
                "id": path.parent.name,
                "first_name": str(values.get("first_name") or ""),
                "last_name": str(values.get("last_name") or ""),
                "email": str(values.get("email") or ""),
                "ip_address": "Hidden",
                "plan": plan_label,
                "profile_path": str(path),
                "summary": {
                    "experience_count": experiences,
                    "education_count": educations,
                    "language_count": languages,
                },
                "details": values,
            }
        )
    rows.sort(key=lambda item: (item.get("last_name") or "", item.get("first_name") or ""))
    return rows


@app.route("/")
def backend_index():
    return redirect("/jobs")


@app.route("/jobs")
def jobs_page():
    return send_file(BASE_DIR / "backend_jobs.html")


@app.route("/scanners")
def scanners_page():
    return send_file(BASE_DIR / "backend_scanners.html")


@app.route("/applications")
def applications_page():
    return send_file(BASE_DIR / "backend_applications.html")


@app.route("/candidates")
def candidates_page():
    return send_file(BASE_DIR / "backend_candidates.html")


@app.route("/app.css")
def app_css():
    return send_file(BASE_DIR / "app.css")


@app.route("/backend.js")
def backend_js():
    return send_file(BASE_DIR / "backend.js")


@app.route("/api/jobs")
def jobs_api():
    return jsonify(load_jobs())


@app.route("/api/retrieval/sources")
def retrieval_sources_api():
    return jsonify(load_sources())


@app.route("/api/retrieval/sources/save", methods=["POST"])
def retrieval_sources_save_api():
    payload = request.get_json(silent=True) or {}
    settings = payload.get("settings")
    if isinstance(settings, str):
        settings = settings.strip()
        if settings:
            try:
                settings = json.loads(settings)
            except Exception:
                return jsonify({"ok": False, "error": "Settings must be valid JSON"}), 400
        else:
            settings = {}
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        return jsonify({"ok": False, "error": "Settings must be a JSON object"}), 400

    source_payload = {
        "source_id": str(payload.get("source_id") or "").strip(),
        "name": str(payload.get("name") or "").strip(),
        "type": "career_site",
        "sector": str(payload.get("sector") or "").strip(),
        "browser_mode": str(payload.get("browser_mode") or "").strip(),
        "location_scope": str(payload.get("location_scope") or "").strip(),
        "swiss_only_url": str(payload.get("swiss_only_url") or "").strip(),
        "base_url": str(payload.get("base_url") or "").strip(),
        "enabled": bool(payload.get("enabled", True)),
        "scanner_key": str(payload.get("scanner_key") or "").strip(),
        "default_pages": int(payload.get("default_pages") or 1),
        "supports_paging": bool(payload.get("supports_paging", False)),
        "settings": settings,
    }
    if not source_payload["name"]:
        return jsonify({"ok": False, "error": "Name is required"}), 400
    if not source_payload["base_url"]:
        return jsonify({"ok": False, "error": "Base URL is required"}), 400
    if str(source_payload["location_scope"] or "").strip().lower() == "worldwide" and not source_payload["swiss_only_url"]:
        return jsonify({"ok": False, "error": "Swiss-only URL is required for worldwide sources"}), 400

    try:
        source = upsert_source(source_payload, original_source_id=str(payload.get("original_source_id") or "").strip() or None)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "source": source})


@app.route("/api/retrieval/sources/delete", methods=["POST"])
def retrieval_sources_delete_api():
    payload = request.get_json(silent=True) or {}
    source_id = str(payload.get("source_id") or "").strip()
    if not source_id:
        return jsonify({"ok": False, "error": "Source id is required"}), 400
    if not delete_source(source_id):
        return jsonify({"ok": False, "error": "Source not found"}), 404
    return jsonify({"ok": True, "source_id": source_id})


@app.route("/api/state")
def state_api():
    with STATE_LOCK:
        scheduler = dict(STATE.get("scheduler", {}))
        listing_runs = list(STATE.get("listing_runs", []))
        application_runs = list(STATE.get("application_runs", []))
    return jsonify(
        {
            "scheduler": scheduler,
            "listing_running": LISTING_ACTIVE,
            "listing_stop_requested": LISTING_STOP_EVENT.is_set(),
            "latest_listing_run": listing_runs[0] if listing_runs else None,
            "latest_application_run": _enrich_application_run(dict(application_runs[0])) if application_runs else None,
        }
    )


@app.route("/api/jobs/automate/<job_key>", methods=["POST"])
def automate_job(job_key: str):
    job = load_job_by_key(job_key)
    if not job:
        return jsonify({"ok": False, "error": "Job not found"}), 404
    run_id = start_application_run([job], "single")
    return jsonify({"ok": True, "run_id": run_id})


@app.route("/api/jobs/automate-all", methods=["POST"])
def automate_all_jobs():
    jobs = [job for job in load_jobs() if bool(job.get("automation_possible"))]
    if not jobs:
        return jsonify({"ok": False, "error": "No automatable jobs found"}), 400
    run_id = start_application_run(jobs, "bulk")
    return jsonify({"ok": True, "run_id": run_id, "job_count": len(jobs)})


@app.route("/api/applications/automate-url", methods=["POST"])
def automate_application_url():
    payload = request.get_json(silent=True) or {}
    application_url = str(payload.get("application_url") or payload.get("url") or "").strip()
    if not application_url:
        return jsonify({"ok": False, "error": "Application URL is required"}), 400
    parsed = urlparse(application_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return jsonify({"ok": False, "error": "Application URL must be a valid http(s) URL"}), 400
    job = _manual_url_job(application_url)
    run_id = start_application_run([job], "url")
    return jsonify({"ok": True, "run_id": run_id})


@app.route("/api/applications/<run_id>/pause", methods=["POST"])
def application_pause(run_id: str):
    if not pause_application_run(str(run_id or "").strip()):
        return jsonify({"ok": False, "error": "No running application run found"}), 409
    return jsonify({"ok": True})


@app.route("/api/applications/<run_id>/resume", methods=["POST"])
def application_resume(run_id: str):
    if not resume_application_run(str(run_id or "").strip()):
        return jsonify({"ok": False, "error": "No paused application run found"}), 409
    return jsonify({"ok": True})


@app.route("/api/applications/<run_id>/restart", methods=["POST"])
def application_restart(run_id: str):
    new_run_id, error = restart_bulk_application_run(str(run_id or "").strip())
    if not new_run_id:
        return jsonify({"ok": False, "error": error or "Could not start automation again"}), 409
    return jsonify({"ok": True, "run_id": new_run_id})


@app.route("/api/listing/run", methods=["POST"])
def listing_run():
    payload = request.get_json(silent=True) or {}
    pages = int(payload.get("pages") or DEFAULT_LISTING_PAGES)
    pages = max(1, min(pages, 20))
    source_ids = _normalize_requested_source_ids(payload.get("source_ids"))
    run_id = start_listing_run(pages, "manual", source_ids=source_ids)
    if not run_id:
        return jsonify({"ok": False, "error": "A listing run is already in progress"}), 409
    return jsonify({"ok": True, "run_id": run_id})


@app.route("/api/listing/stop", methods=["POST"])
def listing_stop():
    if not stop_listing_run():
        return jsonify({"ok": False, "error": "No retrieval run is currently in progress"}), 409
    return jsonify({"ok": True})


@app.route("/api/listing/scheduler/start", methods=["POST"])
def scheduler_start():
    payload = request.get_json(silent=True) or {}
    interval_hours = int(payload.get("interval_hours") or 1)
    pages = int(payload.get("pages") or DEFAULT_LISTING_PAGES)
    pages = max(1, min(pages, 20))
    source_ids = _normalize_requested_source_ids(payload.get("source_ids"))
    if interval_hours not in LISTING_SCHEDULE_OPTIONS:
        return jsonify({"ok": False, "error": "Interval must be 1, 2, or 3 hours"}), 400
    start_scheduler(interval_hours, pages, source_ids=source_ids)
    return jsonify({"ok": True})


@app.route("/api/listing/scheduler/stop", methods=["POST"])
def scheduler_stop():
    stop_scheduler()
    return jsonify({"ok": True})


@app.route("/api/applications")
def applications_api():
    with STATE_LOCK:
        runs = list(STATE.get("application_runs", []))
    return jsonify([_enrich_application_run(dict(run)) for run in runs])


@app.route("/api/applications/clear", methods=["POST"])
def applications_clear_api():
    payload = request.get_json(silent=True) or {}
    origin = str(payload.get("origin") or "").strip().lower() or None
    if origin not in {None, "single", "bulk", "url"}:
        return jsonify({"ok": False, "error": "Origin must be 'single', 'bulk', or 'url'"}), 400
    if _has_running_application_run(origin):
        label = f"{origin} automation" if origin else "application automation"
        return jsonify({"ok": False, "error": f"A {label} run is currently in progress"}), 409
    _clear_application_runs(origin)
    return jsonify({"ok": True})


@app.route("/api/listings")
def listings_api():
    with STATE_LOCK:
        runs = list(STATE.get("listing_runs", []))
    return jsonify(runs)


@app.route("/api/listings/clear", methods=["POST"])
def listings_clear_api():
    if LISTING_ACTIVE:
        return jsonify({"ok": False, "error": "A retrieval run is currently in progress"}), 409
    _clear_runs("listing_runs")
    return jsonify({"ok": True})


@app.route("/api/candidates")
def candidates_api():
    return jsonify(load_candidates())


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
