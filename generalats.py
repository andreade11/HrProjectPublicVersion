from playwright.sync_api import sync_playwright
from candidate import Candidate
from pathlib import Path
import hashlib
from datetime import datetime
from dataclasses import dataclass
import os
import json
import difflib
import time
import unicodedata
import re
import random
from ats_runtime import is_production_mode, load_runtime_answers, question_id, runtime_answer_for_field
from ats_openai import infer_answer_with_openai, infer_intent_with_openai
from intent_catalog import shared_keywords
from language_context import detect_language_from_url, normalize_language
from captcha_helper import (
    CaptchaSolverState,
    datadome_playwright_proxy,
    maybe_solve_datadome,
    maybe_solve_recaptcha,
)

# ============================================================
# CONFIG
# ============================================================

candidate = Candidate()
USED_INTENTS = {}
LAST_USED_INTENT = ""
ADD_CLICKED_FOR_LANG = set()
REQUIRED_TEXT_FIELDS = []
REQUIRED_DROPDOWNS = []
REQUIRED_CHECKBOXES = []
REQUIRED_SEGMENTS = []
INFERRED_FIELDS = []
USER_QUESTIONS = []
RECORDED_USER_QUESTION_IDS = set()
ATTACHMENT_INTENTS = ("resume", "cover letter", "other document")
OTHER_DOCUMENT_INDEX = 0
COVER_LETTER_USED = False
COVER_LETTER_USED_TYPE = ""
UNKNOWN_COUNTER = 0
COVER_LETTER_FILE_AVAILABLE = False
ACTIVE_FRAME_URL = None
RESCAN_REQUESTED = False
FILLED_DROPDOWNS = set()
PENDING_LANGUAGE_INDEX = 0
PENDING_LANGUAGE_STAGE = ""
PRODUCTION_MODE = is_production_mode(default=True)
RUNTIME_ANSWERS = load_runtime_answers()
ATS_SOURCE = "generalats"
SUBMIT_CHECK_PENDING = False
SUBMIT_PRECLICK_SIGNATURE = ""
SUBMIT_PRECLICK_URL = ""
SUBMIT_CHECK_ATTEMPTS = 0
APPLICATION_STATUS = "in_progress"
APPLICATION_DONE = False
CAPTCHA_STATE = CaptchaSolverState()

OPENAI_MODEL = "gpt-4o-mini"
OPENAI_CONFIDENCE_THRESHOLD = 0.6
OPENAI_BETWEEN_CALLS_DELAY = 0.6
APPLICATION_LANGUAGE = normalize_language(os.getenv("APP_LANGUAGE"), default="fr")
INTENTS = {
    "first name": ["first name", "firstname", "given name", "forename","name","prÃ©nom"],
    "last name": shared_keywords("last name", language=APPLICATION_LANGUAGE),
    "expected_salary":["expected salary","expected"],
    "full_name": shared_keywords("full name", language=APPLICATION_LANGUAGE),
    "email": shared_keywords("email", language=APPLICATION_LANGUAGE),
    "phone": shared_keywords("phone", language=APPLICATION_LANGUAGE),
    "phone country": shared_keywords("phone country", language=APPLICATION_LANGUAGE),
    "address": shared_keywords("address", language=APPLICATION_LANGUAGE),
    "city": shared_keywords("city", language=APPLICATION_LANGUAGE),
    "postcode": shared_keywords("postcode", language=APPLICATION_LANGUAGE),
    "country": ["country", "nationality","based in","NationalitÃ©"],
    "region": shared_keywords("region", language=APPLICATION_LANGUAGE),
    "linkedin": shared_keywords("linkedin", language=APPLICATION_LANGUAGE),
    "website": shared_keywords("website", language=APPLICATION_LANGUAGE),
    "gender": shared_keywords("gender", language=APPLICATION_LANGUAGE) + ["salutation", "title"],
    "date of birth": ["date of birth", "birth date", "birthdate", "dob","Date de naissance"],
    
    "availability": ["availability", "notice period", "start date","prÃ©avis","disponibilitÃ©","available"],
    "sponsorship": ["sponsorship","visa"],
    
    "workpermit": ["work permit", "work authorization", "right to work", "workpermit","Permis de travail"],
    
    "resume": shared_keywords("resume", language=APPLICATION_LANGUAGE),
    "cover letter": ["cover letter", "motivation letter", "cover_letter", "cover-letter", "motivation", "lettre de motivation"],
    "other document": shared_keywords("other document", language=APPLICATION_LANGUAGE),
    "privacy": shared_keywords("privacy", language=APPLICATION_LANGUAGE),
    "cookies": shared_keywords("cookies", language=APPLICATION_LANGUAGE),
    "submit": ["submit", "apply", "postuler", "send my application", "send application", "finish", "complete application","envoyer"],
    "continue": ["continue", "next", "save and continue", "proceed","etape","suivant"],
    "add": shared_keywords("add", language=APPLICATION_LANGUAGE),

    "language1_language":["language"],#combox
    "language1_fluenty":["native"],#chechbox
    "language1_level":["overall","level","niveau"],

    "language2_language":["language"],#combox
    "language2_fluenty":["native"],#chechbox
    "language2_level":["overall","level","niveau"],
}

INTENTS["first name"] = shared_keywords("first name", language=APPLICATION_LANGUAGE)
INTENTS["country"] = shared_keywords("country", language=APPLICATION_LANGUAGE)
INTENTS["date of birth"] = shared_keywords("date of birth", language=APPLICATION_LANGUAGE)
INTENTS["availability"] = shared_keywords("availability", language=APPLICATION_LANGUAGE)
INTENTS["workpermit"] = shared_keywords("workpermit", language=APPLICATION_LANGUAGE)
INTENTS["privacy"] = shared_keywords("privacy", language=APPLICATION_LANGUAGE)
INTENTS["submit"] = shared_keywords("submit", language=APPLICATION_LANGUAGE)
INTENTS["continue"] = shared_keywords("continue", language=APPLICATION_LANGUAGE)
INTENTS["cover letter"] = shared_keywords("cover letter", language=APPLICATION_LANGUAGE)


def apply_keyword_language(language: str | None) -> None:
    global APPLICATION_LANGUAGE
    APPLICATION_LANGUAGE = normalize_language(language, default="fr")
    os.environ["APP_LANGUAGE"] = APPLICATION_LANGUAGE
    INTENTS.update(
        {
            "first name": shared_keywords("first name", language=APPLICATION_LANGUAGE),
            "last name": shared_keywords("last name", language=APPLICATION_LANGUAGE),
            "full_name": shared_keywords("full name", language=APPLICATION_LANGUAGE),
            "email": shared_keywords("email", language=APPLICATION_LANGUAGE),
            "phone": shared_keywords("phone", language=APPLICATION_LANGUAGE),
            "phone country": shared_keywords("phone country", language=APPLICATION_LANGUAGE),
            "address": shared_keywords("address", language=APPLICATION_LANGUAGE),
            "city": shared_keywords("city", language=APPLICATION_LANGUAGE),
            "postcode": shared_keywords("postcode", language=APPLICATION_LANGUAGE),
            "country": shared_keywords("country", language=APPLICATION_LANGUAGE),
            "region": shared_keywords("region", language=APPLICATION_LANGUAGE),
            "linkedin": shared_keywords("linkedin", language=APPLICATION_LANGUAGE),
            "website": shared_keywords("website", language=APPLICATION_LANGUAGE),
            "gender": shared_keywords("gender", language=APPLICATION_LANGUAGE) + ["salutation", "title"],
            "date of birth": shared_keywords("date of birth", language=APPLICATION_LANGUAGE),
            "availability": shared_keywords("availability", language=APPLICATION_LANGUAGE),
            "workpermit": shared_keywords("workpermit", language=APPLICATION_LANGUAGE),
            "resume": shared_keywords("resume", language=APPLICATION_LANGUAGE),
            "cover letter": shared_keywords("cover letter", language=APPLICATION_LANGUAGE),
            "other document": shared_keywords("other document", language=APPLICATION_LANGUAGE),
            "privacy": shared_keywords("privacy", language=APPLICATION_LANGUAGE),
            "cookies": shared_keywords("cookies", language=APPLICATION_LANGUAGE),
            "submit": shared_keywords("submit", language=APPLICATION_LANGUAGE),
            "continue": shared_keywords("continue", language=APPLICATION_LANGUAGE),
            "add": shared_keywords("add", language=APPLICATION_LANGUAGE),
        }
    )


# ============================================================
# NORMALIZATION
# ============================================================

def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def keyword_matches(text: str, keyword: str) -> bool:
    haystack = normalize(text)
    needle = normalize(keyword)
    if not haystack or not needle:
        return False
    return bool(re.search(rf"(^|\s){re.escape(needle)}($|\s)", haystack))


def _extract_visible_page_text(page) -> str:
    target = pick_active_frame(page) or page
    chunks = []
    try:
        chunks.append(target.locator("h1, h2").all_inner_texts())
    except:
        pass
    try:
        body_text = target.locator("body").first.inner_text().strip()
        if body_text:
            chunks.append([body_text])
    except:
        pass
    flat = []
    for chunk in chunks:
        if isinstance(chunk, list):
            flat.extend(chunk)
        elif chunk:
            flat.append(str(chunk))
    return normalize(" ".join(flat))


def _page_state_signature(page) -> str:
    if _page_is_closed(page):
        return ""
    target = pick_active_frame(page) or page
    try:
        url = target.url or ""
    except:
        url = ""
    try:
        title = page.title() or ""
    except:
        title = ""
    visible = _extract_visible_page_text(page)[:700]
    raw = f"{normalize(url)}|{normalize(title)}|{visible}"
    if not raw.strip("|"):
        return ""
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _page_is_closed(page) -> bool:
    try:
        return bool(page.is_closed())
    except:
        return False


def _is_target_closed_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return "target page" in text and ("closed" in text or "context" in text or "browser" in text)


def _close_browser_safely(browser) -> None:
    try:
        browser.close()
    except:
        pass


def _current_page_url(page) -> str:
    try:
        target = pick_active_frame(page) or page
        return str(target.url or page.url or "")
    except:
        try:
            return str(page.url or "")
        except:
            return ""


def _submit_keywords() -> list[str]:
    keys = []
    for intent in ("submit", "continue"):
        for keyword in INTENTS.get(intent, []):
            norm = normalize(keyword)
            if norm:
                keys.append(norm)
    return list(dict.fromkeys(keys))


def _element_action_haystack(el) -> str:
    parts = []
    for attr in ("aria-label", "title", "value", "name", "id", "data-automation-id"):
        try:
            value = el.get_attribute(attr)
            if value:
                parts.append(value)
        except:
            pass
    try:
        txt = el.inner_text()
        if txt:
            parts.append(txt)
    except:
        pass
    return normalize(" ".join(parts))


def _has_visible_submit_intent_button(page) -> bool:
    target = pick_active_frame(page) or page
    keywords = _submit_keywords()
    if not keywords:
        return False
    candidates = target.locator("button, a, input[type='submit'], input[type='button'], [role='button']")
    try:
        count = candidates.count()
    except:
        return False
    for idx in range(count):
        el = candidates.nth(idx)
        try:
            if not el.is_visible():
                continue
        except:
            continue
        haystack = _element_action_haystack(el)
        if not haystack:
            continue
        for keyword in keywords:
            if keyword and keyword in haystack:
                return True
    return False


def _mark_submit_click_for_completion_check(page) -> None:
    global SUBMIT_CHECK_PENDING
    global SUBMIT_PRECLICK_SIGNATURE
    global SUBMIT_PRECLICK_URL
    global SUBMIT_CHECK_ATTEMPTS
    SUBMIT_CHECK_PENDING = True
    SUBMIT_PRECLICK_SIGNATURE = _page_state_signature(page)
    SUBMIT_PRECLICK_URL = _current_page_url(page)
    SUBMIT_CHECK_ATTEMPTS = 0


def _refresh_completion_state_after_submit(page) -> bool:
    global SUBMIT_CHECK_PENDING
    global SUBMIT_CHECK_ATTEMPTS
    global APPLICATION_STATUS
    global APPLICATION_DONE
    if not SUBMIT_CHECK_PENDING:
        return False
    if _page_is_closed(page):
        APPLICATION_STATUS = "completed"
        APPLICATION_DONE = True
        SUBMIT_CHECK_PENDING = False
        return True
    current_url = _current_page_url(page)
    if current_url and SUBMIT_PRECLICK_URL and normalize(current_url) != normalize(SUBMIT_PRECLICK_URL):
        APPLICATION_STATUS = "completed"
        APPLICATION_DONE = True
        SUBMIT_CHECK_PENDING = False
        print(f"GENERALATS: URL changed after submit: {SUBMIT_PRECLICK_URL} -> {current_url}")
        return True
    current_signature = _page_state_signature(page)
    if not current_signature or current_signature == SUBMIT_PRECLICK_SIGNATURE:
        APPLICATION_STATUS = "in_progress"
        APPLICATION_DONE = False
        return False
    no_submit_intent_button = not _has_visible_submit_intent_button(page)
    if no_submit_intent_button:
        APPLICATION_STATUS = "completed"
        APPLICATION_DONE = True
        SUBMIT_CHECK_PENDING = False
        return True
    APPLICATION_STATUS = "in_progress"
    APPLICATION_DONE = False
    SUBMIT_CHECK_PENDING = False
    return False


# ============================================================
# LABEL + CONTEXT
# ============================================================

def get_label_for_element(page, el):
    el_id = el.get_attribute("id")
    if el_id:
        lbl = page.locator(f'label[for="{el_id}"]')
        if lbl.count() > 0 and lbl.first.is_visible():
            return lbl.first.inner_text().strip()

    labelledby = el.get_attribute("aria-labelledby")
    if labelledby:
        for ref_id in labelledby.split():
            lbl = page.locator(f"[id='{ref_id}']")
            if lbl.count() > 0 and lbl.first.is_visible():
                text = lbl.first.inner_text().strip()
                if text:
                    return text

    aria_label = el.get_attribute("aria-label")
    if aria_label:
        return aria_label.strip()

    placeholder = el.get_attribute("placeholder")
    if placeholder:
        return placeholder.strip()

    return ""


def get_visible_label_text(page, el) -> str:
    el_id = el.get_attribute("id")
    if el_id:
        lbl = page.locator(f'label[for="{el_id}"]')
        if lbl.count() > 0 and lbl.first.is_visible():
            text = lbl.first.inner_text().strip()
            if text:
                return text

    labelledby = el.get_attribute("aria-labelledby")
    if labelledby:
        for ref_id in labelledby.split():
            lbl = page.locator(f"[id='{ref_id}']")
            if lbl.count() > 0 and lbl.first.is_visible():
                text = lbl.first.inner_text().strip()
                if text:
                    return text

    try:
        return el.evaluate(
            """
            (el) => {
              const clean = s => (s || "").replace(/\\s+/g, " ").trim();
              const lbl = el.closest("label");
              if (lbl && lbl.innerText) {
                const t = clean(lbl.innerText);
                return t || "";
              }
              return "";
            }
            """
        )
    except:
        return ""


def get_best_label_text(page, el) -> str:
    try:
        role = (el.get_attribute("role") or "").lower()
    except:
        role = ""
    if role == "combobox":
        try:
            return el.evaluate(
                """
                (el) => {
                  const clean = s => (s || "").replace(/\\s+/g, " ").trim();
                  const isJunk = (t) => {
                    if (!t) return true;
                    const v = t.trim().toLowerCase();
                    if (!v) return true;
                    if (v.length <= 2) return true;
                    if (["yes","no","true","false","select one","veuillez choisir","delete","clear","supprimer"].includes(v)) return true;
                    return false;
                  };
                  const ignoreSelector = '[role="option"],[role="listbox"],.multiselect-option,.multiselect-options,.multiselect-dropdown,.multiselect-single-label,.multiselect-single-label-text';
                  const textWithoutOptions = (root) => {
                    if (!root) return "";
                    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
                      acceptNode(node) {
                        if (!node || !node.parentElement) return NodeFilter.FILTER_REJECT;
                        if (node.parentElement.closest(ignoreSelector)) return NodeFilter.FILTER_REJECT;
                        return NodeFilter.FILTER_ACCEPT;
                      }
                    });
                    let out = "";
                    let n = walker.nextNode();
                    while (n) {
                      const t = clean(n.textContent || "");
                      if (t) out += (out ? " " : "") + t;
                      n = walker.nextNode();
                    }
                    return out.trim();
                  };
                  const findLabelForId = (id) => {
                    if (!id) return "";
                    const lbl = document.querySelector(`label[for="${CSS.escape(id)}"]`);
                    return lbl && lbl.innerText ? clean(lbl.innerText) : "";
                  };
                  const direct = findLabelForId(el.getAttribute("id"));
                  if (direct) return direct;
                  let p = el.parentElement;
                  let depth = 0;
                  while (p && depth < 4) {
                    const pid = p.getAttribute && p.getAttribute("id");
                    const lbl = findLabelForId(pid);
                    if (lbl) return lbl;
                    // Only look at previous siblings (and their descendants), not following ones
                    let sib = p.previousElementSibling;
                    while (sib) {
                      const t = textWithoutOptions(sib);
                      if (t && !isJunk(t)) return t;
                      sib = sib.previousElementSibling;
                    }
                    // If parent itself has label text before the input, use it
                    const tparent = textWithoutOptions(p);
                    if (tparent && !isJunk(tparent)) return tparent;
                    p = p.parentElement;
                    depth += 1;
                  }
                  return "";
                }
                """
            )
        except:
            pass
    label = get_visible_label_text(page, el)
    if label:
        return label
    try:
        return get_parent_visible_text(el)
    except:
        return ""


def get_element_location(el):
    try:
        return el.evaluate(
            """
            (el) => {
              const escapeCss = (value) => {
                try {
                  return CSS.escape(value);
                } catch {
                  return value.replace(/([^a-zA-Z0-9_-])/g, "\\\\$1");
                }
              };

              const selectorFor = (node) => {
                if (!node || !node.tagName) return "";
                if (node.id) return `#${escapeCss(node.id)}`;
                const parts = [];
                let cur = node;
                let guard = 0;
                while (cur && cur.tagName && guard < 6) {
                  let part = cur.tagName.toLowerCase();
                  if (cur.classList && cur.classList.length) {
                    const cls = Array.from(cur.classList).slice(0, 3).map(escapeCss);
                    if (cls.length) part += "." + cls.join(".");
                  }
                  const parent = cur.parentElement;
                  if (parent) {
                    const siblings = Array.from(parent.children).filter(n => n.tagName === cur.tagName);
                    if (siblings.length > 1) {
                      const index = siblings.indexOf(cur) + 1;
                      part += `:nth-of-type(${index})`;
                    }
                  }
                  parts.unshift(part);
                  cur = cur.parentElement;
                  guard += 1;
                }
                return parts.join(" > ");
              };

              const attrs = {};
              let decl = "";
              for (const attr of el.attributes || []) {
                attrs[attr.name] = attr.value;
                decl += ` ${attr.name}="${attr.value}"`;
              }

              return {
                selector: selectorFor(el),
                declaration: decl.trim(),
                attributes: attrs,
                tag: (el.tagName || "").toLowerCase(),
              };
            }
            """
        )
    except:
        return {"selector": "", "declaration": "", "attributes": {}, "tag": ""}


def get_context_text(el, raw_label: str):
    label_norm = normalize(raw_label)
    try:
        return el.evaluate(
            """
            (el, labelNorm) => {
              const clean = s => (s || "").replace(/\\s+/g, " ").trim();

              let n = el;
              while (n) {
                const ref = n.getAttribute && n.getAttribute("aria-labelledby");
                if (ref) {
                  const lbl = document.getElementById(ref);
                  if (lbl) return clean(lbl.innerText);
                }
                n = n.parentElement;
              }

              let p = el.parentElement;
              let last = null;
              while (p) {
                const t = clean(p.innerText);
                if (t && (!labelNorm || !t.toLowerCase().includes(labelNorm))) {
                  return t;
                }
                last = p;
                p = p.parentElement;
              }

              let s = last ? last.previousElementSibling : null;
              while (s) {
                const t = clean(s.innerText);
                if (t && (!labelNorm || !t.toLowerCase().includes(labelNorm))) {
                  return t;
                }
                s = s.previousElementSibling;
              }

              return "";
            }
            """,
            label_norm,
        )
    except:
        return ""


def get_parent_visible_text(el):
    return el.evaluate(
        """
        (el) => {
            const isJunk = (t) => {
                if (!t) return true;
                const v = t.trim().toLowerCase();
                if (!v) return true;
                if (v.length <= 2) return true;
                if (["yes", "no", "true", "false", "select one", "veuillez choisir", "delete", "clear", "supprimer"].includes(v)) return true;
                const tokens = v.split(/\\s+/).filter(Boolean);
                if (tokens.length > 0 && tokens.every(tok => ["yes","no","true","false","required","*","select","one"].includes(tok))) {
                    return true;
                }
                if (v === "*" || v === "required") return true;
                return false;
            };
            const clean = (s) => (s || "").trim();
            const isCombo = (el.getAttribute && (el.getAttribute("role") || "").toLowerCase() === "combobox");
            const ignoreSelector = '[role="option"],[role="listbox"],.multiselect-option,.multiselect-options,.multiselect-dropdown,.multiselect-single-label,.multiselect-single-label-text';
            const textWithoutOptions = (root) => {
                if (!root) return "";
                const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
                    acceptNode(node) {
                        if (!node || !node.parentElement) return NodeFilter.FILTER_REJECT;
                        if (node.parentElement.closest(ignoreSelector)) return NodeFilter.FILTER_REJECT;
                        return NodeFilter.FILTER_ACCEPT;
                    }
                });
                let out = "";
                let n = walker.nextNode();
                while (n) {
                    const t = clean(n.textContent || "");
                    if (t) out += (out ? " " : "") + t;
                    n = walker.nextNode();
                }
                return out.trim();
            };
            const textFromLabelSiblings = (root) => {
                if (!root) return "";
                const siblings = Array.from(root.children || []);
                const labelSibs = siblings.filter(s => s.querySelector && s.querySelector("label"));
                if (!labelSibs.length) return "";
                let out = "";
                for (const sib of labelSibs) {
                    const t = isCombo ? textWithoutOptions(sib) : (sib.innerText || "").trim();
                    if (t && !isJunk(t)) out += (out ? " " : "") + t;
                }
                return out.trim();
            };

            // 1) Nearest visible text in ancestors and siblings (closest-first)
            let node = el;
            let depth = 0;
            while (node && depth < 4) {
                const parent = node.parentElement;
                if (parent) {
                    let t = textFromLabelSiblings(parent);
                    if (!t) {
                        t = isCombo ? textWithoutOptions(parent) : (parent.innerText || "").trim();
                    }
                    if (!isJunk(t)) return t;
                }
                let prev = node.previousElementSibling;
                while (prev) {
                    if (prev) {
                        const t = isCombo ? textWithoutOptions(prev) : (prev.innerText || "").trim();
                        if (!isJunk(t)) return t;
                    }
                    prev = prev.previousElementSibling;
                }
                let next = node.nextElementSibling;
                while (next) {
                    if (next) {
                        const t = isCombo ? textWithoutOptions(next) : (next.innerText || "").trim();
                        if (!isJunk(t)) return t;
                    }
                    next = next.nextElementSibling;
                }
                node = parent;
                depth += 1;
            }

            // 2) Broader scan: previous/next siblings of ancestors
            let anc = el.parentElement;
            while (anc) {
                let prev = anc.previousElementSibling;
                while (prev) {
                    if (prev) {
                        const t = isCombo ? textWithoutOptions(prev) : (prev.innerText || "").trim();
                        if (!isJunk(t)) return t;
                    }
                    prev = prev.previousElementSibling;
                }
                let next = anc.nextElementSibling;
                while (next) {
                    if (next) {
                        const t = isCombo ? textWithoutOptions(next) : (next.innerText || "").trim();
                        if (!isJunk(t)) return t;
                    }
                    next = next.nextElementSibling;
                }
                anc = anc.parentElement;
            }
            return "";
        }
    """
    )


# ============================================================
# INTENT INFERENCE
# ============================================================

def infer_attachment_intent(el):
    page = el.page
    raw_label = get_label_for_element(page, el)
    raw_context = get_context_text(el, raw_label)
    attr_parts = []
    for attr in (
        "aria-label",
        "title",
        "placeholder",
        "data-placeholder",
        "data-field-id",
        "data-field-name",
        "name",
        "id",
        "accept",
    ):
        try:
            value = el.get_attribute(attr)
            if value:
                attr_parts.append(value)
        except:
            pass

    label = normalize(raw_label)
    context = normalize(" ".join([raw_context, *attr_parts]))

    for intent in ATTACHMENT_INTENTS:
        keywords = INTENTS.get(intent, [])
        if any(keyword_matches(label, k) for k in keywords):
            return intent

    for intent in ATTACHMENT_INTENTS:
        keywords = INTENTS.get(intent, [])
        if any(keyword_matches(context, k) for k in keywords):
            return intent

    return None


def infer_intent(el):
    tag = (el.evaluate("el => el.tagName") or "").lower()
    el_type = (el.get_attribute("type") or "").lower()

    if tag == "input" and el_type == "file":
        intent = infer_attachment_intent(el)
        return intent if intent in ATTACHMENT_INTENTS else None
    if tag == "input" and el_type in {"submit", "button", "reset"}:
        return None

    global PENDING_LANGUAGE_INDEX
    haystack_parts = []
    action_parts = []
    if tag == "a":
        attrs = ["aria-label", "title", "id", "name", "href", "data-job-name", "data-job-reference"]
    else:
        attrs = ["data-automation-id", "aria-label", "placeholder", "id", "name", "title", "data-cy"]
    for attr in attrs:
        v = el.get_attribute(attr)
        if v:
            haystack_parts.append(v.lower())
    # Submit/continue must rely only on the element's own action text/labels.
    for attr in ["aria-label", "title", "value"]:
        v = el.get_attribute(attr)
        if v:
            action_parts.append(v.lower())
    if tag not in {"select"}:
        try:
            txt = el.inner_text().lower()
            haystack_parts.append(txt)
            action_parts.append(txt)
        except:
            pass

    haystack = " ".join(haystack_parts)
    action_haystack = " ".join(action_parts)
    third_party_apply_markers = (
        "linkedin",
        "mit linkedin profil bewerben",
        "finest jobs",
        "mit finest jobs profil bewerben",
        "xing",
        "mit xing profil bewerben",
        "xing",
        "indeed",
        "seek profile",
    )
    upload_cta_markers = (
        "lebenslauf hochladen",
        "cv hochladen",
        "resume upload",
        "upload resume",
        "upload cv",
    )

    if tag in {"a", "button", "span"}:
        if tag == "a":
            try:
                link_text = " ".join(
                    [
                        str(el.inner_text() or ""),
                        str(el.get_attribute("href") or ""),
                    ]
                ).lower()
            except:
                link_text = haystack
            if any(marker in link_text for marker in ("datenschutz", "privacy", "consent", "cookies")):
                return None
        if any(marker in haystack for marker in third_party_apply_markers):
            if "linkedin" in haystack:
                return "linkedin"
            return None
        if any(marker in haystack for marker in upload_cta_markers):
            return None

    if tag == "input" and el_type == "checkbox":
        try:
            checkbox_label = el.evaluate(
                """
                (el) => {
                  const clean = s => (s || "").replace(/\\s+/g, " ").trim();
                  const id = (el.getAttribute("id") || "").trim();
                  if (id) {
                    const lbl = document.querySelector(`label[for="${id}"]`);
                    if (lbl) return clean(lbl.innerText || lbl.textContent || "");
                  }
                  const wrap = el.closest("label");
                  if (wrap) return clean(wrap.innerText || wrap.textContent || "");
                  const parent = el.parentElement;
                  if (parent) {
                    const lbl = parent.querySelector("label");
                    if (lbl) return clean(lbl.innerText || lbl.textContent || "");
                  }
                  return "";
                }
                """
            ) or ""
            raw_context = get_context_text(el, checkbox_label)
            parent_text = get_parent_visible_text(el)
            combined = " ".join([checkbox_label, raw_context, parent_text])
            inferred_checkbox = infer_intent_from_text(combined)
            if inferred_checkbox in {"privacy", "cookies"}:
                return inferred_checkbox
        except:
            pass

    file_keywords = (
        INTENTS.get("resume", [])
        + INTENTS.get("cover letter", [])
        + INTENTS.get("other document", [])
    )
    if PENDING_LANGUAGE_INDEX:
        for intent, keys in INTENTS.items():
            if intent == f"language{PENDING_LANGUAGE_INDEX}_language":
                for k in keys:
                    target_haystack = action_haystack if intent in {"submit", "continue"} else haystack
                    if keyword_matches(target_haystack, k):
                        return intent

    for intent, keys in INTENTS.items():
        used = USED_INTENTS.get(intent, 0)
        max_uses = get_max_uses(intent)
        if used >= max_uses:
            continue
        for k in keys:
            target_haystack = action_haystack if intent in {"submit", "continue"} else haystack
            if keyword_matches(target_haystack, k):
                if intent.startswith("language") and USED_INTENTS.get(intent, 0) >= get_max_uses(intent):
                    continue
                if intent in {"resume", "cover letter", "other document"} and USED_INTENTS.get(intent, 0) >= get_max_uses(intent):
                    continue
                if intent == "add" and any(keyword_matches(haystack, fk) for fk in file_keywords):
                    continue
                if intent in {"resume", "cover letter", "other document"}:
                    if not (tag == "input" and el_type == "file"):
                        continue
                if intent == "phone country":
                    if not any(
                        keyword_matches(haystack, term)
                        for term in ("phone", "mobile", "telephone", "tel", "portable", "indicatif", "dial", "code")
                    ):
                        continue
                if intent == "phone" and (el.get_attribute("role") or "").lower() == "combobox":
                    if keyword_matches(haystack, "phone") and keyword_matches(haystack, "country"):
                        return "phone country"
                if intent == "phone":
                    if not any(keyword_matches(haystack, term) for term in ("phone", "mobile", "telephone", "tel", "portable")):
                        continue
                return intent

    try:
        page = el.page
        raw_label = get_label_for_element(page, el)
        raw_context = get_context_text(el, raw_label)
        parent_text = get_parent_visible_text(el)
        combined = " ".join([raw_label, raw_context, parent_text])
        inferred = infer_intent_from_text(combined)
        if inferred:
            if inferred in {"submit", "continue"}:
                return None
            return inferred
    except:
        pass

    return None


def infer_intent_from_text(text_value):
    if not text_value:
        return None
    haystack = text_value.lower()
    file_keywords = (
        INTENTS.get("resume", [])
        + INTENTS.get("cover letter", [])
        + INTENTS.get("other document", [])
    )
    for intent, keys in INTENTS.items():
        used = USED_INTENTS.get(intent, 0)
        max_uses = get_max_uses(intent)
        if used >= max_uses:
            continue
        for k in keys:
            if keyword_matches(haystack, k):
                if intent in {"resume", "cover letter", "other document"}:
                    # Do not infer file intents from plain text contexts.
                    continue
                if intent == "add" and any(keyword_matches(haystack, fk) for fk in file_keywords):
                    continue
                return intent
    return None


def is_required_element(el):
    aria_required = (el.get_attribute("aria-required") or "").lower()
    aria_label = (el.get_attribute("aria-label") or "").lower()
    # Direct required attribute/prop on the element.
    try:
        if el.get_attribute("required") is not None:
            return True
    except:
        pass
    if aria_required == "true" or "required" in aria_label:
        return True
    try:
        return el.evaluate(
            """
            (el) => {
              const hasAsteriskMarker = (node) => {
                if (!node) return false;
                const text = ((node.innerText || node.textContent || "")).replace(/\s+/g, " ").trim();
                if (text === "*") return true;
                if (text.endsWith(" *")) return true;
                if (text.includes("*")) {
                  const marker = node.querySelector && node.querySelector(".asterisk, [class*='asterisk'], [aria-hidden='true']");
                  if (marker && ((marker.innerText || marker.textContent || "").replace(/\s+/g, " ").trim() === "*")) {
                    return true;
                  }
                }
                return false;
              };

              if (el.matches && el.matches(":required")) return true;
              // For custom comboboxes, look for nearby required fake inputs.
              const role = (el.getAttribute && el.getAttribute("role")) ? el.getAttribute("role").toLowerCase() : "";
              if (role === "combobox") {
                const root = el.closest(".multiselect") || el.parentElement || el;
                const fake = root.querySelector(".multiselect-fake-input[required]");
                if (fake) return true;
              }
              const hasRequiredToken = (node) => {
                if (!node || !node.getAttribute) return false;
                for (const attr of node.attributes || []) {
                  const v = (attr.value || "").toLowerCase();
                  const n = (attr.name || "").toLowerCase();
                  if (n.includes("required")) return true;
                  if (v.includes("required")) return true;
                }
                return false;
              };

              const id = (el.getAttribute && el.getAttribute("id")) ? el.getAttribute("id").trim() : "";
              if (id) {
                const forLabel = document.querySelector(`label[for="${id}"]`);
                if (forLabel && (hasRequiredToken(forLabel) || hasAsteriskMarker(forLabel))) return true;
              }

              const labelledby = (el.getAttribute && el.getAttribute("aria-labelledby"))
                ? el.getAttribute("aria-labelledby").trim()
                : "";
              if (labelledby) {
                for (const ref of labelledby.split(/\s+/).filter(Boolean)) {
                  const lbl = document.getElementById(ref);
                  if (lbl && (hasRequiredToken(lbl) || hasAsteriskMarker(lbl))) return true;
                }
              }

              let parent = el.parentElement;
              let depth = 0;
              while (parent && depth < 3) {
                if (hasRequiredToken(parent)) return true;
                if (hasAsteriskMarker(parent)) return true;
                const label = parent.querySelector("label");
                if (label && hasRequiredToken(label)) return true;
                if (label && hasAsteriskMarker(label)) return true;
                parent = parent.parentElement;
                depth += 1;
              }
              return false;
            }
            """
        )
    except:
        return False


def is_dropzone_upload(el) -> bool:
    try:
        if (el.get_attribute("data-form-field") or "") == "dropzone-upload":
            return True
        cls = (el.get_attribute("class") or "").lower()
        if "dropzone" in cls.split():
            return True
        return el.evaluate(
            """
            (el) => {
              const field = el.closest('[data-form-field="dropzone-upload"]');
              if (field) return true;
              if (el.classList && el.classList.contains("dropzone")) return true;
              const text = (el.innerText || "").toLowerCase();
              return text.includes("click to upload a file") || text.includes("drag and drop");
            }
            """
        )
    except:
        return False


def _file_input_has_visible_control(el) -> bool:
    try:
        tag = (el.evaluate("el => el.tagName") or "").lower()
        el_type = (el.get_attribute("type") or "").lower()
        if tag != "input" or el_type != "file":
            return False
        return bool(
            el.evaluate(
                """
                (el) => {
                  const isVisible = (node) => {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity || 1) === 0) {
                      return false;
                    }
                    const rect = node.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                  };
                  const id = el.getAttribute("id") || "";
                  if (id) {
                    const label = document.querySelector(`label[for="${CSS.escape(id)}"]`);
                    if (isVisible(label)) return true;
                  }
                  const wrapper = el.closest(".ats_input-group--file, .ats_input-group, .form-group, .field, .file, [class*='file']");
                  if (!wrapper) return false;
                  if (isVisible(wrapper.querySelector("label, button, [role='button'], .ats_input--button"))) return true;
                  return isVisible(wrapper.querySelector("input[type='text'], .ats_input--filelabel"));
                }
                """
            )
        )
    except:
        return False


# Try to infer file intent from dropzone attributes (id/data-category/label).
def infer_dropzone_intent(el) -> str | None:
    try:
        data_cat = (el.get_attribute("data-category") or "").lower()
    except:
        data_cat = ""
    try:
        el_id = (el.get_attribute("id") or "").lower()
    except:
        el_id = ""

    raw = " ".join([data_cat, el_id])
    norm = normalize(raw)
    if "cover" in norm:
        return "cover letter"
    if "other" in norm or "support" in norm or "additional" in norm:
        return "other document"
    if "resume" in norm or "cv" in norm or "curriculum" in norm:
        return "resume"

    # Fallback to label/context text if attributes are empty.
    try:
        page = el.page
        raw_label = get_label_for_element(page, el)
        raw_context = get_context_text(el, raw_label)
        parent_text = get_parent_visible_text(el)
        combined = " ".join([raw_label, raw_context, parent_text])
        return infer_intent_from_text(combined)
    except:
        return None


def _find_file_input_near_dropzone(el):
    try:
        handle = el.evaluate_handle(
            """
            (el) => {
              const isFile = (n) => n && n.tagName === "INPUT" && (n.type || "").toLowerCase() === "file";
              const byLabel = () => {
                const lbl = el.querySelector && el.querySelector("label[for]");
                if (!lbl) return null;
                const id = lbl.getAttribute("for");
                if (!id) return null;
                const target = document.getElementById(id);
                return isFile(target) ? target : null;
              };
              const collect = (root) => {
                if (!root || !root.querySelectorAll) return [];
                return Array.from(root.querySelectorAll('input[type="file"]'));
              };

              let found = byLabel();
              if (found) return found;

              let inputs = collect(el);
              if (inputs.length) return inputs[0];

              const root = el.closest("form, [data-form-field], .form-field, .field, .field-container, .form-group") || el.parentElement;
              inputs = collect(root);
              if (inputs.length) return inputs[0];

              let p = el.parentElement;
              let depth = 0;
              while (p && depth < 3) {
                inputs = collect(p);
                if (inputs.length) return inputs[0];
                p = p.parentElement;
                depth += 1;
              }
              return null;
            }
            """
        )
        return handle.as_element()
    except:
        return None

# ============================================================
# FILL HELPERS
# ============================================================

def can_use_intent(intent: str) -> bool:
    if not intent:
        return False
    if USED_INTENTS.get(intent, 0) >= get_max_uses(intent):
        return False
    USED_INTENTS[intent] = USED_INTENTS.get(intent, 0) + 1
    global LAST_USED_INTENT
    LAST_USED_INTENT = intent
    return True


def get_max_uses(intent: str) -> int:
    if intent.startswith("language"):
        return 1  
    if intent == "other document":
        return len(get_otherdocument_paths())
    if intent in {"resume", "email"}:
        return 2
    return 1

def fill_text(el, intent: str, label_text: str = ""):
    def _current_value() -> str:
        try:
            return el.input_value() or ""
        except:
            return ""

    def _set_value(value: str):
        if not value:
            return
        if _current_value().strip():
            return
        try:
            el.click(force=True)
        except:
            pass
        for method in (
            lambda: el.fill(value),
            lambda: el.type(value, delay=20),
            lambda: el.evaluate(
                """
                (el, val) => {
                  el.value = val;
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                }
                """,
                value,
            ),
        ):
            try:
                method()
            except:
                pass
            if _current_value().strip():
                break

    def _confirm_value_accepted(expected_value: str = "", press_tab: bool = False) -> bool:
        before_action = _current_value().strip()
        expected_norm = normalize(expected_value) if expected_value else ""
        if press_tab:
            try:
                el.page.wait_for_timeout(1000)
            except:
                pass
            try:
                el.press("Tab")
            except:
                pass
        try:
            el.page.wait_for_timeout(300)
        except:
            pass
        current_value = _current_value().strip()
        if expected_norm:
            accepted = normalize(current_value) == expected_norm
        else:
            accepted = bool(current_value)
        try:
            print(
                f"[input-accept] intent='{intent}' accepted={accepted} "
                f"before_action='{before_action}' value='{current_value}' expected='{expected_value}'"
            )
        except:
            pass
        return accepted

    if intent == "phone":
        number = str(getattr(candidate, "phone_number", "") or "")
        if not number:
            return
        _set_value(number)
        return

    if intent == "availability":
        label_norm = normalize(label_text)
        try:
            tag = (el.evaluate("el => el.tagName") or "").lower()
        except:
            tag = ""
        role = (el.get_attribute("role") or "").lower()
        is_dropdown_like = role == "combobox" or tag == "select"
        use_date = "notice" in label_norm or not is_dropdown_like
        if use_date:
            value = str(getattr(candidate, "noticeperiodDATE", "") or "")
        else:
            value = str(getattr(candidate, "noticeperiod", "") or "")
        _set_value(value)
        if use_date and value:
            _confirm_value_accepted(expected_value=value, press_tab=True)
        return

    if intent == "date of birth":
        dob = getattr(candidate, "datebirth", {}) or {}
        day = str(dob.get("day", "") or "").zfill(2)
        month = str(dob.get("month", "") or "").zfill(2)
        year = str(dob.get("year", "") or "")
        if not (day and month and year):
            return
        try:
            hint = " ".join(
                [
                    str(el.get_attribute("placeholder") or ""),
                    str(el.get_attribute("aria-label") or ""),
                    str(el.get_attribute("title") or ""),
                    str(el.get_attribute("name") or ""),
                    str(el.get_attribute("id") or ""),
                    str(label_text or ""),
                ]
            ).lower()
        except:
            hint = str(label_text or "").lower()
        if "yyyy-mm-dd" in hint or "date" == (el.get_attribute("type") or "").lower():
            value = f"{year}-{month}-{day}"
        elif "mm/dd/yyyy" in hint or "mm-dd-yyyy" in hint:
            value = f"{month}/{day}/{year}"
        elif "dd/mm/yyyy" in hint or "dd-mm-yyyy" in hint:
            value = f"{day}/{month}/{year}"
        else:
            value = f"{day}.{month}.{year}"
        _set_value(value)
        _confirm_value_accepted(expected_value=value, press_tab=True)
        return

    value = _candidate_value_for_intent(intent)
    _set_value(value)
    _confirm_value_accepted(expected_value=value)


def fill_file(el, intent: str):
    global COVER_LETTER_USED
    global COVER_LETTER_USED_TYPE
    global COVER_LETTER_FILE_AVAILABLE
    if intent == "resume":
        el.set_input_files(candidate.resume_path)
        el.page.wait_for_timeout(2000)
    elif intent == "cover letter":
        COVER_LETTER_FILE_AVAILABLE = True
        COVER_LETTER_USED = True
        COVER_LETTER_USED_TYPE = "file"
        el.set_input_files(candidate.cover_letter_path)
    elif intent == "other document":
        path = next_otherdocument_path()
        if path:
            el.set_input_files(path)


def _pick_file_path_for_intent(intent: str) -> str | None:
    if intent == "resume":
        return candidate.resume_path
    if intent == "cover letter":
        return candidate.cover_letter_path
    if intent == "other document":
        return next_otherdocument_path()
    return None


def _pick_random_fallback_file_path() -> str | None:
    paths = []
    for path in get_otherdocument_paths():
        if path and os.path.exists(path):
            paths.append(path)
    if not paths:
        return None
    return random.choice(paths)


def _set_files_via_filechooser(el, intent: str) -> bool:
    global COVER_LETTER_USED
    global COVER_LETTER_USED_TYPE
    global COVER_LETTER_FILE_AVAILABLE
    try:
        path = _pick_file_path_for_intent(intent)
        if not path:
            return False
        page = el.page
        with page.expect_file_chooser(timeout=2000) as fc_info:
            try:
                el.click(force=True)
            except:
                page.evaluate("el => el.click()", el)
        fc = fc_info.value
        fc.set_files(path)
        if intent == "cover letter":
            COVER_LETTER_FILE_AVAILABLE = True
            COVER_LETTER_USED = True
            COVER_LETTER_USED_TYPE = "file"
        return True
    except:
        return False


def selection_matches_select_option(el, target_text: str) -> bool:
    try:
        selected_text = el.evaluate(
            """
            (el) => {
              const option = el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex] : null;
              return option ? (option.textContent || option.innerText || "") : "";
            }
            """
        ) or ""
    except:
        selected_text = ""
    selected_norm = normalize(selected_text)
    target_norm = normalize(target_text)
    return bool(
        selected_norm
        and target_norm
        and (selected_norm == target_norm or selected_norm in target_norm or target_norm in selected_norm)
    )


def select_from_combobox(el, desired_text: str, prefer_options: bool = False):
    if not desired_text:
        return False
    try:
        el.click(force=True)
        el.page.wait_for_timeout(200)
    except:
        pass
    try:
        tag = (el.evaluate("el => el.tagName") or "").lower()
    except:
        tag = ""
    if tag == "select":
        try:
            matched = _best_option_from_options(desired_text, get_dropdown_options(el))
            target = matched or desired_text
            el.select_option(label=target)
            el.page.wait_for_timeout(300)
            return selection_matches_select_option(el, desired_text)
        except:
            try:
                matched = _best_option_from_options(desired_text, get_dropdown_options(el))
                if matched:
                    selected = el.evaluate(
                        """
                        (el, target) => {
                          const clean = s => (s || "").replace(/\\s+/g, " ").trim().toLowerCase();
                          const t = clean(target);
                          for (const option of Array.from(el.options || [])) {
                            const text = clean(option.textContent || option.innerText || "");
                            if (text === t) {
                              el.value = option.value;
                              el.dispatchEvent(new Event("input", { bubbles: true }));
                              el.dispatchEvent(new Event("change", { bubbles: true }));
                              return true;
                            }
                          }
                          return false;
                        }
                        """,
                        matched,
                    )
                    el.page.wait_for_timeout(300)
                    return bool(selected) and selection_matches_select_option(el, desired_text)
            except:
                pass
        return False
    try:
        cls = (el.get_attribute("class") or "").lower()
    except:
        cls = ""
    is_custom_selectmenu = tag == "span" and "ui-selectmenu" in cls
    if is_custom_selectmenu:
        try:
            target_norm = normalize(desired_text)
        except:
            target_norm = ""
        if target_norm:
            try:
                for _ in range(120):
                    current = _active_option_text_raw(el)
                    if current and normalize(current) == target_norm:
                        el.page.keyboard.press("Enter")
                        el.page.wait_for_timeout(300)
                        return True
                    el.page.keyboard.press("ArrowDown")
                    el.page.wait_for_timeout(120)
            except:
                pass
        try:
            print(f"[dropdown-select] exact option click failed for target='{desired_text}'")
        except:
            pass
        return False

    def dropdown_text_matches(current_text: str, target_text: str) -> bool:
        current_norm = normalize(current_text)
        target_norm = normalize(target_text)
        if not current_norm or not target_norm:
            return False
        if current_norm == target_norm:
            return True
        return current_norm in target_norm or target_norm in current_norm

    def selection_matches_target(target_text: str) -> bool:
        if tag == "select":
            return selection_matches_select_option(el, target_text)
        try:
            current_value = (el.input_value() or "").strip()
        except:
            current_value = ""
        displayed = _dropdown_display_value(el)
        active = _active_option_text_raw(el)
        return (
            dropdown_text_matches(current_value, target_text)
            or dropdown_text_matches(displayed, target_text)
            or dropdown_text_matches(active, target_text)
        )

    def click_visible_matching_option(target_text: str) -> bool:
        try:
            options = el.page.locator("[role='option'], .multiselect-option, li[role='option']")
            count = options.count()
        except:
            count = 0
        visible = []
        for idx in range(count):
            opt = options.nth(idx)
            try:
                if not opt.is_visible():
                    continue
                text = (opt.inner_text() or "").strip()
            except:
                text = ""
            if text:
                visible.append((text, opt))
        if not visible:
            return False
        texts = [text for text, _ in visible]
        best = _best_option_from_options(target_text, texts)
        if not best:
            return False
        for text, opt in visible:
            if text != best:
                continue
            try:
                opt.click(force=True)
                try:
                    print(f"[dropdown-select] visible option click matched target='{target_text}' option='{text}'")
                except:
                    pass
                return True
            except:
                return False
        return False

    def _reset_dropdown_input() -> None:
        try:
            el.click(force=True)
            el.page.wait_for_timeout(150)
        except:
            pass
        for key in ("Control+A", "Backspace"):
            try:
                el.press(key)
            except:
                pass
            try:
                el.page.keyboard.press(key)
            except:
                pass

    def _finish_success() -> bool:
        try:
            el.page.keyboard.press("Escape")
        except:
            pass
        try:
            el.evaluate("el => el.blur && el.blur()")
        except:
            pass
        return True

    def _attempt_keyboard_selection(*, use_arrowdown: bool) -> bool:
        _reset_dropdown_input()
        try:
            el.page.keyboard.type(desired_text, delay=20)
            el.page.wait_for_timeout(1000)
            if click_visible_matching_option(desired_text):
                el.page.wait_for_timeout(250)
                return selection_matches_target(desired_text)
            if use_arrowdown:
                el.page.keyboard.press("ArrowDown")
                el.page.wait_for_timeout(150)
            el.page.keyboard.press("Enter")
            el.page.wait_for_timeout(250)
        except:
            return False
        return selection_matches_target(desired_text)

    try:
        if _attempt_keyboard_selection(use_arrowdown=True):
            return _finish_success()
        try:
            print(f"[dropdown-select] retrying without arrowdown target='{desired_text}' displayed='{_dropdown_display_value(el)}'")
        except:
            pass
        if _attempt_keyboard_selection(use_arrowdown=False):
            return _finish_success()
        try:
            print(f"[dropdown-select] selection verification failed target='{desired_text}' displayed='{_dropdown_display_value(el)}'")
        except:
            pass
        return False
    except:
        return False


def _dropdown_display_value(el) -> str:
    try:
        return (
            el.evaluate(
                """
                (el) => {
                  const clean = s => (s || "").replace(/\\s+/g, " ").trim();
                  const root = el.closest(".multiselect") || el.parentElement || el;
                  for (const selector of [
                    ".ui-selectmenu-text",
                    ".button_label",
                    ".multiselect-single-label-text",
                    ".multiselect-single-label",
                    ".select2-selection__rendered",
                    ".select2-selection__choice",
                    "[id$='-container']"
                  ]) {
                    const node = root.querySelector(selector);
                    if (node) {
                      const text = clean(node.innerText || node.textContent || "");
                      if (text) return text;
                    }
                  }
                  if (el.matches && el.matches(".select2-selection__rendered, .select2-selection__choice, [id$='-container']")) {
                    const ownText = clean(el.innerText || el.textContent || "");
                    if (ownText) return ownText;
                  }
                  return "";
                }
                """
            ) or ""
        ).strip()
    except:
        return ""


def _is_special_multiselect_widget(el, tag: str, role: str) -> bool:
    try:
        cls = (el.get_attribute("class") or "").lower()
        haspopup = (el.get_attribute("aria-haspopup") or "").lower()
    except:
        cls = ""
        haspopup = ""
    if tag == "button" and "ui-multiselect" in cls:
        return True
    if haspopup == "listbox" and tag in {"button", "span"}:
        return True
    if "ui-multiselect" in cls or "multiselect" in cls:
        return True
    return role == "combobox" and "multiselect" in cls


def _special_multiselect_options(el) -> list[str]:
    try:
        el.click(force=True)
        el.page.wait_for_timeout(300)
    except:
        pass
    options = []
    try:
        options = el.evaluate(
            """
            (el) => {
              const clean = s => (s || "").replace(/\\s+/g, " ").trim();
              const out = [];
              const menus = Array.from(document.querySelectorAll(".ui-multiselect-menu, [role='listbox']"))
                .filter(node => {
                  const style = window.getComputedStyle(node);
                  return style.display !== "none" && style.visibility !== "hidden";
                });
              const menu = menus.length ? menus[menus.length - 1] : null;
              const candidates = menu
                ? Array.from(menu.querySelectorAll(".ui-multiselect-checkboxes li label, .ui-multiselect-checkboxes label, label, [role='option']"))
                : [];
              for (const node of candidates) {
                const text = clean(node.innerText || node.textContent || "");
                if (text && text !== "---" && !out.includes(text)) out.push(text);
              }
              return out;
            }
            """
        ) or []
    except:
        options = []
    if not options:
        try:
            el.page.keyboard.press("ArrowDown")
            el.page.wait_for_timeout(200)
        except:
            pass
        try:
            first = _active_option_text_raw(el)
        except:
            first = ""
        if first:
            options.append(first)
            seen = {first}
            previous = first
            same_option_rounds = 0
            for _ in range(160):
                try:
                    el.page.keyboard.press("ArrowDown")
                    el.page.wait_for_timeout(120)
                except:
                    break
                current = _active_option_text_raw(el)
                if not current:
                    break
                if current == previous:
                    same_option_rounds += 1
                    if same_option_rounds >= 2:
                        break
                else:
                    same_option_rounds = 0
                previous = current
                if current in seen:
                    continue
                seen.add(current)
                options.append(current)
    try:
        el.page.keyboard.press("Escape")
    except:
        pass
    seen = set()
    deduped = []
    for opt in options:
        value = str(opt or "").strip()
        if not value or value == "---" or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _select_first_special_multiselect_option(el) -> bool:
    options = _special_multiselect_options(el)
    if not options:
        return False
    return _select_special_multiselect_option(el, options[0])


def _select_special_multiselect_option(el, desired_text: str) -> bool:
    if not desired_text:
        return False
    try:
        el.click(force=True)
        el.page.wait_for_timeout(300)
    except:
        pass
    try:
        matched = el.evaluate(
            """
            (el, target) => {
              const clean = s => (s || "").replace(/\\s+/g, " ").trim().toLowerCase();
              const t = clean(target);
              const nodes = Array.from(document.querySelectorAll(
                ".ui-multiselect-checkboxes li label, .ui-multiselect-checkboxes label, [role='listbox'] label, [role='listbox'] [role='option']"
              ));
              for (const node of nodes) {
                const text = clean(node.innerText || node.textContent || "");
                if (text && text === t) {
                  node.click();
                  return true;
                }
              }
              for (const node of nodes) {
                const text = clean(node.innerText || node.textContent || "");
                if (text && (text.includes(t) || t.includes(text))) {
                  node.click();
                  return true;
                }
              }
              return false;
            }
            """,
            desired_text,
        )
    except:
        matched = False
    if not matched:
        try:
            target_norm = normalize(desired_text)
        except:
            target_norm = ""
        if target_norm:
            try:
                el.click(force=True)
                el.page.wait_for_timeout(250)
            except:
                pass
            try:
                for _ in range(120):
                    current = _active_option_text_raw(el)
                    if current and normalize(current) == target_norm:
                        el.page.keyboard.press("Enter")
                        el.page.wait_for_timeout(300)
                        matched = True
                        break
                    el.page.keyboard.press("ArrowDown")
                    el.page.wait_for_timeout(120)
            except:
                pass
    try:
        el.page.keyboard.press("Escape")
    except:
        pass
    return bool(matched)


def _candidate_value_for_intent(intent: str) -> str:
    if not intent:
        return ""
    intent_norm = normalize(intent)
    candidates = [intent, intent.replace(" ", "_"), intent.replace(" ", "")]
    for attr in candidates:
        if hasattr(candidate, attr):
            value = getattr(candidate, attr)
            if value is None:
                return ""
            if isinstance(value, (str, int, float, bool)):
                return str(value)
            return str(value)
    for attr, value in candidate.__dict__.items():
        attr_norm = normalize(str(attr).replace("_", " "))
        if attr_norm == intent_norm:
            if value is None:
                return ""
            return str(value)
    return ""


def _candidate_values_for_intent(intent: str) -> list[str]:
    value = _candidate_value_for_intent(intent)
    values = [value] if value else []
    attr_candidates = [intent, intent.replace(" ", "_"), intent.replace(" ", "")]
    for attr in attr_candidates:
        try:
            localized = candidate.value_for_language(attr, APPLICATION_LANGUAGE)
        except Exception:
            localized = ""
        if localized is not None:
            values.append(str(localized))
        try:
            raw_value = object.__getattribute__(candidate, attr)
        except Exception:
            raw_value = ""
        if raw_value is not None:
            values.append(str(raw_value))
        try:
            i18n = object.__getattribute__(candidate, f"{attr}_i18n")
        except Exception:
            i18n = {}
        if isinstance(i18n, dict):
            values.extend(str(item) for item in i18n.values() if item not in {None, ""})

    deduped = []
    seen = set()
    for item in values:
        item = str(item or "").strip()
        key = normalize(item)
        if not item or not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _option_from_candidate_values(intent: str, options: list[str], *, strict: bool = False) -> tuple[str, str]:
    for value in _candidate_values_for_intent(intent):
        matched = _strict_option_from_options(value, options) if strict else _best_option_from_options(value, options)
        if matched:
            return matched, value
    return "", ""


def _best_option_from_options(candidate_value: str, options: list[str]) -> str:
    if not candidate_value or not options:
        return ""
    target = normalize(candidate_value)
    best_opt = ""
    best_score = 0.0
    for opt in options:
        opt_norm = normalize(opt)
        if not opt_norm:
            continue
        if opt_norm == target:
            return opt
        if target in opt_norm or opt_norm in target:
            return opt
        score = difflib.SequenceMatcher(None, target, opt_norm).ratio()
        if score > best_score:
            best_score = score
            best_opt = opt
    return best_opt


def _strict_option_from_options(candidate_value: str, options: list[str]) -> str:
    if not candidate_value or not options:
        return ""
    target = normalize(candidate_value)
    if not target:
        return ""
    for opt in options:
        opt_norm = normalize(opt)
        if opt_norm and opt_norm == target:
            return opt
    return ""


def _infer_intent_with_openai(label: str) -> dict:
    return infer_intent_with_openai(label, INTENTS, OPENAI_MODEL)


def _infer_answer_with_openai(label: str, field_type: str, options: list[str]) -> dict:
    candidate_dict = {
        k: v
        for k, v in candidate.__dict__.items()
        if not k.startswith("_") and isinstance(v, (str, int, float, bool, dict))
    }
    return infer_answer_with_openai(
        label,
        field_type,
        options,
        candidate_dict=candidate_dict,
        model=OPENAI_MODEL,
    )


def _record_user_question(label: str, field_type: str, options: list[str], reason: str, confidence: float):
    qid = question_id(ATS_SOURCE, label, field_type, options)
    if qid in RECORDED_USER_QUESTION_IDS:
        return
    RECORDED_USER_QUESTION_IDS.add(qid)
    USER_QUESTIONS.append(
        {
            "question_id": qid,
            "label": label,
            "field_type": field_type,
            "options": options,
            "reason": reason,
            "confidence": confidence,
        }
    )
def is_element_filled(el) -> bool:
    try:
        tag = (el.evaluate("el => el.tagName") or "").lower()
    except:
        tag = ""
    if tag in {"input", "textarea"}:
        try:
            t = (el.get_attribute("type") or "").lower()
            if t in {"checkbox", "radio"}:
                return bool(el.is_checked())
        except:
            pass
        try:
            existing = el.input_value()
            if existing and existing.strip():
                return True
        except:
            pass
    if tag == "select":
        try:
            current = el.input_value()
            if current and current.strip():
                return True
        except:
            pass
    return False


def append_unique(items, item, key="label"):
    if not item:
        return
    if key and isinstance(item, dict):
        value = normalize(item.get(key) or "")
        item_options = sorted(normalize(option) for option in item.get("options", []) if normalize(option))
        if value:
            for existing in items:
                if not isinstance(existing, dict):
                    continue
                existing_value = normalize(existing.get(key) or "")
                existing_options = sorted(normalize(option) for option in existing.get("options", []) if normalize(option))
                if existing_value == value and (not item_options or item_options == existing_options):
                    return
    items.append(item)


def get_dropdown_options(el):
    try:
        tag = (el.evaluate("el => el.tagName") or "").lower()
    except:
        tag = ""
    options = []
    if tag == "select":
        try:
            options = el.evaluate(
                """
                (el) => {
                  const out = [];
                  const opts = Array.from(el.options || []);
                  for (const o of opts) {
                    const t = (o.label || o.textContent || o.value || "").trim();
                    if (t) out.push(t);
                  }
                  return out;
                }
                """
            ) or []
        except:
            try:
                opts = el.locator("option")
                for i in range(opts.count()):
                    opt = opts.nth(i)
                    try:
                        text = opt.inner_text().strip()
                    except:
                        text = ""
                    if text:
                        options.append(text)
            except:
                pass
        # De-dupe while preserving order.
        seen = set()
        deduped = []
        for opt in options:
            if opt in seen:
                continue
            seen.add(opt)
            deduped.append(opt)
        return deduped
    try:
        el.click(force=True)
        el.page.wait_for_timeout(200)
    except:
        pass
    try:
        listbox_id = el.get_attribute("aria-controls") or el.get_attribute("aria-owns") or ""
        if listbox_id:
            opts = el.page.locator(f"#{listbox_id} [role='option']")
        else:
            opts = el.page.locator("[role='listbox'] [role='option']")
        if not listbox_id:
            try:
                lb = el.page.locator("[role='listbox']").filter(has=el)
                if lb.count() > 0:
                    opts = lb.first.locator("[role='option']")
            except:
                pass
        try:
            opts.first.wait_for(timeout=800)
        except:
            pass
        for i in range(opts.count()):
            opt = opts.nth(i)
            try:
                text = opt.inner_text().strip()
            except:
                text = ""
            if text:
                options.append(text)
    except:
        pass
    try:
        el.page.keyboard.press("Escape")
    except:
        pass
    if options:
        seen = set()
        deduped = []
        for opt in options:
            if opt in seen:
                continue
            seen.add(opt)
            deduped.append(opt)
        return deduped
    return options


def _active_option_text(el):
    try:
        print("[dropdown] aria-activedescendant:", el.get_attribute("aria-activedescendant"))
    except:
        pass
    try:
        active_id = el.get_attribute("aria-activedescendant") or ""
    except:
        active_id = ""
    if active_id:
        try:
            active = el.page.locator(f"#{active_id}")
            text = active.inner_text().strip()
            if text:
                return text
        except:
            pass
    try:
        active = el.page.locator(
            "[role='option'][aria-selected='true'], "
            "[role='option'][data-highlighted='true'], "
            "[role='option'][aria-current='true']"
        ).first
        text = active.inner_text().strip()
        if text:
            print("[dropdown] active option via aria-selected/data-highlighted/aria-current:", text)
            return text
    except:
        pass
    try:
        opts = el.page.locator("[role='option']")
        count = opts.count()
        print("[dropdown] options count:", count)
        sample = []
        for i in range(min(count, 5)):
            try:
                t = opts.nth(i).inner_text().strip()
            except:
                t = ""
            if t:
                sample.append(t)
        if sample:
            print("[dropdown] options sample:", sample)
    except:
        pass
    return ""


def _active_option_text_raw(el):
    try:
        active_id = el.get_attribute("aria-activedescendant") or ""
    except:
        active_id = ""
    if not active_id:
        try:
            active_id = el.evaluate(
                """
                (el) => {
                  const root = el.closest(".multiselect") || el;
                  const combo = root.querySelector(
                    '[aria-activedescendant], input[role="combobox"], input[aria-controls], [role="combobox"]'
                  );
                  if (combo && combo.getAttribute) {
                    return combo.getAttribute("aria-activedescendant") || "";
                  }
                  return "";
                }
                """
            )
        except:
            active_id = ""
    if active_id:
        try:
            active = el.page.locator(f"#{active_id}")
            text = active.inner_text().strip()
            if text:
                try:
                    print(f"[dropdown-active] id={active_id} text='{text}'")
                except:
                    pass
                return text
        except:
            pass
    try:
        active = el.page.locator(
            "[role='option'][aria-selected='true'], "
            "[role='option'][data-highlighted='true'], "
            "[role='option'][aria-current='true']"
        ).first
        text = active.inner_text().strip()
        if text:
            try:
                print(f"[dropdown-active] fallback text='{text}'")
            except:
                pass
            return text
    except:
        pass
    return ""


def _is_dropdown_filled(el) -> bool:
    try:
        v = el.input_value()
        if v and v.strip():
            return True
    except:
        pass
    try:
        return el.evaluate(
            """
            (el) => {
              const clean = s => (s || "").replace(/\\s+/g, " ").trim();
              if (el.tagName === "SELECT") {
                const option = el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex] : null;
                const text = option ? clean(option.textContent || option.innerText || "") : "";
                return Boolean(text && text !== "---" && !/^select|selectionnez|veuillez/i.test(text));
              }
              const root = el.closest(".multiselect") || el.parentElement || el;
              const label = root.querySelector(
                ".multiselect-single-label-text, .multiselect-single-label, .select2-selection__rendered, .select2-selection__choice, [id$='-container']"
              );
              if (label && clean(label.innerText || label.textContent || "").replace(/^×\\s*/, "")) return true;
              if (el.matches && el.matches(".select2-selection__rendered, .select2-selection__choice, [id$='-container']")) {
                const ownText = clean(el.innerText || el.textContent || "").replace(/^×\\s*/, "");
                if (ownText) return true;
              }
              const selected = root.querySelector('[role="option"][aria-selected="true"]');
              if (selected && selected.innerText && selected.innerText.trim()) return true;
              return false;
            }
            """
        )
    except:
        return False


def _dropdown_unique_key(el) -> str:
    try:
        key = el.get_attribute("data-gats-uid") or ""
    except:
        key = ""
    if key:
        return key
    try:
        key = el.evaluate(
            """
            (el) => {
              if (el.dataset && el.dataset.gatsUid) return el.dataset.gatsUid;
              const uid = "gats-" + Math.random().toString(36).slice(2);
              if (el.dataset) el.dataset.gatsUid = uid;
              return uid;
            }
            """
        )
    except:
        key = ""
    return key or ""


def get_dropdown_options_by_navigation(el, max_steps=200):
    options = []
    try:
        el.click(force=True)
        el.page.wait_for_timeout(200)
    except:
        pass
    try:
        el.page.keyboard.press("ArrowDown")
        el.page.wait_for_timeout(200)
    except:
        pass
    try:
        el.page.keyboard.press("ArrowDown")
        el.page.wait_for_timeout(200)
    except:
        pass
    first = _active_option_text_raw(el)
    if not first:
        try:
            first = _active_option_text_raw(el)
        except:
            pass
    if not first:
        return options
    options.append(first)
    seen = {first}
    same_option_rounds = 0
    previous = first
    for _ in range(max_steps):
        try:
            el.page.keyboard.press("ArrowDown")
            el.page.wait_for_timeout(200)
        except:
            break
        current = _active_option_text_raw(el)
        if not current:
            break
        if current == first:
            break
        if current == previous:
            same_option_rounds += 1
            if same_option_rounds >= 2:
                break
        else:
            same_option_rounds = 0
        previous = current
        if current in seen:
            continue
        seen.add(current)
        options.append(current)
    return options


def select_first_option(el):
    try:
        tag = (el.evaluate("el => el.tagName") or "").lower()
    except:
        tag = ""
    try:
        el.click(force=True)
        el.page.wait_for_timeout(200)
    except:
        pass
    try:
        el.page.keyboard.press("ArrowDown")
    except:
        try:
            el.page.keyboard.press("ArrowDown")
        except:
            pass


def confirm_dropdown_selection(el):
    searchable = False
    try:
        searchable = el.evaluate(
            """
            (el) => {
              const root = el.closest(".multiselect") || el;
              const inp = root.querySelector(
                'input[type="text"], input.multiselect-search, input[role="combobox"], [contenteditable="true"]'
              );
              return !!inp;
            }
            """
        )
    except:
        searchable = False
    try:
        if searchable:
            el.page.keyboard.type("a", delay=20)
            print("TYPED A")
            el.page.wait_for_timeout(500)
        el.page.keyboard.press("Enter")
        el.page.wait_for_timeout(500)
        print("TYPED ENTER 1")
    except:
        try:
            el.page.keyboard.press("Enter")
            print("TYPED ENTER 2")
        except:
            pass
    try:
        el.page.keyboard.press("Escape")
        el.page.wait_for_timeout(500)
        print("ESCAPE")
    except:
        pass


def record_required_text(el, fill_value: str):
    if is_element_filled(el):
        return
    label = get_best_label_text(el.page, el)
    location = get_element_location(el)
    if label:
        append_unique(REQUIRED_TEXT_FIELDS, {"label": label, "location": location})
    # Do not click during recording to avoid changing the selected state.
    try:
        el.fill(fill_value)
    except:
        try:
            el.type(fill_value, delay=20)
        except:
            pass
    try:
        el.page.wait_for_timeout(1000)
    except:
        pass


def record_required_dropdown(el):
    label = get_best_label_text(el.page, el)
    try:
        tag = (el.evaluate("el => el.tagName") or "").lower()
    except:
        tag = ""
    intent = infer_intent_from_text(label) if label else None
    options = []
    if intent:
        options = get_dropdown_options(el)
        if not options and tag != "select":
            options = get_dropdown_options_by_navigation(el)
    else:
        if tag == "select":
            options = get_dropdown_options(el)
        else:
            options = get_dropdown_options_by_navigation(el)
        if not options:
            options = get_dropdown_options(el)
    location = get_element_location(el)
    if label:
        append_unique(
            REQUIRED_DROPDOWNS,
            {"label": label, "options": options, "location": location},
        )
        print(f"[record] dropdown label='{label}' options={len(options)}")


def record_required_checkbox(el):
    label = get_best_label_text(el.page, el)
    options = ["true", "false"]
    try:
        info = _checkbox_group_info(el)
        if info:
            if info.get("label"):
                label = info.get("label")
            if info.get("options"):
                options = info.get("options")
    except:
        pass

    location = get_element_location(el)
    if label:
        append_unique(
            REQUIRED_CHECKBOXES,
            {"label": label, "options": options, "location": location},
        )
        print(f"[record] checkbox label='{label}' options={len(options)}")
    try:
        if not el.is_checked():
            el.click(force=True)
    except:
        try:
            el.click(force=True)
        except:
            pass


def get_segment_options(el):
    try:
        return el.evaluate(
            """
            (el) => {
              const parent = el.parentElement;
              if (!parent) return [];
              const buttons = Array.from(parent.querySelectorAll("button"));
              return buttons.map(b => (b.innerText || "").trim()).filter(Boolean);
            }
            """
        )
    except:
        return []


def record_required_segment(el):
    options = get_segment_options(el)
    label = ""
    try:
        label = el.evaluate(
            """
            (el) => {
              const clean = s => (s || "").replace(/\\s+/g, " ").trim();
              const field = el.closest(".ashby-application-form-field-entry");
              if (!field) return "";
              const label = field.querySelector("label");
              if (label && label.innerText) return clean(label.innerText);
              return "";
            }
            """
        )
    except:
        label = ""

    def clean_label(text: str) -> str:
        if not text:
            return ""
        opt_norm = {normalize(o) for o in options if o}
        parts = []
        for line in text.splitlines():
            t = line.strip()
            if not t:
                continue
            if normalize(t) in opt_norm:
                continue
            parts.append(t)
        return " ".join(parts).strip()

    if not label:
        label = get_best_label_text(el.page, el)
        label = clean_label(label)

    location = get_element_location(el)
    if label:
        append_unique(
            REQUIRED_SEGMENTS,
            {"label": label, "options": options, "location": location},
        )
        print(f"[record] segment label='{label}' options={len(options)}")
    try:
        btn_text = el.inner_text().strip()
    except:
        btn_text = ""
    print(f"[segment] label='{label}' btn='{btn_text}'")
    try:
        el.click(force=True)
    except:
        pass


def record_unknown_question(el, fill_value: str | None = None):
    global UNKNOWN_COUNTER
    try:
        tag = (el.evaluate("el => el.tagName") or "").lower()
    except:
        tag = ""
    role = (el.get_attribute("role") or "").lower()
    if is_element_filled(el):
        return

    question = get_parent_visible_text(el)
    if not question:
        try:
            question = get_visible_label_text(el.page, el)
        except:
            question = ""
    if tag == "select" or role == "combobox":
        record_required_dropdown(el)
        return
    if tag in {"input", "textarea"}:
        UNKNOWN_COUNTER += 1
        if fill_value is None:
            fill_value = f"unknown{UNKNOWN_COUNTER}"
            if question and "cover letter" in question.lower():
                fill_value = "coverletterrequired"
        record_required_text(el, fill_value)
        return


def is_cover_letter_field(el) -> bool:
    try:
        tag = (el.evaluate("el => el.tagName") or "").lower()
    except:
        tag = ""
    if tag not in {"input", "textarea"}:
        return False
    haystack_parts = []
    for attr in ("name", "id", "placeholder", "aria-label", "title"):
        v = el.get_attribute(attr)
        if v:
            haystack_parts.append(v.lower())
    haystack = " ".join(haystack_parts)
    return "cover letter" in haystack or "cover_letter" in haystack


def get_otherdocument_paths():
    paths = []
    for idx in range(1, 6):
        attr = f"otherdocument{idx}_path"
        if hasattr(candidate, attr):
            value = getattr(candidate, attr)
            if value:
                paths.append(value)
    if not paths and hasattr(candidate, "diploma_path"):
        if candidate.diploma_path:
            paths.append(candidate.diploma_path)
    return paths


def next_otherdocument_path():
    global OTHER_DOCUMENT_INDEX
    paths = get_otherdocument_paths()
    if OTHER_DOCUMENT_INDEX >= len(paths):
        return ""
    path = paths[OTHER_DOCUMENT_INDEX]
    OTHER_DOCUMENT_INDEX += 1
    return path


def _job_key_from_url(url: str) -> str:
    override = os.getenv("JOB_KEY", "").strip()
    if override:
        return override
    normalized = (url or "").strip().lower().rstrip("/")
    if not normalized:
        return "job_unknown"
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
    date_prefix = datetime.now().strftime("%d%m%Y")
    return f"{date_prefix}_{digest[:16]}"


def save_required_questions(url: str):
    if not PRODUCTION_MODE:
        return
    base_dir = Path(__file__).resolve().parent
    target_dir = base_dir / "FichesJobs"
    target_dir.mkdir(parents=True, exist_ok=True)
    job_key = _job_key_from_url(url)
    target_path = target_dir / f"{job_key}.json"
    if target_path.exists():
        try:
            existing = json.loads(target_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    else:
        existing = {}

    existing["ats"] = {
        "source_url": url,
        "required_text_fields": REQUIRED_TEXT_FIELDS,
        "required_dropdowns": REQUIRED_DROPDOWNS,
        "required_checkboxes": REQUIRED_CHECKBOXES,
        "required_segments": REQUIRED_SEGMENTS,
        "inferred_fields": INFERRED_FIELDS,
        "user_questions": USER_QUESTIONS,
        "cover_letter_used": True if COVER_LETTER_USED else False,
        "cover_letter_used_type": COVER_LETTER_USED_TYPE,
        "application_status": APPLICATION_STATUS,
        "application_done": True if APPLICATION_DONE else False,
    }
    target_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def debug_action(el, intent: str):
    def safe_attr(value):
        return value if value else None

    def get_attr(name: str):
        try:
            return safe_attr(el.get_attribute(name))
        except:
            return None

    try:
        tag = el.evaluate("el => el.tagName")
    except:
        tag = None

    try:
        text = el.inner_text().strip()
    except:
        text = None

    print("\n--- ELEMENT ---")
    print("tag:", tag)
    print("automation-id:", get_attr("data-automation-id"))
    print("aria-label:", get_attr("aria-label"))
    print("placeholder:", get_attr("placeholder"))
    print("name", get_attr("name"))
    print("id", get_attr("id"))
    print("text:", text)
    print("intent:", intent)


# ============================================================
# FRAME SELECTION
# ============================================================

def pick_active_frame(page):
    frames = [page] + list(page.frames)
    usable = []
    for frame in frames:
        url = frame.url or ""
        if "recaptcha" in url or url.startswith("about:"):
            continue
        try:
            inputs = frame.locator("input").count()
            textareas = frame.locator("textarea").count()
            selects = frame.locator("select").count()
            score = inputs + textareas + selects
        except:
            continue
        usable.append((score, frame))
    if not usable:
        return None
    usable.sort(key=lambda x: x[0], reverse=True)
    return usable[0][1]


def _dismiss_cookie_popups_before_scan(page) -> bool:
    popup_selectors = [
        "dialog",
        "[role='dialog']",
        "[aria-modal='true']",
        "#modal-root",
        "[data-cy*='cookie']",
        "[id*='cookie']",
        "[class*='cookie']",
        "[id*='consent']",
        "[class*='consent']",
    ]
    popup_candidates = []
    for selector in popup_selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
        except:
            continue
        for idx in range(count):
            popup_candidates.append(locator.nth(idx))

    print(f"[popup-scan] popup candidates found: {len(popup_candidates)}")

    clicked_any = False
    seen_popups = set()
    visible_popups = 0
    for popup in popup_candidates:
        try:
            if not popup.is_visible():
                continue
        except:
            continue
        visible_popups += 1
        try:
            popup_key = (
                popup.get_attribute("id")
                or popup.get_attribute("data-cy")
                or popup.get_attribute("class")
                or ""
            ).strip()
        except:
            popup_key = ""
        if popup_key and popup_key in seen_popups:
            continue
        if popup_key:
            seen_popups.add(popup_key)
        print(f"[popup-scan] visible popup: key='{popup_key}'")
        try:
            buttons = popup.locator("button, a, input[type='submit'], input[type='button'], [role='button']")
            count = buttons.count()
        except:
            continue
        for idx in range(count):
            btn = buttons.nth(idx)
            try:
                if not btn.is_visible():
                    continue
            except:
                continue
            try:
                intent = infer_intent(btn)
            except:
                intent = None
            try:
                btn_text = (btn.inner_text() or btn.get_attribute("aria-label") or btn.get_attribute("title") or "").strip()
            except:
                btn_text = ""
            if intent != "cookies":
                continue
            try:
                print(f"[popup-scan] clicking cookie popup button: text='{btn_text}' intent='{intent}'")
                btn.click(force=True)
                page.wait_for_timeout(800)
                clicked_any = True
                break
            except:
                continue
    print(f"[popup-scan] visible popups scanned: {visible_popups} clicked={clicked_any}")
    return clicked_any


def _dismiss_blocking_dialogs(page, attempts: int = 2, wait_ms: int = 500) -> bool:
    context_markers = (
        "cookie", "cookies", "consent", "privacy", "datenschutz", "hinweis",
        "ki", "kunstliche intelligenz", "artificial intelligence", "onetrust",
    )
    button_markers = (
        "accept", "accept all", "allow", "allow all", "agree", "ok",
        "akzeptieren", "alle erlauben", "alle akzeptieren", "verstanden",
        "schliessen", "schlieÃŸen", "close", "dismiss",
    )
    clicked_any = False
    for _ in range(attempts):
        clicked_this_round = False
        try:
            dialogs = page.locator("dialog, [role='dialog'], [aria-modal='true'], .ui-dialog, #onetrust-banner-sdk")
            count = dialogs.count()
        except:
            count = 0
        for idx in range(count):
            dlg = dialogs.nth(idx)
            try:
                if not dlg.is_visible():
                    continue
                context = (
                    dlg.inner_text(timeout=800)
                    or dlg.get_attribute("aria-label")
                    or dlg.get_attribute("id")
                    or dlg.get_attribute("class")
                    or ""
                ).strip().lower()
            except:
                continue
            if not any(marker in context for marker in context_markers):
                continue
            try:
                buttons = dlg.locator("button, a, [role='button'], input[type='button'], input[type='submit']")
                btn_count = buttons.count()
            except:
                btn_count = 0
            for btn_idx in range(btn_count):
                btn = buttons.nth(btn_idx)
                try:
                    if not btn.is_visible():
                        continue
                    text = (
                        btn.inner_text(timeout=500)
                        or btn.get_attribute("value")
                        or btn.get_attribute("aria-label")
                        or btn.get_attribute("title")
                        or ""
                    ).strip().lower()
                    btn_meta = " ".join(
                        [
                            str(btn.get_attribute("class") or ""),
                            str(btn.get_attribute("id") or ""),
                            str(btn.get_attribute("data-testid") or ""),
                        ]
                    ).strip().lower()
                except:
                    continue
                if not any(marker in text for marker in button_markers):
                    if "onetrust-close-btn" not in btn_meta and "banner-close-button" not in btn_meta:
                        continue
                try:
                    print(f"[dialog-scan] clicking dialog button: text='{text}'")
                    btn.click(force=True)
                    page.wait_for_timeout(wait_ms)
                    clicked_any = True
                    clicked_this_round = True
                    break
                except:
                    continue
            if clicked_this_round:
                break
        if not clicked_this_round:
            break
    return clicked_any


def _click_submit_confirmation_popup(page, attempts: int = 3, wait_ms: int = 700) -> bool:
    positive_markers = (
        "oui postuler", "postuler", "envoyer", "envoyer ma candidature", "soumettre",
        "confirmer", "confirm", "yes apply", "apply", "submit", "send application",
        "bewerben", "bewerbung senden", "absenden", "ja bewerben",
    )
    negative_markers = (
        "changer", "changer de mail", "modifier", "change email", "change mail",
        "annuler", "cancel", "non", "no", "retour", "back", "close", "fermer",
    )
    dialog_selectors = (
        "dialog",
        "[role='dialog']",
        "[aria-modal='true']",
        ".ui-dialog",
        ".modal",
        ".modal-dialog",
        ".swal2-popup",
        ".bootbox",
        "[class*='modal']",
        "[class*='popup']",
    )

    def button_text(btn) -> str:
        try:
            return (
                btn.inner_text(timeout=500)
                or btn.get_attribute("value")
                or btn.get_attribute("aria-label")
                or btn.get_attribute("title")
                or ""
            ).strip()
        except:
            return ""

    def score_button(text: str) -> int:
        normalized = normalize(text)
        if not normalized:
            return -100
        if any(keyword_matches(normalized, marker) for marker in negative_markers):
            return -100
        score = 0
        for marker in positive_markers:
            if keyword_matches(normalized, marker):
                score += 10 + len(normalize(marker))
        if "oui" in normalized and ("postuler" in normalized or "envoyer" in normalized):
            score += 30
        if "yes" in normalized and ("apply" in normalized or "submit" in normalized):
            score += 30
        return score

    def try_scope(scope) -> bool:
        candidates = []
        for selector in dialog_selectors:
            try:
                locator = scope.locator(selector)
                count = locator.count()
            except:
                continue
            for idx in range(count):
                dlg = locator.nth(idx)
                try:
                    if dlg.is_visible():
                        candidates.append(dlg)
                except:
                    continue

        for dlg in candidates:
            try:
                buttons = dlg.locator("button, a, [role='button'], input[type='button'], input[type='submit']")
                button_count = buttons.count()
            except:
                continue
            scored = []
            for button_idx in range(button_count):
                btn = buttons.nth(button_idx)
                try:
                    if not btn.is_visible():
                        continue
                except:
                    continue
                text = button_text(btn)
                score = score_button(text)
                if score > 0:
                    scored.append((score, text, btn))
            if not scored:
                continue
            scored.sort(key=lambda item: item[0], reverse=True)
            _, text, btn = scored[0]
            try:
                print(f"[submit-confirm-popup] clicking confirmation button: text='{text}'")
                btn.click(force=True)
                scope.wait_for_timeout(wait_ms)
                return True
            except:
                continue
        return False

    clicked_any = False
    for _ in range(attempts):
        try:
            page.wait_for_timeout(wait_ms)
        except:
            pass
        clicked = try_scope(page)
        if not clicked:
            try:
                for frame in page.frames:
                    if try_scope(frame):
                        clicked = True
                        break
            except:
                clicked = False
        if not clicked:
            break
        clicked_any = True
    return clicked_any


# ============================================================
# MAIN LOOP
# ============================================================

def process_page(page):
    return process_page_simple(page)


def _normalize_label(value: str) -> str:
    return normalize(value or "")


def _click_option_if_matches(el, option_text: str) -> bool:
    if not option_text:
        return False
    option_norm = _normalize_label(option_text)
    if not option_norm:
        return False

    def _matches(candidate: str) -> bool:
        if not candidate:
            return False
        c = _normalize_label(candidate)
        if not c:
            return False
        if option_norm in {"yes", "no"}:
            return c == option_norm
        if c == option_norm:
            return True
        if c in option_norm or option_norm in c:
            return True
        return False

    # 1) Prefer element text/value/aria-label
    candidates = []
    try:
        t = el.inner_text().strip()
        if t:
            candidates.append(t)
    except:
        pass
    try:
        v = el.get_attribute("value")
        if v:
            candidates.append(v.strip())
    except:
        pass
    try:
        a = el.get_attribute("aria-label")
        if a:
            candidates.append(a.strip())
    except:
        pass
    for c in candidates:
        if _matches(c):
            try:
                el.click(force=True)
                return True
            except:
                return False

    # 2) Fallback to label text
    label_text = get_best_label_text(el.page, el)
    if not _matches(label_text):
        return False
    try:
        el.click(force=True)
        return True
    except:
        return False


def _click_segment_option(el, option_text: str) -> bool:
    if not option_text:
        return False
    option_norm = _normalize_label(option_text)
    if not option_norm:
        return False
    try:
        return el.evaluate(
            """
            (el, opt) => {
              const clean = s => (s || "").replace(/\\s+/g, " ").trim().toLowerCase();
              const field = el.closest(".ashby-application-form-field-entry") || el.parentElement;
              if (!field) return false;
              const buttons = Array.from(field.querySelectorAll("button"));
              for (const b of buttons) {
                const t = clean(b.innerText);
                if (t === opt) {
                  b.click();
                  return true;
                }
              }
              return false;
            }
            """,
            option_norm,
        )
    except:
        return False


@dataclass
class FieldContext:
    el: object
    frame: object
    tag: str
    el_type: str
    role: str
    field_type: str
    label: str
    required: bool
    options: list[str]
    intent_local: str | None


@dataclass
class ActionPlan:
    source: str
    intent: str | None = None
    answer: str = ""
    option: str = ""
    intent_confidence: float = 0.0
    answer_confidence: float = 0.0
    reason: str = ""


def _field_type(el, tag: str, el_type: str, role: str) -> str | None:
    if tag == "input" and el_type == "file":
        return "file"
    if is_dropzone_upload(el):
        return "file"
    if _is_special_multiselect_widget(el, tag, role):
        return "dropdown"
    if role == "combobox" or tag == "select":
        return "dropdown"
    if el_type in {"checkbox", "radio"} or role in {"checkbox", "radio"}:
        return "checkbox"
    if tag in {"button", "a"}:
        try:
            txt = normalize(el.inner_text())
        except:
            txt = ""
        if txt in {"yes", "no"}:
            return "segment"
        return "button"
    if tag in {"input", "textarea"} and el_type != "file":
        return "text"
    return None


def _dropdown_options(el) -> list[str]:
    try:
        tag = (el.evaluate("el => el.tagName") or "").lower()
    except:
        tag = ""
    role = (el.get_attribute("role") or "").lower()
    if _is_special_multiselect_widget(el, tag, role):
        options = _special_multiselect_options(el)
    else:
        options = get_dropdown_options(el)
    if not options:
        options = get_dropdown_options_by_navigation(el)
    if not options:
        try:
            options = el.evaluate(
                """
                (el) => {
                  const clean = s => (s || "").replace(/\\s+/g, " ").trim();
                  const id = el.getAttribute("aria-controls");
                  if (!id) return [];
                  const list = document.getElementById(id);
                  if (!list) return [];
                  const opts = Array.from(list.querySelectorAll('[role="option"]'));
                  return opts.map(o => clean(o.getAttribute("aria-label") || o.innerText)).filter(Boolean);
                }
                """
            ) or []
        except:
            options = []
    return options


def _checkbox_group_info(el) -> dict:
    try:
        return el.evaluate(
            """
            (el) => {
              const clean = s => (s || "").replace(/\\s+/g, " ").trim();
              const isJunk = (t) => {
                if (!t) return true;
                const v = t.trim().toLowerCase();
                if (!v) return true;
                if (v.length <= 2) return true;
                if (["yes","no","true","false","select one"].includes(v)) return true;
                return false;
              };

              const input = el.matches && el.matches('input[type="checkbox"],input[type="radio"]')
                ? el
                : (el.querySelector && el.querySelector('input[type="checkbox"],input[type="radio"]'));
              const base = input || el;

              let root = base.closest("fieldset") || base.closest('[role="radiogroup"]') || base.closest('[role="group"]');
              if (!root) {
                let cur = base.parentElement;
                while (cur) {
                  const count = cur.querySelectorAll('input[type="checkbox"],input[type="radio"]').length;
                  if (count >= 2) { root = cur; break; }
                  cur = cur.parentElement;
                }
              }
              root = root || base.parentElement || base;

              const inputs = Array.from(root.querySelectorAll("input[type='checkbox'],input[type='radio']"));
              const optionLabelNodes = new Set();
              const options = [];
              const labelForInput = (input) => {
                if (!input) return null;
                const parent = input.parentElement;
                if (parent) {
                  const lbl = parent.querySelector("label");
                  if (lbl && lbl.innerText) return lbl;
                  let psib = parent.nextElementSibling;
                  while (psib) {
                    if (psib.tagName === "LABEL" && psib.innerText) return psib;
                    psib = psib.nextElementSibling;
                  }
                  psib = parent.previousElementSibling;
                  while (psib) {
                    if (psib.tagName === "LABEL" && psib.innerText) return psib;
                    psib = psib.previousElementSibling;
                  }
                }
                let sib = input.nextElementSibling;
                while (sib) {
                  if (sib.tagName === "LABEL" && sib.innerText) return sib;
                  sib = sib.nextElementSibling;
                }
                sib = input.previousElementSibling;
                while (sib) {
                  if (sib.tagName === "LABEL" && sib.innerText) return sib;
                  sib = sib.previousElementSibling;
                }
                const wrap = input.closest("label");
                if (wrap && wrap.innerText) return wrap;
                return null;
              };
              for (const input of inputs) {
                const lbl = labelForInput(input);
                if (lbl) {
                  optionLabelNodes.add(lbl);
                  const t = clean(lbl.innerText);
                  if (t && !isJunk(t)) options.push(t);
                }
              }
              const labels = Array.from(root.querySelectorAll("label"));
              const mainLabelNode = labels.find(l => !optionLabelNodes.has(l) && l.innerText && !isJunk(l.innerText));
              const groupLabel = mainLabelNode ? clean(mainLabelNode.innerText) : "";
              return { label: groupLabel, options: Array.from(new Set(options)) };
            }
            """
        )
    except:
        return {"label": "", "options": []}


def _checkbox_group_key(el) -> str:
    try:
        handle = el.evaluate_handle(
            """
            (el) => {
              const input = el.matches && el.matches('input[type="checkbox"],input[type="radio"]')
                ? el
                : (el.querySelector && el.querySelector('input[type="checkbox"],input[type="radio"]'));
              const base = input || el;
              let root = base.closest("fieldset") || base.closest('[role="radiogroup"]') || base.closest('[role="group"]');
              if (!root) {
                let cur = base.parentElement;
                while (cur) {
                  const count = cur.querySelectorAll('input[type="checkbox"],input[type="radio"]').length;
                  if (count >= 2) { root = cur; break; }
                  cur = cur.parentElement;
                }
              }
              return root || base.parentElement || base;
            }
            """
        )
        root = handle.as_element()
        if root:
            loc = get_element_location(root)
            sel = (loc or {}).get("selector") or ""
            return sel
    except:
        pass
    return ""


def _check_checkbox_via_label(el) -> bool:
    try:
        return bool(
            el.evaluate(
                """
                (el) => {
                  const id = (el.getAttribute("id") || "").trim();
                  let label = null;
                  if (id) {
                    label = document.querySelector(`label[for="${id}"]`);
                  }
                  if (!label) {
                    label = el.closest("label");
                  }
                  if (!label && el.parentElement) {
                    label = el.parentElement.querySelector("label");
                  }
                  if (!label) return false;
                  label.click();
                  return true;
                }
                """
            )
        )
    except:
        return False


def _checkbox_has_visible_label(el) -> bool:
    try:
        return bool(
            el.evaluate(
                """
                (el) => {
                  const id = (el.getAttribute("id") || "").trim();
                  if (id) {
                    const lbl = document.querySelector(`label[for="${id}"]`);
                    if (lbl) {
                      const style = window.getComputedStyle(lbl);
                      return style.display !== "none" && style.visibility !== "hidden";
                    }
                  }
                  const wrap = el.closest("label");
                  if (wrap) {
                    const style = window.getComputedStyle(wrap);
                    return style.display !== "none" && style.visibility !== "hidden";
                  }
                  return false;
                }
                """
            )
        )
    except:
        return False


def _looks_like_required_acceptance(el, label: str = "") -> bool:
    try:
        text = " ".join(
            [
                str(label or ""),
                str(get_context_text(el, label) or ""),
                str(get_parent_visible_text(el) or ""),
            ]
        )
    except:
        text = str(label or "")
    normalized = normalize(text)
    if not normalized:
        return False
    accept_markers = ("j accepte", "i agree", "agree", "accept", "accepte", "consent")
    legal_markers = (
        "privacy",
        "confidentiality",
        "confidentialite",
        "politique de confidentialite",
        "donnees",
        "data protection",
        "terms",
        "conditions",
        "datenschutz",
        "einwilligung",
    )
    return any(keyword_matches(normalized, marker) for marker in accept_markers) and (
        any(keyword_matches(normalized, marker) for marker in legal_markers)
        or normalize(label) in {"j accepte", "i agree", "agree", "accept", "accepte"}
    )


def _build_field_context(frame, el) -> FieldContext | None:
    tag = (el.evaluate("el => el.tagName") or "").lower()
    el_type = (el.get_attribute("type") or "").lower()
    role = (el.get_attribute("role") or "").lower()
    try:
        if role == "button":
            cls = (el.get_attribute("class") or "").lower()
            if "multiselect-clear" in cls or el.get_attribute("data-clear") is not None:
                return None
            if (el.get_attribute("aria-roledescription") or "") in {"âŽ", "clear"}:
                return None
    except:
        pass
    ftype = _field_type(el, tag, el_type, role)
    if not ftype:
        return None
    label = get_best_label_text(frame, el)
    required = is_required_element(el)
    intent = infer_intent(el)
    if not intent and ftype == "file":
        intent = infer_dropzone_intent(el)
    options = []
    if ftype == "checkbox":
        try:
            group_info = _checkbox_group_info(el) or {}
        except:
            group_info = {}
        group_label = str(group_info.get("label") or "").strip()
        group_options = list(group_info.get("options") or [])
        if group_label:
            label = group_label
            if not intent:
                try:
                    intent = infer_intent_from_text(group_label)
                except:
                    pass
        if group_options:
            options = group_options
        if not required:
            try:
                required = bool(
                    el.evaluate(
                        """
                        (el) => {
                          const input = el.matches && el.matches('input[type="checkbox"],input[type="radio"]')
                            ? el
                            : (el.querySelector && el.querySelector('input[type="checkbox"],input[type="radio"]'));
                          const base = input || el;
                          let root = base.closest('.form_content_row')
                            || base.closest('fieldset')
                            || base.closest('[role="radiogroup"]')
                            || base.closest('[role="group"]');
                          if (!root) {
                            let cur = base.parentElement;
                            while (cur) {
                              const count = cur.querySelectorAll('input[type="checkbox"],input[type="radio"]').length;
                              if (count >= 2) { root = cur; break; }
                              cur = cur.parentElement;
                            }
                          }
                          root = root || base.parentElement || base;
                          const text = ((root.innerText || root.textContent || "")).replace(/\\s+/g, " ").trim();
                          if (text.includes("*")) return true;
                          return Boolean(
                            root.querySelector('.form_content_label_mustsign, .asterisk, [class*="mustsign"], [class*="required"]')
                          );
                        }
                        """
                    )
                )
            except:
                pass
    if ftype == "dropdown":
        options = _dropdown_options(el)
    elif ftype == "segment":
        options = get_segment_options(el)
    if ftype == "checkbox" and required and _looks_like_required_acceptance(el, label):
        intent = "privacy"
    return FieldContext(el, frame, tag, el_type, role, ftype, label, required, options, intent)


def _resolve_action_plan(ctx: FieldContext) -> ActionPlan:
    if _is_special_multiselect_widget(ctx.el, ctx.tag, ctx.role):
        return ActionPlan(source="fallback", intent=ctx.intent_local, reason="special_multiselect_user_choice")
    if not PRODUCTION_MODE:
        runtime_answer = runtime_answer_for_field(
            RUNTIME_ANSWERS,
            ATS_SOURCE,
            ctx.label,
            ctx.field_type,
            ctx.options,
        )
        if runtime_answer:
            runtime_intent = ctx.intent_local or infer_intent_from_text(ctx.label) or infer_intent(ctx.el)
            return ActionPlan(
                source="runtime",
                intent=runtime_intent,
                answer=runtime_answer,
                option=runtime_answer,
                intent_confidence=1.0,
                answer_confidence=1.0,
                reason="runtime_answer",
            )
    try:
        if ctx.label and ("niveau" in normalize(ctx.label) or "level" in normalize(ctx.label)):
            print(f"[plan-debug] label='{ctx.label}' field_type={ctx.field_type} intent_local={ctx.intent_local}")
    except:
        pass
    if ctx.intent_local and ctx.field_type == "checkbox":
        return ActionPlan(source="local", intent=ctx.intent_local)
    if ctx.intent_local and ctx.field_type not in {"checkbox", "segment"}:
        m = re.match(r"language(\d+)_", ctx.intent_local or "")
        if m and not ctx.intent_local.endswith("language"):
            idx = m.group(1)
            base = f"language{idx}language"
            if USED_INTENTS.get(base, 0) == 0:
                return ActionPlan(source="fallback", intent=ctx.intent_local, reason="language_order_guard")
        if ctx.field_type == "dropdown":
            cand = _candidate_value_for_intent(ctx.intent_local)
            matched = ""
            if cand:
                if ctx.options:
                    matched = _strict_option_from_options(cand, ctx.options)
                    if not matched:
                        matched, cand = _option_from_candidate_values(ctx.intent_local, ctx.options, strict=True)
                    if not matched:
                        cand = ""
            try:
                if ctx.intent_local.endswith("_level"):
                    print(
                        f"[level-debug] intent_local={ctx.intent_local} cand='{_candidate_value_for_intent(ctx.intent_local)}' "
                        f"options={len(ctx.options)} matched={'yes' if (cand and ctx.options and _best_option_from_options(cand, ctx.options)) else 'no'}"
                    )
            except:
                pass
            if cand:
                return ActionPlan(source="local", intent=ctx.intent_local, option=matched or cand, answer=matched or cand)
            intent = ctx.intent_local
            if not PRODUCTION_MODE:
                return ActionPlan(
                    source="fallback" if ctx.required else "skip",
                    intent=intent,
                    reason="runtime_missing_ai_disabled" if ctx.required else "local_dropdown_no_strict_option_nonrequired",
                )
            try:
                ai_answer = _infer_answer_with_openai(ctx.label, ctx.field_type, ctx.options) or {}
                time.sleep(OPENAI_BETWEEN_CALLS_DELAY)
            except Exception as exc:
                try:
                    print(f"[level-ai-error] {exc}")
                except:
                    pass
                if ctx.required:
                    _record_user_question(ctx.label, ctx.field_type, ctx.options, f"openai_answer_error:{exc}", 0.0)
                    return ActionPlan(source="fallback", intent=intent, reason="openai_answer_error")
                return ActionPlan(source="skip", intent=intent, reason="openai_answer_error_nonrequired")
            answer = (ai_answer.get("answer") or "").strip()
            option = (ai_answer.get("option") or "").strip()
            answer_conf = float(ai_answer.get("answer_confidence") or 0.0)
            if ctx.options:
                matched_ai = ""
                if option:
                    matched_ai = _best_option_from_options(option, ctx.options)
                if not matched_ai and answer:
                    matched_ai = _best_option_from_options(answer, ctx.options)
                if not matched_ai:
                    return ActionPlan(
                        source="fallback" if ctx.required else "skip",
                        intent=intent,
                        answer=answer,
                        option=option,
                        intent_confidence=1.0,
                        answer_confidence=answer_conf,
                        reason="ai_dropdown_no_option_match" if ctx.required else "ai_dropdown_no_option_match_nonrequired",
                    )
                option = matched_ai
                answer = matched_ai
            return ActionPlan(source="ai", intent=intent, answer=answer, option=option, intent_confidence=1.0, answer_confidence=answer_conf)
        elif ctx.intent_local == "availability":
            pass
        else:
            return ActionPlan(source="local", intent=ctx.intent_local)
    if ctx.field_type == "button":
        return ActionPlan(source="skip", reason="plain_button_no_intent")
    if not ctx.required:
        return ActionPlan(source="skip", reason="not_required")
    if not PRODUCTION_MODE:
        return ActionPlan(source="fallback", reason="runtime_missing_ai_disabled")
    try:
        ai_intent = _infer_intent_with_openai(ctx.label) or {}
        time.sleep(OPENAI_BETWEEN_CALLS_DELAY)
    except Exception as exc:
        _record_user_question(ctx.label, ctx.field_type, ctx.options, f"openai_intent_error:{exc}", 0.0)
        return ActionPlan(source="fallback", reason="openai_intent_error")
    intent = ai_intent.get("intent")
    intent_conf = float(ai_intent.get("intent_confidence") or 0.0)
    if intent and intent.startswith("language") and USED_INTENTS.get(intent, 0) >= get_max_uses(intent):
        return ActionPlan(source="fallback", intent=intent, intent_confidence=intent_conf, reason="intent_already_used")
    if intent in {"resume", "cover letter", "other document"} and USED_INTENTS.get(intent, 0) >= get_max_uses(intent):
        return ActionPlan(source="fallback", intent=intent, intent_confidence=intent_conf, reason="intent_already_used")
    m = re.match(r"language(\d+)_", intent or "")
    if m and not (intent or "").endswith("language"):
        idx = m.group(1)
        base = f"language{idx}language"
        if USED_INTENTS.get(base, 0) == 0:
            return ActionPlan(source="fallback", intent=intent, intent_confidence=intent_conf, reason="language_order_guard")
    if intent == "availability":
        label_norm = normalize(ctx.label)
        allowed = ["available", "availability", "notice period", "noticeperiod", "start working", "start date"]
        if not any(k in label_norm for k in allowed):
            return ActionPlan(source="fallback", intent=intent, intent_confidence=intent_conf, reason="availability_intent_guard")
    if intent in {"resume", "cover letter", "other document"}:
        if ctx.field_type != "file":
            return ActionPlan(source="fallback", intent=intent, intent_confidence=intent_conf, reason="file_intent_nonfile")
        label_norm = normalize(ctx.label)
        keywords = [k.lower() for k in INTENTS.get(intent, [])]
        if not any(k in label_norm for k in keywords):
            return ActionPlan(source="fallback", intent=intent, intent_confidence=intent_conf, reason="file_intent_guard")
    if not intent or intent_conf < OPENAI_CONFIDENCE_THRESHOLD:
        return ActionPlan(source="fallback", intent=intent, intent_confidence=intent_conf, reason="ai_intent_low_confidence")

    try:
        ai_answer = _infer_answer_with_openai(ctx.label, ctx.field_type, ctx.options) or {}
        time.sleep(OPENAI_BETWEEN_CALLS_DELAY)
    except Exception as exc:
        _record_user_question(ctx.label, ctx.field_type, ctx.options, f"openai_answer_error:{exc}", intent_conf)
        return ActionPlan(source="fallback", intent=intent, intent_confidence=intent_conf, reason="openai_answer_error")
    answer = (ai_answer.get("answer") or "").strip()
    option = (ai_answer.get("option") or "").strip()
    answer_conf = float(ai_answer.get("answer_confidence") or 0.0)
    return ActionPlan(source="ai", intent=intent, answer=answer, option=option, intent_confidence=intent_conf, answer_confidence=answer_conf)


def _apply_plan(ctx: FieldContext, plan: ActionPlan, processed_segment_keys: set[str]) -> bool:
    global COVER_LETTER_USED
    global COVER_LETTER_USED_TYPE
    global LAST_USED_INTENT
    global PENDING_LANGUAGE_INDEX
    global PENDING_LANGUAGE_STAGE
    el = ctx.el
    frame = ctx.frame
    intent = plan.intent
    page_obj = frame.page if hasattr(frame, "page") else frame
    if plan.source == "skip":
        return False

    if plan.source == "fallback":
        _record_user_question(ctx.label, ctx.field_type, ctx.options, plan.reason or "ai_unresolved_required", plan.intent_confidence)
        if ctx.field_type == "dropdown":
            record_required_dropdown(el)
            if _is_special_multiselect_widget(el, ctx.tag, ctx.role):
                _select_first_special_multiselect_option(el)
            else:
                select_first_option(el)
                confirm_dropdown_selection(el)
        elif ctx.field_type == "checkbox":
            record_required_checkbox(el)
        elif ctx.field_type == "segment":
            record_required_segment(el)
        elif ctx.field_type == "text":
            if is_cover_letter_field(el):
                record_unknown_question(el, "coverletterrequired")
            else:
                record_unknown_question(el)
        elif ctx.field_type == "file":
            fallback_path = _pick_random_fallback_file_path()
            try:
                if fallback_path:
                    if ctx.tag == "input" and ctx.el_type == "file":
                        el.set_input_files(fallback_path)
                    else:
                        input_el = el.locator("input[type='file']")
                        target = input_el.first if input_el.count() > 0 else _find_file_input_near_dropzone(el)
                        if target:
                            target.set_input_files(fallback_path)
                        else:
                            print(f"[record] required file label='{ctx.label}' fallback file chooser unavailable")
                    print(f"[record] required file fallback label='{ctx.label}' path='{fallback_path}'")
                else:
                    print(f"[record] required file label='{ctx.label}' no fallback document available")
            except:
                print(f"[record] required file label='{ctx.label}' fallback upload failed")
        frame.wait_for_timeout(300)
        return True

    if not intent:
        return False

    debug_action(el, intent)
    _dismiss_blocking_dialogs(page_obj)
    if intent == "cookies":
        if ctx.tag == "button":
            try:
                el.click(force=True)
                frame.wait_for_timeout(300)
            except:
                pass
        return True

    if intent in {"submit", "continue"} and ctx.tag in {"button", "a"}:
        if can_use_intent(intent):
            try:
                maybe_solve_datadome(frame.page if hasattr(frame, "page") else frame, "GENERALATS", CAPTCHA_STATE)
                maybe_solve_recaptcha(frame.page if hasattr(frame, "page") else frame, "GENERALATS", CAPTCHA_STATE)
                _mark_submit_click_for_completion_check(frame.page if hasattr(frame, "page") else frame)
                el.click(force=True)
                frame.wait_for_timeout(1000)
                _click_submit_confirmation_popup(page_obj)
            except:
                pass
        return True

    if intent == "add" and ctx.tag in {"button", "a"}:
        try:
            print(f"[add-debug] last_intent='{LAST_USED_INTENT}'")
            if LAST_USED_INTENT.startswith("language"):
                # Parse language index from intent like language2_x
                m = re.match(r"language(\d+)_", LAST_USED_INTENT)
                if m:
                    idx = int(m.group(1))
                    max_lang = int(getattr(candidate, "nb_language", 0) or 0)
                    print(f"[add-debug] idx={idx} max_lang={max_lang}")
                    if idx < max_lang:
                        global ADD_CLICKED_FOR_LANG
                        if idx in ADD_CLICKED_FOR_LANG:
                            return True
                        global RESCAN_REQUESTED
                        el.click(force=True)
                        frame.wait_for_timeout(500)
                        ADD_CLICKED_FOR_LANG.add(idx)
                        PENDING_LANGUAGE_INDEX = idx + 1
                        PENDING_LANGUAGE_STAGE = "language"
                        RESCAN_REQUESTED = True
                        return True
        except:
            pass
        return True

    if ctx.field_type == "file":
        file_intent = infer_dropzone_intent(el) if is_dropzone_upload(el) else intent
        if file_intent in ATTACHMENT_INTENTS and can_use_intent(file_intent):
            try:
                if ctx.tag == "input" and ctx.el_type == "file":
                    fill_file(el, file_intent)
                else:
                    input_el = el.locator("input[type='file']")
                    target = input_el.first if input_el.count() > 0 else _find_file_input_near_dropzone(el)
                    if target:
                        fill_file(target, file_intent)
                    else:
                        _set_files_via_filechooser(el, file_intent)
                frame.wait_for_timeout(1000)
                _dismiss_blocking_dialogs(page_obj, attempts=3, wait_ms=700)
            except:
                pass
        return True

    if ctx.field_type == "dropdown":
        try:
            print(
                f"[dropdown] id={ctx.el.get_attribute('id')} aria-controls={ctx.el.get_attribute('aria-controls')} "
                f"label='{ctx.label}' required={ctx.required}"
            )
        except:
            pass
        if _is_dropdown_filled(el):
            return True
        if intent and intent.startswith("language") and intent.endswith("language"):
            value = _best_option_from_options(_candidate_value_for_intent(intent), ctx.options)
        elif plan.source == "local":
            value = ""
            if ctx.options:
                value = _best_option_from_options(plan.option or plan.answer, ctx.options)
            else:
                value = plan.option or plan.answer or _candidate_value_for_intent(intent)
        elif plan.source in {"ai", "runtime"}:
            value = ""
            if ctx.options:
                if plan.option in ctx.options:
                    value = plan.option
                elif plan.answer in ctx.options:
                    value = plan.answer
                else:
                    value = _best_option_from_options(plan.option or plan.answer, ctx.options)
            else:
                value = plan.option or plan.answer
        else:
            value = _candidate_value_for_intent(intent)
        try:
            print(f"[dropdown-plan] source={plan.source} value='{value}' intent={plan.intent}")
        except:
            pass
        if value:
            if intent in {"resume", "cover letter", "other document"} or intent.startswith("language"):
                if not can_use_intent(intent):
                    return True
            elif intent and plan.source == "local":
                can_use_intent(intent)
            try:
                if el.input_value() and el.input_value().strip():
                    return True
            except:
                pass
            _dismiss_blocking_dialogs(page_obj)
            if _is_special_multiselect_widget(el, ctx.tag, ctx.role):
                selection_ok = _select_special_multiselect_option(el, value)
            else:
                selection_ok = select_from_combobox(el, value, prefer_options=True)
            frame.wait_for_timeout(300)
            displayed_value = _dropdown_display_value(el)
            if displayed_value:
                displayed_norm = _normalize_label(displayed_value)
                target_norm = _normalize_label(value)
                if displayed_norm and target_norm and displayed_norm != target_norm:
                    print(
                        f"[dropdown-mismatch] label='{ctx.label}' wanted='{value}' got='{displayed_value}'"
                    )
            if not selection_ok:
                print(f"[dropdown-select] selection failed label='{ctx.label}' target='{value}'")
            if intent and intent.startswith("language"):
                LAST_USED_INTENT = intent
                m = re.match(r"language(\d+)_(language|level|fluenty)$", intent)
                if m and PENDING_LANGUAGE_INDEX == int(m.group(1)):
                    if m.group(2) == "language":
                        PENDING_LANGUAGE_STAGE = "level"
                    elif m.group(2) == "level":
                        PENDING_LANGUAGE_STAGE = "fluenty"
                    else:
                        PENDING_LANGUAGE_INDEX = 0
                        PENDING_LANGUAGE_STAGE = ""
            key = _dropdown_unique_key(ctx.el)
            if key:
                FILLED_DROPDOWNS.add(key)
            if plan.source in {"ai", "runtime"}:
                append_unique(
                    INFERRED_FIELDS,
                    {
                        "label": ctx.label,
                        "field_type": "dropdown",
                        "intent": intent,
                        "answer": plan.answer,
                        "option": plan.option or value,
                        "intent_confidence": plan.intent_confidence,
                        "answer_confidence": plan.answer_confidence,
                        "source": "ai",
                    },
                )
            return True
        if plan.source in {"ai", "runtime"} and ctx.required:
            _record_user_question(ctx.label, ctx.field_type, ctx.options, "ai_no_option", plan.intent_confidence)
            select_first_option(el)
            confirm_dropdown_selection(el)
            frame.wait_for_timeout(300)
            if intent and intent.startswith("language"):
                LAST_USED_INTENT = intent
            return True
        return False

    if ctx.field_type == "checkbox":
        if plan.source in {"ai", "runtime"}:
            value = plan.option or plan.answer
            try:
                print(f"[checkbox-ai] value='{value}' options={len(ctx.options)}")
            except:
                pass
            if value and _click_option_if_matches(el, value):
                if intent and intent.startswith("language"):
                    m = re.match(r"language(\d+)_fluenty$", intent)
                    if m and PENDING_LANGUAGE_INDEX == int(m.group(1)):
                        PENDING_LANGUAGE_INDEX = 0
                        PENDING_LANGUAGE_STAGE = ""
                _record_user_question(ctx.label, ctx.field_type, ctx.options, "ai_selected_option", plan.intent_confidence)
                frame.wait_for_timeout(300)
                return True
            if value:
                try:
                    clicked = el.evaluate(
                        """
                        (el, target) => {
                          const clean = s => (s || "").replace(/\\s+/g, " ").trim().toLowerCase();
                          const root = el.closest("fieldset") || el.parentElement || el;
                          const labels = Array.from(root.querySelectorAll("label"));
                          const t = clean(target);
                          for (const lbl of labels) {
                            const txt = clean(lbl.innerText);
                            if (txt && (txt === t || txt.includes(t) || t.includes(txt))) {
                              lbl.click();
                              return true;
                            }
                          }
                          return false;
                        }
                        """,
                        value,
                    )
                    if clicked:
                        _record_user_question(ctx.label, ctx.field_type, ctx.options, "ai_selected_option", plan.intent_confidence)
                        frame.wait_for_timeout(300)
                        return True
                except:
                    pass
            if ctx.required:
                _record_user_question(ctx.label, ctx.field_type, ctx.options, "ai_no_option", plan.intent_confidence)
                try:
                    el.evaluate(
                        """
                        (el, firstOpt) => {
                          const clean = s => (s || "").replace(/\\s+/g, " ").trim().toLowerCase();
                          const root = el.closest("fieldset") || el.closest('[role="radiogroup"]') || el.closest('[role="group"]') || el.parentElement || el;
                          const labels = Array.from(root.querySelectorAll("label"));
                          if (firstOpt) {
                            const t = clean(firstOpt);
                            for (const lbl of labels) {
                              const txt = clean(lbl.innerText);
                              if (txt && (txt === t || txt.includes(t) || t.includes(txt))) {
                                lbl.click();
                                return true;
                              }
                            }
                          }
                          const inputs = Array.from(root.querySelectorAll("input[type='checkbox'],input[type='radio']"));
                          if (inputs[0]) {
                            inputs[0].click();
                            return true;
                          }
                          return false;
                        }
                        """,
                        (ctx.options[0] if ctx.options else ""),
                    )
                except:
                    pass
                frame.wait_for_timeout(300)
                return True
            return False
        if intent == "privacy" or ctx.required:
            try:
                if not el.is_checked():
                    if not _check_checkbox_via_label(el):
                        el.click(force=True)
            except:
                try:
                    if not _check_checkbox_via_label(el):
                        el.click(force=True)
                except:
                    pass
            frame.wait_for_timeout(300)
        return True

    if ctx.field_type == "segment":
        key = _normalize_label(ctx.label)
        if plan.source in {"ai", "runtime"}:
            if key and key in processed_segment_keys:
                return True
            value = plan.option or plan.answer
            if value and _click_segment_option(el, value):
                append_unique(
                    INFERRED_FIELDS,
                    {
                        "label": ctx.label,
                        "field_type": "segment",
                        "intent": intent,
                        "answer": plan.answer,
                        "option": plan.option or value,
                        "intent_confidence": plan.intent_confidence,
                        "answer_confidence": plan.answer_confidence,
                        "source": "ai",
                    },
                )
                frame.wait_for_timeout(300)
                if key:
                    processed_segment_keys.add(key)
                return True
            if ctx.required:
                _record_user_question(ctx.label, ctx.field_type, ctx.options, "ai_no_option", plan.intent_confidence)
                if ctx.options:
                    _click_segment_option(el, ctx.options[0])
                else:
                    try:
                        el.click(force=True)
                    except:
                        pass
                frame.wait_for_timeout(300)
                if key:
                    processed_segment_keys.add(key)
                return True
            return False
        if key and key in processed_segment_keys:
            return True
        desired = _candidate_value_for_intent(intent)
        if desired:
            _click_segment_option(el, desired)
        else:
            try:
                el.click(force=True)
            except:
                pass
        if key:
            processed_segment_keys.add(key)
        frame.wait_for_timeout(300)
        return True

    if ctx.field_type == "text":
        if plan.source in {"ai", "runtime"} and plan.answer:
            try:
                el.fill(plan.answer)
            except:
                try:
                    el.type(plan.answer, delay=20)
                except:
                    pass
            append_unique(
                INFERRED_FIELDS,
                {
                    "label": ctx.label,
                    "field_type": "text",
                    "intent": intent,
                    "answer": plan.answer,
                    "option": plan.option,
                    "intent_confidence": plan.intent_confidence,
                    "answer_confidence": plan.answer_confidence,
                    "source": "ai",
                },
            )
            frame.wait_for_timeout(300)
            return True
        if plan.source in {"ai", "runtime"} and ctx.required:
            _record_user_question(ctx.label, ctx.field_type, ctx.options, "ai_no_answer", plan.intent_confidence)
            try:
                el.fill("unknown")
            except:
                try:
                    el.type("unknown", delay=20)
                except:
                    pass
            frame.wait_for_timeout(300)
            return True
        if intent == "cover letter":
            COVER_LETTER_USED = True
            COVER_LETTER_USED_TYPE = "text"
            if can_use_intent(intent):
                value = (
                    _candidate_value_for_intent(intent)
                    or str(getattr(candidate, "cover_letter_text", "") or "")
                    or "cover letter text"
                )
                try:
                    el.fill(value)
                except:
                    try:
                        el.type(value, delay=20)
                    except:
                        pass
                frame.wait_for_timeout(300)
            return True
        if can_use_intent(intent):
            fill_text(el, intent, ctx.label)
            frame.wait_for_timeout(300)
            return True
    return False


def process_page_simple(page):
    global ACTIVE_FRAME_URL
    global RESCAN_REQUESTED
    global FILLED_DROPDOWNS
    processed_segment_keys = set()
    processed_checkbox_groups = set()
    processed_dropdowns = set()
    reset_submit_once = False
    RESCAN_REQUESTED = False
    try:
        page.wait_for_timeout(2000)
    except:
        pass
    _dismiss_cookie_popups_before_scan(page)
    _dismiss_blocking_dialogs(page, attempts=3, wait_ms=700)
    frames = [page] + list(page.frames)
    target = None
    if ACTIVE_FRAME_URL:
        for fr in frames:
            if fr.url == ACTIVE_FRAME_URL:
                target = fr
                break
    if not target:
        target = pick_active_frame(page)
        if target:
            ACTIVE_FRAME_URL = target.url
    if target:
        frames = [target]

    for frame in frames:
        elements = frame.locator("input, textarea, select, button, a, [role='combobox'], [data-form-field='dropzone-upload'], .dropzone")
        for i in range(elements.count()):
            el = elements.nth(i)
            try:
                tag_name = (el.evaluate("el => el.tagName") or "").lower()
            except:
                tag_name = ""
            try:
                el_type_name = (el.get_attribute("type") or "").lower()
            except:
                el_type_name = ""
            try:
                if not el.is_visible():
                    if not (
                        (tag_name == "input" and el_type_name in {"checkbox", "radio"} and _checkbox_has_visible_label(el))
                        or (tag_name == "input" and el_type_name == "file" and _file_input_has_visible_control(el))
                    ):
                        continue
            except:
                continue
            try:
                frame.wait_for_timeout(500)
            except:
                pass
            _dismiss_blocking_dialogs(page, attempts=1, wait_ms=500)
            ctx = _build_field_context(frame, el)
            if not ctx:
                continue
            try:
                if ctx.label and ("niveau" in normalize(ctx.label) or "level" in normalize(ctx.label)):
                    print("[debug] USED_INTENTS:", {k: v for k, v in USED_INTENTS.items() if k.startswith("language")})
            except:
                pass
            try:
                if PENDING_LANGUAGE_INDEX:
                    lbl_norm = normalize(ctx.label)
                    if ctx.field_type == "dropdown":
                        if PENDING_LANGUAGE_STAGE == "language":
                            if "language" in lbl_norm or "linguistique" in lbl_norm or "langue" in lbl_norm:
                                ctx.intent_local = f"language{PENDING_LANGUAGE_INDEX}_language"
                        elif PENDING_LANGUAGE_STAGE == "level":
                            if "niveau" in lbl_norm or "level" in lbl_norm or "overall" in lbl_norm:
                                ctx.intent_local = f"language{PENDING_LANGUAGE_INDEX}_level"
                    if ctx.field_type == "checkbox":
                        if PENDING_LANGUAGE_STAGE == "fluenty":
                            if "native" in lbl_norm or "fluency" in lbl_norm or "fluent" in lbl_norm:
                                ctx.intent_local = f"language{PENDING_LANGUAGE_INDEX}_fluenty"
            except:
                pass
            try:
                role = (ctx.el.get_attribute("role") or "").lower()
                if role == "combobox":
                    print(
                        f"[combobox-detect] tag={ctx.tag} id={ctx.el.get_attribute('id')} "
                        f"aria-controls={ctx.el.get_attribute('aria-controls')}"
                    )
            except:
                pass
            if ctx.field_type == "dropdown":
                try:
                    print(f"[dropdown-ctx] label='{ctx.label}' intent_local={ctx.intent_local} required={ctx.required}")
                except:
                    pass
            if ctx.field_type == "file":
                try:
                    print(
                        f"[file-ctx] id={ctx.el.get_attribute('id')} name={ctx.el.get_attribute('name')} "
                        f"title={ctx.el.get_attribute('title')} data-field-name={ctx.el.get_attribute('data-field-name')} "
                        f"label='{ctx.label}' intent_local={ctx.intent_local} required={ctx.required}"
                    )
                except:
                    pass
            if ctx.field_type == "checkbox":
                group_key = _checkbox_group_key(ctx.el)
                if group_key:
                    if group_key in processed_checkbox_groups:
                        continue
                    processed_checkbox_groups.add(group_key)
                info = _checkbox_group_info(ctx.el)
                if info:
                    if info.get("label"):
                        ctx.label = info.get("label") or ctx.label
                    if info.get("options"):
                        ctx.options = info.get("options") or ctx.options
                try:
                    print(f"[checkbox] label='{ctx.label}' options={len(ctx.options)} required={ctx.required}")
                except:
                    pass
            if ctx.field_type == "segment":
                # Always collect options for AI on segment groups
                ctx.options = get_segment_options(ctx.el) or ctx.options
            if ctx.field_type == "dropdown":
                try:
                    key = ctx.el.get_attribute("id") or ctx.el.get_attribute("aria-controls") or ""
                    cls = (ctx.el.get_attribute("class") or "").lower()
                except:
                    key = ""
                    cls = ""
                filled_key = _dropdown_unique_key(ctx.el)
                if filled_key and filled_key in FILLED_DROPDOWNS:
                    continue
                if _is_dropdown_filled(ctx.el):
                    if filled_key:
                        FILLED_DROPDOWNS.add(filled_key)
                    continue
                if "multiselect-wrapper" in cls:
                    key = ""
                if key:
                    if key in processed_dropdowns:
                        continue
                    processed_dropdowns.add(key)
            plan = _resolve_action_plan(ctx)
            if ctx.field_type == "checkbox":
                try:
                    print(
                        f"[checkbox-plan] source={plan.source} intent={plan.intent} "
                        f"intent_conf={plan.intent_confidence:.2f} answer_conf={plan.answer_confidence:.2f} reason={plan.reason}"
                    )
                except:
                    pass
            if not reset_submit_once and ctx.required and plan.source in {"ai", "fallback"}:
                if USED_INTENTS.get("submit", 0) >= get_max_uses("submit"):
                    USED_INTENTS["submit"] = 0
                if USED_INTENTS.get("continue", 0) >= get_max_uses("continue"):
                    USED_INTENTS["continue"] = 0
                reset_submit_once = True
            _apply_plan(ctx, plan, processed_segment_keys)
            if RESCAN_REQUESTED:
                return

    save_required_questions(page.url)


def run(url: str):
    print("GENERALATS: start")
    apply_keyword_language(os.getenv("APP_LANGUAGE") or detect_language_from_url(url))
    print(f"GENERALATS: keyword language {APPLICATION_LANGUAGE}")
    REQUIRED_TEXT_FIELDS.clear()
    REQUIRED_DROPDOWNS.clear()
    REQUIRED_CHECKBOXES.clear()
    REQUIRED_SEGMENTS.clear()
    INFERRED_FIELDS.clear()
    USER_QUESTIONS.clear()
    RECORDED_USER_QUESTION_IDS.clear()
    global COVER_LETTER_USED
    global COVER_LETTER_USED_TYPE
    global COVER_LETTER_FILE_AVAILABLE
    global OTHER_DOCUMENT_INDEX
    global USED_INTENTS
    global ACTIVE_FRAME_URL
    global UNKNOWN_COUNTER
    global ADD_CLICKED_FOR_LANG
    global FILLED_DROPDOWNS
    global PENDING_LANGUAGE_INDEX
    global PENDING_LANGUAGE_STAGE
    global SUBMIT_CHECK_PENDING
    global SUBMIT_PRECLICK_SIGNATURE
    global SUBMIT_PRECLICK_URL
    global SUBMIT_CHECK_ATTEMPTS
    global APPLICATION_STATUS
    global APPLICATION_DONE
    COVER_LETTER_USED = False
    COVER_LETTER_USED_TYPE = ""
    COVER_LETTER_FILE_AVAILABLE = False
    OTHER_DOCUMENT_INDEX = 0
    USED_INTENTS = {}
    ACTIVE_FRAME_URL = None
    UNKNOWN_COUNTER = 0
    ADD_CLICKED_FOR_LANG = set()
    FILLED_DROPDOWNS = set()
    PENDING_LANGUAGE_INDEX = 0
    PENDING_LANGUAGE_STAGE = ""
    SUBMIT_CHECK_PENDING = False
    SUBMIT_PRECLICK_SIGNATURE = ""
    SUBMIT_PRECLICK_URL = ""
    SUBMIT_CHECK_ATTEMPTS = 0
    APPLICATION_STATUS = "in_progress"
    APPLICATION_DONE = False
    CAPTCHA_STATE.reset()
    with sync_playwright() as p:
        print("GENERALATS: playwright ready")
        browser_proxy = datadome_playwright_proxy()
        browser = p.chromium.launch(headless=False, proxy=browser_proxy) if browser_proxy else p.chromium.launch(headless=False)
        print("GENERALATS: browser launched")
        context = browser.new_context(permissions=[])
        page = context.new_page()
        print("GENERALATS: page created")
        page.goto(url)
        print("GENERALATS: navigated", url)
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(5000)

        while True:
            if _page_is_closed(page):
                APPLICATION_STATUS = "completed"
                APPLICATION_DONE = True
                print("GENERALATS: page closed after submit; treating application as completed")
                save_required_questions(url)
                _close_browser_safely(browser)
                break
            try:
                maybe_solve_datadome(page, "GENERALATS", CAPTCHA_STATE)
                maybe_solve_recaptcha(page, "GENERALATS", CAPTCHA_STATE)
                process_page_simple(page)
            except Exception as exc:
                if _is_target_closed_error(exc):
                    APPLICATION_STATUS = "completed"
                    APPLICATION_DONE = True
                    print("GENERALATS: page/context closed after submit; treating application as completed")
                    save_required_questions(url)
                    _close_browser_safely(browser)
                    break
                raise
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except:
                pass
            maybe_solve_datadome(page, "GENERALATS", CAPTCHA_STATE, force=True)
            maybe_solve_recaptcha(page, "GENERALATS", CAPTCHA_STATE, force=True)
            page.wait_for_timeout(1000)
            if _refresh_completion_state_after_submit(page):
                print("GENERALATS: application done detected")
                print("FINISHED")
                save_required_questions(_current_page_url(page) or url)
                _close_browser_safely(browser)
                break
        _close_browser_safely(browser)
