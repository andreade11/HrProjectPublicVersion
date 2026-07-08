from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
SOURCES_PATH = BASE_DIR / "retrieval_sources.json"
SOURCES_LOCK = threading.Lock()
SECTORS = {
    "generic platform",
    "bank",
    "insurance",
    "Audit, Accounting, Consulting",
    "Real Estate",
}
BROWSER_MODES = {
    "headless",
    "headed",
}
LOCATION_SCOPES = {
    "swiss_only",
    "worldwide",
}

DEFAULT_SOURCES = [
    {
        "source_id": "jobup_main",
        "name": "Jobup",
        "type": "job_board",
        "sector": "generic platform",
        "browser_mode": "headless",
        "location_scope": "swiss_only",
        "swiss_only_url": "",
        "base_url": "https://www.jobup.ch/en/jobs/?term=",
        "enabled": True,
        "scanner_key": "jobup",
        "default_pages": 1,
        "supports_paging": True,
        "status": "idle",
        "last_run_at": None,
        "last_success_at": None,
        "last_error": "",
    }
]


def _normalize_source(raw: dict[str, Any]) -> dict[str, Any]:
    source_id = str(raw.get("source_id") or "").strip()
    if not source_id:
        raise ValueError("Each retrieval source needs a source_id")
    settings = raw.get("settings") if isinstance(raw.get("settings"), dict) else {}
    sector = str(raw.get("sector") or "generic platform").strip()
    if sector not in SECTORS:
        sector = "generic platform"
    browser_mode = str(raw.get("browser_mode") or "headless").strip().lower()
    if browser_mode not in BROWSER_MODES:
        browser_mode = "headless"
    location_scope = str(raw.get("location_scope") or "swiss_only").strip().lower()
    if location_scope not in LOCATION_SCOPES:
        location_scope = "swiss_only"
    return {
        "source_id": source_id,
        "name": str(raw.get("name") or source_id).strip(),
        "type": str(raw.get("type") or "career_site").strip(),
        "sector": sector,
        "browser_mode": browser_mode,
        "location_scope": location_scope,
        "swiss_only_url": str(raw.get("swiss_only_url") or "").strip(),
        "base_url": str(raw.get("base_url") or "").strip(),
        "enabled": bool(raw.get("enabled", True)),
        "scanner_key": str(raw.get("scanner_key") or "generic_career").strip(),
        "default_pages": max(1, int(raw.get("default_pages") or 1)),
        "supports_paging": bool(raw.get("supports_paging", False)),
        "status": str(raw.get("status") or "idle").strip(),
        "last_run_at": raw.get("last_run_at"),
        "last_success_at": raw.get("last_success_at"),
        "last_error": str(raw.get("last_error") or ""),
        "settings": settings,
    }


def source_id_from_payload(payload: dict[str, Any]) -> str:
    raw = str(payload.get("name") or payload.get("base_url") or "source").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return slug or "source"


def _load_sources_unlocked() -> list[dict[str, Any]]:
    if not SOURCES_PATH.exists():
        SOURCES_PATH.write_text(json.dumps(DEFAULT_SOURCES, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        payload = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    except Exception:
        payload = DEFAULT_SOURCES
    if not isinstance(payload, list):
        payload = DEFAULT_SOURCES

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            source = _normalize_source(item)
        except Exception:
            continue
        if source["source_id"] in seen:
            continue
        seen.add(source["source_id"])
        normalized.append(source)

    for item in DEFAULT_SOURCES:
        source = _normalize_source(item)
        if source["source_id"] not in seen:
            normalized.append(source)

    SOURCES_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def load_sources() -> list[dict[str, Any]]:
    with SOURCES_LOCK:
        return _load_sources_unlocked()


def save_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [_normalize_source(item) for item in sources]
    with SOURCES_LOCK:
        SOURCES_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def upsert_source(payload: dict[str, Any], original_source_id: str | None = None) -> dict[str, Any]:
    original_source_id = str(original_source_id or "").strip()
    if not str(payload.get("source_id") or "").strip():
        payload = dict(payload)
        if original_source_id:
            payload["source_id"] = original_source_id
        else:
            base_id = source_id_from_payload(payload)
            candidate_id = base_id
            suffix = 2
            with SOURCES_LOCK:
                sources = _load_sources_unlocked()
                existing_ids = {str(source.get("source_id") or "") for source in sources}
            while candidate_id in existing_ids:
                candidate_id = f"{base_id}_{suffix}"
                suffix += 1
            payload["source_id"] = candidate_id
    candidate = _normalize_source(payload)
    original_source_id = str(original_source_id or candidate.get("source_id") or "").strip()
    with SOURCES_LOCK:
        sources = _load_sources_unlocked()
        replacement_index = None
        for idx, source in enumerate(sources):
            if source.get("source_id") == original_source_id:
                replacement_index = idx
                break

        for idx, source in enumerate(sources):
            if idx == replacement_index:
                continue
            if source.get("source_id") == candidate["source_id"]:
                raise ValueError(f"Source id '{candidate['source_id']}' already exists")

        if replacement_index is not None:
            existing = sources[replacement_index]
            merged = dict(existing)
            merged.update(candidate)
            candidate = _normalize_source(merged)
            sources[replacement_index] = candidate
        else:
            sources.append(candidate)

        SOURCES_PATH.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
        return candidate


def get_source(source_id: str) -> dict[str, Any] | None:
    source_id = str(source_id or "").strip()
    if not source_id:
        return None
    for source in load_sources():
        if source.get("source_id") == source_id:
            return source
    return None


def get_enabled_sources() -> list[dict[str, Any]]:
    return [source for source in load_sources() if bool(source.get("enabled"))]


def delete_source(source_id: str) -> bool:
    source_id = str(source_id or "").strip()
    if not source_id:
        return False
    with SOURCES_LOCK:
        sources = _load_sources_unlocked()
        remaining = [source for source in sources if source.get("source_id") != source_id]
        if len(remaining) == len(sources):
            return False
        SOURCES_PATH.write_text(json.dumps(remaining, ensure_ascii=False, indent=2), encoding="utf-8")
        return True


def update_source_runtime(source_id: str, **updates: Any) -> dict[str, Any] | None:
    with SOURCES_LOCK:
        sources = _load_sources_unlocked()
        updated_source = None
        for idx, source in enumerate(sources):
            if source.get("source_id") != source_id:
                continue
            merged = dict(source)
            merged.update(updates)
            updated_source = _normalize_source(merged)
            sources[idx] = updated_source
            break
        if updated_source is None:
            return None
        SOURCES_PATH.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
        return updated_source


def reset_running_sources_to_idle() -> list[dict[str, Any]]:
    with SOURCES_LOCK:
        sources = _load_sources_unlocked()
        changed = False
        normalized: list[dict[str, Any]] = []
        for source in sources:
            merged = dict(source)
            if str(merged.get("status") or "").strip().lower() == "running":
                merged["status"] = "idle"
                changed = True
            normalized.append(_normalize_source(merged))
        if changed:
            SOURCES_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        return normalized
