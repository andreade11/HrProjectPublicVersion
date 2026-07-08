from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from env_loader import load_env_file
from scanners.browser_flow_utils import (
    DEFAULT_CONTROL_SELECTOR,
    STANDARD_APPLY_LABELS,
    STANDARD_NEGATIVE_LABELS,
    STANDARD_POST_APPLY_LABELS,
    click_control_and_capture_target,
    dismiss_cookie_banners,
    page_has_application_fields,
    settle_page,
)
from retrieval_store import (
    candidate_job_urls,
    get_automation_state,
    get_registration_url,
    is_headhunter_application_url,
    load_known_job_urls,
    save_job_record,
)


load_env_file()


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) "
    "Gecko/20100101 Firefox/123.0",
}

LISTING_HEADLESS = True
LISTING_TIMEOUT_MS = 20000
APPLY_HEADLESS = False
APPLY_TIMEOUT_MS = 20000
APPLY_TOTAL_TIMEOUT_MS = 45000
APPLY_CLICK_TIMEOUT_MS = 5000
APPLY_NAV_TIMEOUT_MS = 8000
POST_LOAD_SETTLE_MS = 1200
CLICKABLE_CARD_TIMEOUT_MS = 8000
MAX_JOB_LINKS = 80
MAX_DYNAMIC_CARDS = 40
MAX_EXPANDABLE_CARDS = 120

JOB_LINK_HINTS = (
    "job",
    "jobs",
    "career",
    "careers",
    "vacancy",
    "vacancies",
    "position",
    "positions",
    "opportunity",
    "opportunities",
    "opening",
    "openings",
    "stelle",
    "stellen",
    "karriere",
    "emploi",
    "offre",
    "offres",
)

APPLY_HINTS = tuple(dict.fromkeys(STANDARD_APPLY_LABELS + ("application",)))

POST_APPLY_HINTS = STANDARD_POST_APPLY_LABELS

NEGATIVE_HINTS = tuple(
    dict.fromkeys(
        STANDARD_NEGATIVE_LABELS
        + (
            "contact",
            "about",
            "faq",
        )
    )
)

LISTING_PAGE_HINTS = (
    "job",
    "jobs",
    "career",
    "careers",
    "vacancy",
    "vacancies",
    "position",
    "positions",
    "stellen",
    "karriere",
    "emploi",
    "offres",
)

GENERIC_TITLES = (
    "jobs",
    "careers",
    "career",
    "vacancies",
    "positions",
    "open positions",
    "offene stellen",
    "karriere",
    "emploi",
)

DETAIL_CONTENT_MARKERS = (
    "responsibilities",
    "requirements",
    "qualifications",
    "benefits",
    "experience",
    "full time",
    "part time",
    "job description",
    "about the role",
    "what you'll do",
    "your profile",
    "your responsibilities",
    "your mission",
    "responsable",
    "missions",
    "profil",
    "anforderungen",
    "qualifikationen",
    "aufgaben",
    "dein profil",
    "deine aufgaben",
    "pensum",
    "arbeitsort",
)

DATE_TEXT_RE = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b")


def _normalize_url(url: str, base_url: str) -> str:
    resolved = urljoin(base_url, url or "")
    resolved, _ = urldefrag(resolved)
    return resolved.strip()


def _root_host(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _same_site(url: str, base_url: str) -> bool:
    return bool(_root_host(url)) and _root_host(url) == _root_host(base_url)


def _normalize_text(value: str) -> str:
    value = (value or "").strip().lower()
    return re.sub(r"\s+", " ", value)


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "job"


def _looks_like_job_card_text(title: str, text: str) -> bool:
    normalized_title = _normalize_text(title)
    normalized_text = _normalize_text(text)
    if not normalized_title or len(normalized_title.split()) < 2:
        return False
    if normalized_title in GENERIC_TITLES:
        return False
    if any(marker in normalized_text for marker in NEGATIVE_HINTS):
        return False

    has_date = bool(DATE_TEXT_RE.search(text or ""))
    has_percent = "%" in text
    has_jobish_marker = any(marker in normalized_text for marker in DETAIL_CONTENT_MARKERS)
    has_locationish_text = " in " in normalized_text or " bei " in normalized_text or " at " in normalized_text
    return bool(has_date or has_percent or has_jobish_marker or has_locationish_text or len(normalized_title.split()) >= 3)


def _path_segments(url: str) -> list[str]:
    try:
        path = urlparse(url).path or ""
    except Exception:
        path = ""
    return [segment for segment in path.lower().split("/") if segment]


def _is_listing_like_url(url: str) -> bool:
    segments = _path_segments(url)
    if not segments:
        return True
    last = segments[-1]
    return len(segments) <= 2 and last in LISTING_PAGE_HINTS


def _looks_like_job_detail_url(url: str, text: str) -> bool:
    segments = _path_segments(url)
    if not segments or _is_listing_like_url(url):
        return False

    haystack = _normalize_text(f"{url} {text}")
    if any(marker in haystack for marker in NEGATIVE_HINTS):
        return False

    has_hint = any(marker in haystack for marker in JOB_LINK_HINTS)
    has_numeric_id = any(re.search(r"\d{3,}", segment) for segment in segments)
    has_slug = any("-" in segment and len(segment) >= 12 for segment in segments)
    has_deep_path = len(segments) >= 3
    text_words = len(_normalize_text(text).split())

    return bool(
        has_hint
        and (
            has_numeric_id
            or has_slug
            or (has_deep_path and text_words >= 3)
        )
    )


def _has_apply_signal_in_html(html_text: str) -> bool:
    soup = BeautifulSoup(html_text, "html.parser")
    for node in soup.select("a[href], button, input[type='submit'], input[type='button'], form[action]"):
        text = " ".join(
            filter(
                None,
                [
                    node.get_text(" ", strip=True) if hasattr(node, "get_text") else "",
                    node.get("value") if hasattr(node, "get") else "",
                    node.get("aria-label") if hasattr(node, "get") else "",
                    node.get("title") if hasattr(node, "get") else "",
                    node.get("action") if hasattr(node, "get") else "",
                    node.get("href") if hasattr(node, "get") else "",
                ],
            )
        )
        haystack = _normalize_text(text)
        if any(hint in haystack for hint in APPLY_HINTS) and not any(negative in haystack for negative in NEGATIVE_HINTS):
            return True
    return False


def _source_settings(source: dict) -> dict:
    return source.get("settings") if isinstance(source.get("settings"), dict) else {}


def _listing_browser_mode(source: dict) -> str:
    value = str(source.get("browser_mode") or "headless").strip().lower()
    return value if value in {"headless", "headed"} else "headless"


def _listing_browser_headless(source: dict) -> bool:
    return _listing_browser_mode(source) != "headed"


def _listing_browser_wait_ms(source: dict) -> int:
    settings = _source_settings(source)
    try:
        if "listing_wait_ms" in settings:
            return max(0, int(settings.get("listing_wait_ms") or 0))
    except Exception:
        pass
    return 12000 if _listing_browser_mode(source) == "headed" else 0


def _listing_timeout_ms(source: dict | None = None) -> int:
    if not source:
        return LISTING_TIMEOUT_MS
    settings = _source_settings(source)
    try:
        value = int(settings.get("listing_timeout_ms") or LISTING_TIMEOUT_MS)
    except Exception:
        value = LISTING_TIMEOUT_MS
    return max(LISTING_TIMEOUT_MS, value)


def _skip_listing_cookie_dismiss(source: dict | None = None) -> bool:
    if not source:
        return False
    settings = _source_settings(source)
    return bool(settings.get("skip_listing_cookie_dismiss"))


def _settle_listing_page(page, source: dict | None = None) -> None:
    if not _skip_listing_cookie_dismiss(source):
        dismiss_cookie_banners(page)
    wait_ms = 0 if source is None else _listing_browser_wait_ms(source)
    if wait_ms > 0:
        try:
            page.wait_for_timeout(wait_ms)
        except Exception:
            pass
        if not _skip_listing_cookie_dismiss(source):
            dismiss_cookie_banners(page)


def fetch_html(url: str, session: requests.Session) -> str:
    response = session.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def fetch_html_dynamic(url: str, *, source: dict | None = None) -> str:
    with sync_playwright() as playwright:
        headless = LISTING_HEADLESS if source is None else _listing_browser_headless(source)
        timeout_ms = _listing_timeout_ms(source)
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass
        _settle_listing_page(page, source)
        for _ in range(3):
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(800)
        content = page.content()
        browser.close()
        return content


def _score_job_link(href: str, text: str) -> int:
    haystack = _normalize_text(f"{href} {text}")
    if any(marker in haystack for marker in NEGATIVE_HINTS):
        return 0
    if not _looks_like_job_detail_url(href, text):
        return 0

    score = 0
    if any(f"/{marker}" in haystack or f"-{marker}" in haystack for marker in JOB_LINK_HINTS):
        score += 3
    if any(marker in haystack for marker in JOB_LINK_HINTS):
        score += 2
    if "/job/" in haystack or "/jobs/" in haystack or "/careers/" in haystack:
        score += 2
    if any(re.search(r"\d{3,}", segment) for segment in _path_segments(href)):
        score += 2
    if any("-" in segment and len(segment) >= 12 for segment in _path_segments(href)):
        score += 1
    if len(text.strip()) > 8:
        score += 1
    return score


def collect_job_links(html_text: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    results: list[dict] = []
    seen: set[str] = set()

    for anchor in soup.select("a[href]"):
        href = _normalize_url(anchor.get("href", ""), base_url)
        if not href or href in seen or not _same_site(href, base_url):
            continue
        if href.rstrip("/") == base_url.rstrip("/"):
            continue

        text = " ".join(
            filter(
                None,
                [
                    anchor.get_text(" ", strip=True),
                    anchor.get("title"),
                    anchor.get("aria-label"),
                ],
            )
        )
        score = _score_job_link(href, text)
        if score < 5:
            continue

        seen.add(href)
        results.append({"url": href, "title": text or None, "score": score})

    results.sort(key=lambda item: (int(item.get("score") or 0), len(item.get("url") or "")), reverse=True)
    return results[:MAX_JOB_LINKS]


def _mark_dynamic_job_cards(page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const selectors = [
            "ui-result-list-item",
            "ui-result-list-item [role='link']",
            ".pfch-ui-rli__row",
            "li [role='link']",
            "[role='link'][tabindex]"
          ];
          const seen = new Set();
          const out = [];
          let idx = 0;
          document.querySelectorAll(selectors.join(",")).forEach((el) => {
            const clickable = el.matches("[role='link'], .pfch-ui-rli__row") ? el : (el.querySelector("[role='link'], .pfch-ui-rli__row") || el);
            const titleNode = clickable.querySelector("h1, h2, h3, h4") || el.querySelector("h1, h2, h3, h4");
            const title = (titleNode?.innerText || "").trim();
            const text = ((clickable.innerText || el.innerText) || "").trim();
            if (!title || !text) {
              return;
            }
            const key = `${title}||${text}`;
            if (seen.has(key)) {
              return;
            }
            seen.add(key);
            clickable.setAttribute("data-codex-job-card-index", String(idx));
            out.push({ index: idx, title, text });
            idx += 1;
          });
          return out;
        }
        """
    )


def _wait_for_dynamic_job_cards(page) -> None:
    selectors = [
        "ui-result-list-item",
        "ui-result-list-item [role='link']",
        ".pfch-ui-rli__row",
        "[role='link'][tabindex]",
    ]
    for _ in range(5):
        for selector in selectors:
            try:
                page.wait_for_selector(selector, timeout=2500)
                return
            except Exception:
                continue
        try:
            page.mouse.wheel(0, 1600)
            page.wait_for_timeout(700)
        except Exception:
            pass


def collect_dynamic_job_links(base_url: str, *, source: dict | None = None) -> list[dict]:
    with sync_playwright() as playwright:
        headless = LISTING_HEADLESS if source is None else _listing_browser_headless(source)
        timeout_ms = _listing_timeout_ms(source)
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.goto(base_url, timeout=timeout_ms, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass
        _settle_listing_page(page, source)
        _wait_for_dynamic_job_cards(page)
        for _ in range(2):
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(600)

        try:
            cards = _mark_dynamic_job_cards(page)
        except Exception:
            cards = []

        filtered_cards = [
            card for card in cards
            if _looks_like_job_card_text(str(card.get("title") or ""), str(card.get("text") or ""))
        ][:MAX_DYNAMIC_CARDS]

        results: list[dict] = []
        for card in filtered_cards:
            card_index = int(card.get("index") or 0)
            try:
                page.goto(base_url, timeout=timeout_ms, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    pass
                _settle_listing_page(page, source)
                _wait_for_dynamic_job_cards(page)
                for _ in range(2):
                    page.mouse.wheel(0, 1400)
                    page.wait_for_timeout(400)
                _mark_dynamic_job_cards(page)
                target = page.locator(f'[data-codex-job-card-index="{card_index}"]').first
                if target.count() == 0:
                    continue

                previous_url = page.url
                popup_page = None
                try:
                    with page.expect_popup(timeout=2500) as popup_info:
                        target.click(timeout=2500, force=True)
                    popup_page = popup_info.value
                except Exception:
                    try:
                        target.click(timeout=2500, force=True)
                    except Exception:
                        continue

                active_page = popup_page or page
                try:
                    active_page.wait_for_function(
                        "(previous) => window.location.href !== previous",
                        previous_url,
                        timeout=3000,
                    )
                except Exception:
                    pass
                try:
                    active_page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                except Exception:
                    pass
                try:
                    active_page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    pass

                detail_url = active_page.url
                if not detail_url or detail_url == previous_url:
                    if popup_page:
                        popup_page.close()
                    continue

                results.append(
                    {
                        "url": detail_url,
                        "title": str(card.get("title") or "").strip() or None,
                        "score": 10,
                    }
                )
                if popup_page:
                    popup_page.close()
            except Exception:
                continue

        browser.close()

    deduped: list[dict] = []
    seen_urls: set[str] = set()
    for item in results:
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(item)
    return deduped[:MAX_JOB_LINKS]


def merge_job_link_candidates(static_links: list[dict], dynamic_links: list[dict]) -> list[dict]:
    combined: list[dict] = []
    seen_urls: set[str] = set()
    for item in sorted(
        (static_links or []) + (dynamic_links or []),
        key=lambda entry: int(entry.get("score") or 0),
        reverse=True,
    ):
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        combined.append(item)
    return combined[:MAX_JOB_LINKS]


def _wait_for_expandable_cards(page, card_selector: str) -> None:
    for _ in range(6):
        try:
            page.wait_for_selector(card_selector, timeout=2500)
            return
        except Exception:
            try:
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(700)
            except Exception:
                pass


def _collect_expandable_card_summaries(page, settings: dict) -> list[dict]:
    card_selector = str(settings.get("card_selector") or "ui-result-list-item")
    clickable_selector = str(settings.get("clickable_selector") or ".pfch-ui-rli__row, [role='link']")
    title_selector = str(settings.get("title_selector") or "h1, h2, h3, h4")
    cards = page.evaluate(
        """
        ({ cardSelector, clickableSelector, titleSelector }) => {
          const out = [];
          const seen = new Set();
          document.querySelectorAll(cardSelector).forEach((item, idx) => {
            const clickable = item.querySelector(clickableSelector);
            const title = (item.querySelector(titleSelector)?.innerText || "").trim();
            const text = (item.innerText || "").trim();
            if (!clickable || !title || !text) return;
            const key = `${title}||${text}`;
            if (seen.has(key)) return;
            seen.add(key);
            out.push({ index: idx, title, text });
          });
          return out;
        }
        """,
        {
            "cardSelector": card_selector,
            "clickableSelector": clickable_selector,
            "titleSelector": title_selector,
        },
    )
    return list(cards or [])[:MAX_EXPANDABLE_CARDS]


def _extract_apply_url_from_expandable_item(page, item_locator, base_url: str, apply_labels: tuple[str, ...]) -> str | None:
    controls = item_locator.locator("a[href], button, [role='button'], input[type='button'], input[type='submit']")
    try:
        count = controls.count()
    except Exception:
        return None

    for idx in range(count):
        control = controls.nth(idx)
        try:
            if not control.is_visible():
                continue
            text = _normalize_text(
                control.inner_text(timeout=600)
                or control.get_attribute("value")
                or control.get_attribute("aria-label")
                or control.get_attribute("title")
                or ""
            )
        except Exception:
            continue
        if not text or not any(label in text for label in apply_labels):
            continue

        try:
            href = control.get_attribute("href") or ""
        except Exception:
            href = ""
        if href:
            return urljoin(base_url, href)

        popup_page = None
        previous_url = page.url
        try:
            with page.expect_popup(timeout=2500) as popup_info:
                control.click(timeout=2500, force=True)
            popup_page = popup_info.value
        except Exception:
            try:
                control.click(timeout=2500, force=True)
            except Exception:
                continue

        active_page = popup_page or page
        try:
            active_page.wait_for_load_state("domcontentloaded", timeout=APPLY_TIMEOUT_MS)
        except Exception:
            pass
        try:
            active_page.wait_for_load_state("networkidle", timeout=APPLY_TIMEOUT_MS)
        except Exception:
            pass
        current_url = active_page.url
        if popup_page:
            try:
                popup_page.close()
            except Exception:
                pass
        if current_url and current_url != previous_url:
            return current_url
    return None


def _crawl_expandable_cards_source(source: dict, known_urls: set[str] | None, run_id: str | None, stop_requested=None) -> dict:
    base_url = str(source.get("base_url") or "").strip()
    settings = _source_settings(source)
    listing_headless = _listing_browser_headless(source)
    listing_wait_ms = _listing_browser_wait_ms(source)
    timeout_ms = _listing_timeout_ms(source)
    card_selector = str(settings.get("card_selector") or "ui-result-list-item")
    clickable_selector = str(settings.get("clickable_selector") or ".pfch-ui-rli__row, [role='link']")
    title_selector = str(settings.get("title_selector") or "h1, h2, h3, h4")
    apply_labels = tuple(settings.get("apply_labels") or APPLY_HINTS)
    company_name = str(settings.get("company_name") or source.get("name") or "")

    known_urls = known_urls if known_urls is not None else load_known_job_urls()
    jobs_saved: list[dict] = []
    jobs_skipped_existing = 0
    jobs_failed = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=listing_headless)
        context = browser.new_context()
        page = context.new_page()
        page.goto(base_url, timeout=timeout_ms, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass
        _settle_listing_page(page, source)
        _wait_for_expandable_cards(page, card_selector)
        for _ in range(2):
            page.mouse.wheel(0, 1600)
            page.wait_for_timeout(500)

        summaries = _collect_expandable_card_summaries(page, settings)
        print(f"[generic_career] expandable cards collected {len(summaries)} from {base_url}")

        for card in summaries:
            if callable(stop_requested) and stop_requested():
                raise RuntimeError("retrieval_stop_requested")
            card_index = int(card.get("index") or 0)
            try:
                page.goto(base_url, timeout=timeout_ms, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    pass
                _settle_listing_page(page, source)
                _wait_for_expandable_cards(page, card_selector)
                item = page.locator(card_selector).nth(card_index)
                if item.count() == 0:
                    continue
                row = item.locator(clickable_selector).first
                if row.count() == 0:
                    continue
                dismiss_cookie_banners(page)
                row.click(timeout=3000, force=True)
                page.wait_for_timeout(700)

                title_locator = item.locator(title_selector).first
                if title_locator.count() > 0:
                    title = title_locator.inner_text(timeout=800).strip()
                else:
                    title = str(card.get("title") or "").strip()
                raw_text = item.inner_text(timeout=1200).strip()
                lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
                meta_line = ""
                for line in lines:
                    if "%" in line or " in " in line.lower():
                        meta_line = line
                        break
                date_line = lines[0] if lines and re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", lines[0]) else ""
                application_url = _extract_apply_url_from_expandable_item(page, item, base_url, apply_labels)

                synthetic_url = f"{base_url}#job={_slugify(date_line + '-' + title)}"
                job = {
                    "url": synthetic_url,
                    "url_add": synthetic_url,
                    "url_application": application_url,
                    "application_url": application_url,
                    "title": title,
                    "description": raw_text,
                    "date_posted": date_line or None,
                    "employment_type": None,
                    "hiring_org": company_name,
                    "job_location": meta_line or "",
                    "headhunter_agency": is_headhunter_application_url(application_url),
                    "source_id": source.get("source_id"),
                    "source_name": source.get("name"),
                    "source_type": source.get("type"),
                    "source_url": base_url,
                    "retrieval_run_id": run_id,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }

                known_job_urls = candidate_job_urls(job)
                if any(url in known_urls for url in known_job_urls):
                    jobs_skipped_existing += 1
                    continue

                job_key = save_job_record(job)
                known_urls.update(known_job_urls)
                automation_state = get_automation_state(job_key)
                job["job_key"] = job_key
                job["automation_possible"] = bool(application_url) and not job["headhunter_agency"]
                job["automation_completed"] = automation_state["application_done"]
                job["automation_status"] = (
                    "headhunter_agency" if job["headhunter_agency"] else automation_state["application_status"]
                )
                job["automation_user_questions_count"] = automation_state["user_questions_count"]
                jobs_saved.append(job)
                print(f"[generic_career] expandable saved {job_key} ({len(jobs_saved)}/{len(summaries)}) -> {title}")
                time.sleep(0.3)
            except Exception as exc:
                jobs_failed += 1
                print(f"[generic_career] expandable failed on card {card_index}: {exc}")
                continue

        browser.close()

    return {
        "source_id": source.get("source_id"),
        "source_name": source.get("name"),
        "jobs": jobs_saved,
        "jobs_found": len(summaries),
        "jobs_saved": len(jobs_saved),
        "jobs_skipped_existing": jobs_skipped_existing,
        "jobs_failed": jobs_failed,
    }


def _wait_for_clickable_cards(page, card_selector: str) -> None:
    for _ in range(6):
        try:
            page.wait_for_selector(card_selector, timeout=2500)
            return
        except Exception:
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    if frame.locator(card_selector).first.count() > 0:
                        return
                except Exception:
                    continue
            try:
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(700)
            except Exception:
                pass


def _collect_clickable_card_summaries(page, settings: dict) -> list[dict]:
    card_selector = str(settings.get("card_selector") or "")
    title_selector = str(settings.get("title_selector") or "h1, h2, h3, h4")
    meta_selector = str(settings.get("meta_selector") or "")
    cards: list[dict] = []
    seen_keys: set[str] = set()

    for frame_index, frame in enumerate(page.frames):
        try:
            frame_cards = frame.evaluate(
                """
                ({ cardSelector, titleSelector, metaSelector, frameIndex }) => {
                  const out = [];
                  const nodeText = (node) => {
                    if (!node) return "";
                    const visibleText = (node.innerText || "").trim();
                    if (visibleText) return visibleText;
                    return (node.textContent || "").trim();
                  };
                  document.querySelectorAll(cardSelector).forEach((card, idx) => {
                    const title = nodeText(card.querySelector(titleSelector));
                    const text = nodeText(card);
                    const meta = metaSelector ? nodeText(card.querySelector(metaSelector)) : "";
                    const anchor = card.closest("a[href]") || card.querySelector("a[href]");
                    const href = anchor ? new URL(anchor.getAttribute("href"), window.location.href).href : "";
                    if (!title || !text) return;
                    card.setAttribute("data-codex-click-card-index", String(idx));
                    out.push({ index: idx, title, text, meta, href, frameIndex });
                  });
                  return out;
                }
                """,
                {
                    "cardSelector": card_selector,
                    "titleSelector": title_selector,
                    "metaSelector": meta_selector,
                    "frameIndex": frame_index,
                },
            )
        except Exception:
            frame_cards = []

        for card in list(frame_cards or []):
            key = f"{card.get('title') or ''}||{card.get('text') or ''}"
            if not key.strip() or key in seen_keys:
                continue
            seen_keys.add(key)
            cards.append(card)

    return cards[:MAX_EXPANDABLE_CARDS]


def _open_clickable_card_detail_url(page, base_url: str, card_selector: str, card_index: int, settings: dict) -> str | None:
    timeout_ms = max(CLICKABLE_CARD_TIMEOUT_MS, _listing_timeout_ms({"settings": settings}))
    page.goto(base_url, timeout=timeout_ms, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=min(10000, timeout_ms))
    except Exception:
        pass
    dismiss_cookie_banners(page)
    _wait_for_clickable_cards(page, card_selector)

    card = page.locator(card_selector).nth(card_index)
    if card.count() == 0:
        return None

    previous_url = page.url

    try:
        direct_href = card.evaluate(
            """
            (el) => {
              const anchor = el.closest("a[href]") || el.querySelector("a[href]");
              if (!anchor) return "";
              try {
                return new URL(anchor.getAttribute("href"), window.location.href).href;
              } catch {
                return anchor.getAttribute("href") || "";
              }
            }
            """
        ) or ""
    except Exception:
        direct_href = ""
    if direct_href and direct_href != previous_url:
        print(f"[generic_career] clickable direct href resolved for card {card_index}: {direct_href}", flush=True)
        return direct_href

    clickable_selector = str(settings.get("clickable_selector") or "").strip()
    click_targets = []
    if clickable_selector:
        click_targets.append(card.locator(clickable_selector).first)
    click_targets.append(card.locator("a[href], [role='link'], button").first)
    click_targets.append(card)

    for target in click_targets:
        try:
            if target.count() == 0:
                continue
            target.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass

        popup_page = None
        try:
            with page.expect_popup(timeout=2500) as popup_info:
                target.click(timeout=2500, force=True)
            popup_page = popup_info.value
        except Exception:
            try:
                target.click(timeout=2500, force=True)
            except Exception:
                continue

        active_page = popup_page or page
        try:
            active_page.wait_for_function(
                "(previous) => window.location.href !== previous",
                previous_url,
                timeout=3500,
            )
        except Exception:
            pass
        try:
            active_page.wait_for_load_state("domcontentloaded", timeout=LISTING_TIMEOUT_MS)
        except Exception:
            pass
        try:
            active_page.wait_for_load_state("networkidle", timeout=2500)
        except Exception:
            pass
        detail_url = active_page.url
        if popup_page:
            try:
                popup_page.close()
            except Exception:
                pass
        if detail_url and detail_url != previous_url:
            print(f"[generic_career] clickable click resolved for card {card_index}: {detail_url}", flush=True)
            return detail_url
    return None


def _crawl_clickable_cards_source(source: dict, known_urls: set[str] | None, run_id: str | None, stop_requested=None) -> dict:
    base_url = str(source.get("base_url") or "").strip()
    settings = _source_settings(source)
    listing_headless = _listing_browser_headless(source)
    listing_wait_ms = _listing_browser_wait_ms(source)
    timeout_ms = _listing_timeout_ms(source)
    card_selector = str(settings.get("card_selector") or "")
    if not card_selector:
        raise RuntimeError("clickable_cards mode requires settings.card_selector")
    company_name = str(settings.get("company_name") or source.get("name") or "")

    known_urls = known_urls if known_urls is not None else load_known_job_urls()
    jobs_saved: list[dict] = []
    jobs_skipped_existing = 0
    jobs_failed = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=listing_headless)
        context = browser.new_context()
        page = context.new_page()
        page.goto(base_url, timeout=timeout_ms, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass
        _settle_listing_page(page, source)
        _wait_for_clickable_cards(page, card_selector)
        for _ in range(2):
            page.mouse.wheel(0, 1600)
            page.wait_for_timeout(500)

        summaries = _collect_clickable_card_summaries(page, settings)
        print(f"[generic_career] clickable cards collected {len(summaries)} from {base_url}", flush=True)
        browser.close()

    with requests.Session() as session:
        for card in summaries:
            if callable(stop_requested) and stop_requested():
                raise RuntimeError("retrieval_stop_requested")
            card_index = int(card.get("index") or 0)
            try:
                print(f"[generic_career] clickable processing card {card_index}", flush=True)
                detail_url = str(card.get("href") or "").strip()
                if detail_url:
                    print(f"[generic_career] clickable using collected href for card {card_index}: {detail_url}", flush=True)
                else:
                    print(f"[generic_career] clickable opening card {card_index} via Playwright", flush=True)
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=listing_headless)
                        context = browser.new_context()
                        page = context.new_page()
                        detail_url = _open_clickable_card_detail_url(page, base_url, card_selector, card_index, settings)
                        browser.close()
                if not detail_url:
                    print(f"[generic_career] clickable failed to open detail url for card {card_index}", flush=True)
                    jobs_failed += 1
                    continue
                if detail_url.rstrip("/") in known_urls:
                    jobs_skipped_existing += 1
                    continue

                detail_html = fetch_html(detail_url, session)
                detail = parse_detail(detail_html, detail_url)
                application_url = extract_application_url_from_html(detail_html, detail_url, base_url)
                if not application_url:
                    try:
                        application_url = discover_application_url(detail_url)
                    except Exception as exc:
                        print(f"[generic_career] clickable apply discovery error for {detail_url}: {exc}")
                        application_url = None

                has_apply_signal = bool(application_url) or _has_apply_signal_in_html(detail_html)
                if not bool(detail.get("detail_valid")) and not has_apply_signal:
                    continue

                job = {
                    "url": detail_url,
                    "url_add": detail_url,
                    "url_application": application_url,
                    "application_url": application_url,
                    "title": detail.get("title") or str(card.get("title") or "").strip() or detail_url,
                    "description": detail.get("description") or str(card.get("text") or ""),
                    "date_posted": detail.get("date_posted"),
                    "employment_type": None,
                    "hiring_org": company_name,
                    "job_location": detail.get("job_location") or str(card.get("meta") or ""),
                    "headhunter_agency": is_headhunter_application_url(application_url),
                    "source_id": source.get("source_id"),
                    "source_name": source.get("name"),
                    "source_type": source.get("type"),
                    "source_url": base_url,
                    "retrieval_run_id": run_id,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }

                known_job_urls = candidate_job_urls(job)
                if any(url in known_urls for url in known_job_urls):
                    jobs_skipped_existing += 1
                    continue

                job_key = save_job_record(job)
                known_urls.update(known_job_urls)
                automation_state = get_automation_state(job_key)
                job["job_key"] = job_key
                job["automation_possible"] = bool(application_url) and not job["headhunter_agency"]
                job["automation_completed"] = automation_state["application_done"]
                job["automation_status"] = (
                    "headhunter_agency" if job["headhunter_agency"] else automation_state["application_status"]
                )
                job["automation_user_questions_count"] = automation_state["user_questions_count"]
                jobs_saved.append(job)
                print(f"[generic_career] clickable saved {job_key} ({len(jobs_saved)}/{len(summaries)}) -> {detail_url}")
                time.sleep(0.3)
            except Exception as exc:
                jobs_failed += 1
                print(f"[generic_career] clickable failed on card {card_index}: {exc}")
                continue

    return {
        "source_id": source.get("source_id"),
        "source_name": source.get("name"),
        "jobs": jobs_saved,
        "jobs_found": len(summaries),
        "jobs_saved": len(jobs_saved),
        "jobs_skipped_existing": jobs_skipped_existing,
        "jobs_failed": jobs_failed,
    }


def _iter_jsonld(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_jsonld(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_jsonld(item)


def _jobposting_from_soup(soup: BeautifulSoup) -> dict | None:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or "")
        except Exception:
            continue
        for obj in _iter_jsonld(payload):
            if isinstance(obj, dict) and obj.get("@type") == "JobPosting":
                return obj
    return None


def parse_detail(html_text: str, detail_url: str) -> dict:
    soup = BeautifulSoup(html_text, "html.parser")
    jobposting = _jobposting_from_soup(soup)

    if jobposting:
        desc_html = jobposting.get("description") or ""
        desc_text = BeautifulSoup(desc_html, "html.parser").get_text(" ", strip=True)
        title = jobposting.get("title") or jobposting.get("name")
        hiring_org = ""
        if isinstance(jobposting.get("hiringOrganization"), dict):
            hiring_org = jobposting["hiringOrganization"].get("name") or ""
        locality = ""
        if isinstance(jobposting.get("jobLocation"), dict):
            address = jobposting["jobLocation"].get("address") or {}
            if isinstance(address, dict):
                locality = address.get("addressLocality") or ""
        return {
            "title": title,
            "description": desc_text,
            "date_posted": jobposting.get("datePosted"),
            "employment_type": jobposting.get("employmentType"),
            "hiring_org": hiring_org,
            "job_location": locality,
            "detail_source": "jobposting",
            "detail_valid": bool(title or desc_text),
        }

    title = ""
    if soup.find("h1"):
        title = soup.find("h1").get_text(" ", strip=True)
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    description = ""
    meta_description = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if meta_description:
        description = meta_description.get("content") or ""
    if not description:
        main_node = soup.find("main") or soup.find("article") or soup.find("body")
        if main_node:
            description = main_node.get_text(" ", strip=True)[:2000]

    description = re.sub(r"\s+", " ", description).strip()
    normalized_title = _normalize_text(title)
    normalized_description = _normalize_text(description)
    title_ok = bool(normalized_title) and normalized_title not in GENERIC_TITLES and len(normalized_title.split()) >= 2
    marker_count = sum(1 for marker in DETAIL_CONTENT_MARKERS if marker in normalized_description)
    detail_valid = bool(title_ok and len(description) >= 120 and marker_count >= 1)
    return {
        "title": title or detail_url,
        "description": description,
        "date_posted": None,
        "employment_type": None,
        "hiring_org": "",
        "job_location": "",
        "detail_source": "fallback",
        "detail_valid": detail_valid,
    }


def page_has_real_application_fields(page) -> bool:
    return page_has_application_fields(page)


def extract_application_url_from_html(html_text: str, detail_url: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html_text, "html.parser")

    for form in soup.select("form[action]"):
        action = _normalize_url(form.get("action", ""), detail_url)
        if action and action != detail_url:
            action_text = _normalize_text(form.get_text(" ", strip=True))
            if any(hint in action_text or hint in action.lower() for hint in APPLY_HINTS):
                return action

    for anchor in soup.select("a[href], button[onclick], [role='button'][onclick]"):
        href = ""
        text = anchor.get_text(" ", strip=True)
        if anchor.has_attr("href"):
            href = _normalize_url(anchor.get("href", ""), detail_url)
        elif anchor.has_attr("onclick"):
            match = re.search(r"""['"]((?:https?:)?//[^'"]+|/[^'"]+)['"]""", anchor.get("onclick", ""))
            if match:
                href = _normalize_url(match.group(1), detail_url)
        haystack = _normalize_text(f"{text} {href}")
        if not any(hint in haystack for hint in APPLY_HINTS):
            continue
        if any(negative in haystack for negative in NEGATIVE_HINTS):
            continue
        if href:
            return href

    if "type=\"file\"" in html_text.lower():
        return detail_url
    return None


def discover_application_url(detail_url: str) -> str | None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=APPLY_HEADLESS)
        context = browser.new_context()
        page = context.new_page()
        started_at = time.monotonic()

        def bounded_timeout(default_ms: int) -> int:
            remaining = APPLY_TOTAL_TIMEOUT_MS - int((time.monotonic() - started_at) * 1000)
            if remaining <= 0:
                raise TimeoutError(f"generic_career apply discovery exceeded {APPLY_TOTAL_TIMEOUT_MS}ms")
            return min(default_ms, remaining)

        page.goto(detail_url, timeout=APPLY_TIMEOUT_MS)
        settle_page(page, nav_timeout_ms=APPLY_NAV_TIMEOUT_MS, settle_ms=POST_LOAD_SETTLE_MS, timeout_for=bounded_timeout)
        dismiss_cookie_banners(page, click_timeout_ms=APPLY_CLICK_TIMEOUT_MS, timeout_for=bounded_timeout)

        if page_has_real_application_fields(page):
            current = page.url
            browser.close()
            return current
        clicked_any = False

        current_page = page
        for labels in (APPLY_HINTS, APPLY_HINTS, POST_APPLY_HINTS, POST_APPLY_HINTS):
            result = click_control_and_capture_target(
                current_page,
                labels,
                excluded_labels=NEGATIVE_HINTS,
                control_selector=DEFAULT_CONTROL_SELECTOR,
                click_timeout_ms=APPLY_CLICK_TIMEOUT_MS,
                nav_timeout_ms=APPLY_NAV_TIMEOUT_MS,
                timeout_for=bounded_timeout,
            )
            if not result:
                break
            if result["kind"] == "href":
                browser.close()
                return str(result.get("value") or "") or None
            current_page = result["value"]
            clicked_any = True
            if page_has_real_application_fields(current_page):
                current = current_page.url
                browser.close()
                return current

        current = current_page.url
        browser.close()
        if clicked_any and current:
            return current
        if current and current != detail_url:
            return current
        return None


def crawl_source(
    source: dict,
    *,
    pages: int | None = None,
    term: str = "",
    known_urls: set[str] | None = None,
    run_id: str | None = None,
    stop_requested=None,
) -> dict:
    del pages, term

    settings = _source_settings(source)
    if str(settings.get("mode") or "").strip().lower() == "expandable_cards":
        return _crawl_expandable_cards_source(source, known_urls, run_id, stop_requested=stop_requested)
    if str(settings.get("mode") or "").strip().lower() == "clickable_cards":
        return _crawl_clickable_cards_source(source, known_urls, run_id, stop_requested=stop_requested)

    base_url = str(source.get("base_url") or "").strip()
    if not base_url:
        raise RuntimeError(f"Source '{source.get('source_id')}' is missing base_url")

    listing_headless = _listing_browser_headless(source)
    known_urls = known_urls if known_urls is not None else load_known_job_urls()
    jobs_saved: list[dict] = []
    jobs_skipped_existing = 0
    jobs_failed = 0

    with requests.Session() as session:
        try:
            listing_html = fetch_html(base_url, session)
        except Exception:
            listing_html = fetch_html_dynamic(base_url, source=source)

        static_job_links = collect_job_links(listing_html, base_url)
        dynamic_job_links: list[dict] = []
        try:
            dynamic_job_links = collect_dynamic_job_links(base_url, source=source)
        except Exception as exc:
            print(f"[generic_career] dynamic card discovery error for {base_url}: {exc}")
        job_links = merge_job_link_candidates(static_job_links, dynamic_job_links)
        print(
            f"[generic_career] static links={len(static_job_links)} dynamic links={len(dynamic_job_links)} merged={len(job_links)}"
        )
        print(f"[generic_career] collected {len(job_links)} job detail links from {base_url}")

        for idx, item in enumerate(job_links, start=1):
            if callable(stop_requested) and stop_requested():
                raise RuntimeError("retrieval_stop_requested")
            detail_url = str(item.get("url") or "").strip()
            if not detail_url:
                continue
            if detail_url.rstrip("/") in known_urls:
                jobs_skipped_existing += 1
                continue

            try:
                try:
                    detail_html = fetch_html(detail_url, session)
                except Exception:
                    detail_html = fetch_html_dynamic(detail_url, source=source)

                detail = parse_detail(detail_html, detail_url)
                application_url = extract_application_url_from_html(detail_html, detail_url, base_url)
                if not application_url:
                    try:
                        application_url = discover_application_url(detail_url)
                    except Exception as exc:
                        print(f"[generic_career] apply discovery error for {detail_url}: {exc}")
                        application_url = None

                has_apply_signal = bool(application_url) or _has_apply_signal_in_html(detail_html)
                if not bool(detail.get("detail_valid")) and not has_apply_signal:
                    continue
                if detail.get("detail_source") != "jobposting" and not has_apply_signal:
                    continue

                job = {
                    "url": detail_url,
                    "url_add": detail_url,
                    "url_application": application_url,
                    "application_url": application_url,
                    "title": detail.get("title") or item.get("title") or detail_url,
                    "description": detail.get("description") or "",
                    "date_posted": detail.get("date_posted"),
                    "employment_type": detail.get("employment_type"),
                    "hiring_org": detail.get("hiring_org") or "",
                    "job_location": detail.get("job_location") or "",
                    "headhunter_agency": is_headhunter_application_url(application_url),
                    "source_id": source.get("source_id"),
                    "source_name": source.get("name"),
                    "source_type": source.get("type"),
                    "source_url": base_url,
                    "retrieval_run_id": run_id,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }

                known_job_urls = candidate_job_urls(job)
                if any(url in known_urls for url in known_job_urls):
                    jobs_skipped_existing += 1
                    continue

                job_key = save_job_record(job)
                known_urls.update(known_job_urls)
                automation_state = get_automation_state(job_key)
                job["job_key"] = job_key
                job["automation_possible"] = bool(application_url) and not job["headhunter_agency"]
                job["automation_completed"] = automation_state["application_done"]
                job["automation_status"] = (
                    "headhunter_agency" if job["headhunter_agency"] else automation_state["application_status"]
                )
                job["automation_user_questions_count"] = automation_state["user_questions_count"]
                jobs_saved.append(job)
                print(f"[generic_career] saved {job_key} from {get_registration_url(job) or detail_url} ({idx}/{len(job_links)})")
                time.sleep(0.4)
            except Exception as exc:
                jobs_failed += 1
                print(f"[generic_career] failed on {detail_url}: {exc}")
                continue

    return {
        "source_id": source.get("source_id"),
        "source_name": source.get("name"),
        "jobs": jobs_saved,
        "jobs_found": len(job_links),
        "jobs_saved": len(jobs_saved),
        "jobs_skipped_existing": jobs_skipped_existing,
        "jobs_failed": jobs_failed,
    }
