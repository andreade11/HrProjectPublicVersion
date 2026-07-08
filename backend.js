const pageType = document.body.dataset.page || "";
let latestSources = [];
let activeBulkApplicationRunId = "";
const JOBS_REFRESH_INTERVAL_MS = 5000;
let jobsRefreshTimer = null;
let jobsRefreshPromise = null;

function esc(value) {
  return (value ?? "")
    .toString()
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function statusPill(status) {
  const normalized = (status || "unknown").toString().toLowerCase();
  return `<span class="status-pill status-${esc(normalized)}">${esc(status || "unknown")}</span>`;
}

function sourceNameMap(sources) {
  return new Map((sources || []).map((source) => [source.source_id, source.name || source.source_id]));
}

function formatSourceNames(sourceIds, sources) {
  const names = sourceNameMap(sources);
  const resolved = (sourceIds || []).map((sourceId) => names.get(sourceId) || sourceId).filter(Boolean);
  if (!resolved.length) return "All enabled sources";
  return resolved.join(", ");
}

function getSelectedSourceIds() {
  return Array.from(document.querySelectorAll("[data-source-checkbox]:checked"))
    .map((input) => input.value || "")
    .filter(Boolean);
}

function sourceEditorElements() {
  return {
    originalId: document.getElementById("source-original-id"),
    name: document.getElementById("source-name-input"),
    sector: document.getElementById("source-sector-input"),
    scannerKey: document.getElementById("source-scanner-key"),
    browserMode: document.getElementById("source-browser-mode-input"),
    locationScope: document.getElementById("source-location-scope-input"),
    baseUrl: document.getElementById("source-base-url-input"),
    swissOnlyUrl: document.getElementById("source-swiss-only-url-input"),
    defaultPages: document.getElementById("source-default-pages-input"),
    enabled: document.getElementById("source-enabled-input"),
    supportsPaging: document.getElementById("source-supports-paging-input"),
    settings: document.getElementById("source-settings-input"),
  };
}

function resetSourceForm() {
  const form = sourceEditorElements();
  if (!form.name) return;
  form.originalId.value = "";
  form.name.value = "";
  form.sector.value = "generic platform";
  form.scannerKey.value = "generic_career";
  form.browserMode.value = "headless";
  form.locationScope.value = "swiss_only";
  form.baseUrl.value = "";
  form.swissOnlyUrl.value = "";
  form.defaultPages.value = "1";
  form.enabled.checked = true;
  form.supportsPaging.checked = false;
  form.settings.value = "";
}

function loadSourceIntoForm(source) {
  const form = sourceEditorElements();
  if (!form.name) return;
  form.originalId.value = source.source_id || "";
  form.name.value = source.name || "";
  form.sector.value = source.sector || "generic platform";
  form.scannerKey.value = source.scanner_key || "generic_career";
  form.browserMode.value = source.browser_mode || "headless";
  form.locationScope.value = source.location_scope || "swiss_only";
  form.baseUrl.value = source.base_url || "";
  form.swissOnlyUrl.value = source.swiss_only_url || "";
  form.defaultPages.value = String(source.default_pages || 1);
  form.enabled.checked = !!source.enabled;
  form.supportsPaging.checked = !!source.supports_paging;
  form.settings.value = source.settings && Object.keys(source.settings).length
    ? JSON.stringify(source.settings, null, 2)
    : "";
}

function currentSourcePayload() {
  const form = sourceEditorElements();
  if (!form.name) {
    return {};
  }
  return {
    original_source_id: (form.originalId.value || "").trim(),
    name: (form.name.value || "").trim(),
    sector: (form.sector.value || "").trim(),
    scanner_key: (form.scannerKey.value || "").trim(),
    browser_mode: (form.browserMode.value || "").trim(),
    location_scope: (form.locationScope.value || "").trim(),
    base_url: (form.baseUrl.value || "").trim(),
    swiss_only_url: (form.swissOnlyUrl.value || "").trim(),
    default_pages: Number.parseInt(form.defaultPages.value || "1", 10) || 1,
    enabled: !!form.enabled.checked,
    supports_paging: !!form.supportsPaging.checked,
    settings: (form.settings.value || "").trim(),
  };
}

async function saveSource() {
  const payload = currentSourcePayload();
  if (!payload.name) {
    throw new Error("Name is required");
  }
  await fetchJson("/api/retrieval/sources/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await renderScannersPage();
}

async function deleteSource(sourceId) {
  const normalized = String(sourceId || "").trim();
  if (!normalized) return;
  if (!window.confirm(`Delete source "${normalized}"?`)) return;
  await fetchJson("/api/retrieval/sources/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_id: normalized }),
  });
  const form = sourceEditorElements();
  if (form.originalId?.value === normalized) {
    resetSourceForm();
  }
  await renderScannersPage();
}

async function runAutomation(jobKey) {
  await fetchJson(`/api/jobs/automate/${encodeURIComponent(jobKey)}`, { method: "POST" });
  await renderJobsPage();
  queueJobsRefresh();
}

async function automateAllJobs() {
  const payload = await fetchJson("/api/jobs/automate-all", { method: "POST" });
  activeBulkApplicationRunId = payload.run_id || "";
  await renderJobsPage();
  queueJobsRefresh();
}

async function pauseApplicationRun(runId) {
  await fetchJson(`/api/applications/${encodeURIComponent(runId)}/pause`, { method: "POST" });
  await renderJobsPage();
  queueJobsRefresh();
}

async function resumeApplicationRun(runId) {
  await fetchJson(`/api/applications/${encodeURIComponent(runId)}/resume`, { method: "POST" });
  await renderJobsPage();
  queueJobsRefresh();
}

async function restartApplicationRun(runId) {
  const payload = await fetchJson(`/api/applications/${encodeURIComponent(runId)}/restart`, { method: "POST" });
  activeBulkApplicationRunId = payload.run_id || "";
  await renderJobsPage();
  queueJobsRefresh();
}

async function runListingNow() {
  const pagesInput = document.getElementById("listing-pages");
  const pages = Number.parseInt(pagesInput?.value || "1", 10) || 1;
  const sourceIds = getSelectedSourceIds();
  await fetchJson("/api/listing/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pages, source_ids: sourceIds }),
  });
  await renderScannersPage();
}

async function stopListingNow() {
  await fetchJson("/api/listing/stop", { method: "POST" });
  await renderScannersPage();
}

async function startScheduler() {
  const pagesInput = document.getElementById("listing-pages");
  const intervalSelect = document.getElementById("scheduler-interval");
  const pages = Number.parseInt(pagesInput?.value || "1", 10) || 1;
  const intervalHours = Number.parseInt(intervalSelect?.value || "1", 10) || 1;
  const sourceIds = getSelectedSourceIds();
  await fetchJson("/api/listing/scheduler/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pages, interval_hours: intervalHours, source_ids: sourceIds }),
  });
  await renderScannersPage();
}

async function stopScheduler() {
  await fetchJson("/api/listing/scheduler/stop", { method: "POST" });
  await renderScannersPage();
}

async function clearListingRuns() {
  await fetchJson("/api/listings/clear", { method: "POST" });
  await renderScannersPage();
}

async function clearApplicationRuns(origin) {
  await fetchJson("/api/applications/clear", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ origin }),
  });
  await renderApplicationsPage();
}

async function automateApplicationUrl(applicationUrl) {
  await fetchJson("/api/applications/automate-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ application_url: applicationUrl }),
  });
  await renderApplicationsPage();
}

function wireJobActions() {
  document.querySelectorAll("[data-automate-job]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await runAutomation(button.dataset.automateJob || "");
      } catch (error) {
        alert(error.message);
      } finally {
        button.disabled = false;
      }
    });
  });
}

function wireSourceRegistryActions() {
  document.querySelectorAll("[data-edit-source]").forEach((button) => {
    button.addEventListener("click", () => {
      const sourceId = button.dataset.editSource || "";
      const source = latestSources.find((item) => item.source_id === sourceId);
      if (!source) return;
      loadSourceIntoForm(source);
      document.getElementById("source-editor-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  document.querySelectorAll("[data-delete-source]").forEach((button) => {
    button.addEventListener("click", async () => {
      await deleteSource(button.dataset.deleteSource || "");
    });
  });
}

function activeBulkRunFromState(state) {
  const run = state?.latest_application_run || null;
  if (!run || (run.origin || "").toString().toLowerCase() !== "bulk") return null;
  const status = (run.status || "").toString().toLowerCase();
  if (!["running", "pausing", "paused"].includes(status)) return null;
  return run;
}

function shouldPollJobsPage(state) {
  if (state?.listing_running || state?.listing_stop_requested) return true;
  const run = state?.latest_application_run || null;
  const status = (run?.status || "").toString().toLowerCase();
  return ["running", "pausing"].includes(status);
}

function stopJobsRefresh() {
  if (!jobsRefreshTimer) return;
  window.clearTimeout(jobsRefreshTimer);
  jobsRefreshTimer = null;
}

function queueJobsRefresh() {
  if (pageType !== "jobs" || jobsRefreshTimer) return;
  jobsRefreshTimer = window.setTimeout(() => {
    jobsRefreshTimer = null;
    renderJobsPage().catch((error) => console.error(error));
  }, JOBS_REFRESH_INTERVAL_MS);
}

function updateJobsRefreshPolling(state) {
  stopJobsRefresh();
  if (shouldPollJobsPage(state)) {
    queueJobsRefresh();
  }
}

function updateAutomationControls(run) {
  const pauseButton = document.getElementById("automation-pause-btn");
  const resumeButton = document.getElementById("automation-resume-btn");
  const restartButton = document.getElementById("automation-restart-btn");
  if (!pauseButton && !resumeButton && !restartButton) return;
  if (!run) {
    activeBulkApplicationRunId = "";
    [pauseButton, resumeButton, restartButton].forEach((button) => {
      if (!button) return;
      button.classList.add("hidden");
      button.disabled = true;
      button.dataset.runId = "";
    });
    return;
  }
  const runId = run?.id || activeBulkApplicationRunId;
  const status = (run?.status || "running").toString().toLowerCase();
  activeBulkApplicationRunId = runId;
  [pauseButton, resumeButton, restartButton].forEach((button) => {
    if (button) button.dataset.runId = runId;
  });

  if (pauseButton) {
    pauseButton.classList.toggle("hidden", status !== "running");
    pauseButton.disabled = status !== "running";
    pauseButton.textContent = "Pause Automation";
  }
  if (resumeButton) {
    const canResume = status === "paused" || status === "pausing";
    resumeButton.classList.toggle("hidden", !canResume);
    resumeButton.disabled = !canResume;
    resumeButton.textContent = status === "pausing" ? "Resume Automation (pause pending)" : "Resume Automation";
  }
  if (restartButton) {
    restartButton.classList.toggle("hidden", status !== "paused");
    restartButton.disabled = status !== "paused";
  }
}

function renderJobsStatusBanner(state = null) {
  const banner = document.getElementById("backend-status");
  if (!banner) return;
  const activeBulkRun = activeBulkRunFromState(state);
  if (activeBulkRun) {
    const status = (activeBulkRun.status || "running").toString().toLowerCase();
    const total = activeBulkRun.jobs_total ?? ((activeBulkRun.items || []).length || 0);
    const done = Number(activeBulkRun.jobs_success || 0) + Number(activeBulkRun.jobs_skipped || 0) + Number(activeBulkRun.jobs_failed || 0);
    const actionText = status === "paused"
      ? "Bulk automation is paused before the next job."
      : (status === "pausing" ? "Bulk automation will pause after the current job." : "Bulk automation is running.");
    banner.textContent = `${actionText} Progress: ${done}/${total}.`;
    return;
  }
  banner.textContent = "Saved jobs are shown here. Use the Scanners page to refresh retrieval sources and launch scans.";
}

function renderStatusBanner(state, sources) {
  const banner = document.getElementById("backend-status");
  if (!banner) return;
  const scheduler = state.scheduler || {};
  const schedulerText = scheduler.enabled
    ? `Scheduler every ${scheduler.interval_hours || "?"}h for ${formatSourceNames(scheduler.source_ids, sources)}, next run ${formatDateTime(scheduler.next_run_at)}`
    : "Scheduler stopped";
  const listingText = state.listing_running
    ? (state.listing_stop_requested ? "A retrieval run is stopping" : "A retrieval run is in progress")
    : "No retrieval run in progress";
  const latestRun = state.latest_listing_run;
  const latestRunText = latestRun
    ? `Latest run scanned ${formatSourceNames(latestRun.selected_source_ids, sources)}`
    : "No retrieval run recorded yet";
  banner.innerHTML = `${esc(listingText)}. ${esc(schedulerText)}. ${esc(latestRunText)}.`;
}

function renderSourceSelector(sources, preferredIds) {
  const container = document.getElementById("source-selector-list");
  if (!container) return;
  const selected = new Set(
    (preferredIds && preferredIds.length
      ? preferredIds
      : (sources || []).filter((source) => source.enabled).map((source) => source.source_id))
  );
  const sectorOrder = [
    "generic platform",
    "insurance",
    "bank",
    "Audit, Accounting, Consulting",
    "Real Estate",
  ];
  const grouped = new Map();
  for (const source of (sources || [])) {
    const sector = source.sector || "generic platform";
    if (!grouped.has(sector)) grouped.set(sector, []);
    grouped.get(sector).push(source);
  }
  const orderedSectors = [
    ...sectorOrder.filter((sector) => grouped.has(sector)),
    ...Array.from(grouped.keys()).filter((sector) => !sectorOrder.includes(sector)).sort(),
  ];
  container.innerHTML = orderedSectors.map((sector) => {
    const items = grouped.get(sector) || [];
    return `
      <div class="source-selector-group">
        <div class="source-selector-group-title"><strong>${esc(sector)}</strong></div>
        <div class="source-selector-group-items">
          ${items.map((source) => `
            <label class="source-chip ${source.enabled ? "" : "is-disabled"}">
              <input
                type="checkbox"
                data-source-checkbox
                value="${esc(source.source_id || "")}"
                ${selected.has(source.source_id) ? "checked" : ""}
                ${source.enabled ? "" : "disabled"}
              >
              <span>${esc(source.name || source.source_id || "source")}</span>
              ${statusPill(source.status || (source.enabled ? "idle" : "disabled"))}
            </label>
          `).join("")}
        </div>
      </div>
    `;
  }).join("");
}

function renderSourceRegistry(sources) {
  const list = document.getElementById("sources-list");
  const empty = document.getElementById("sources-empty");
  if (!list || !empty) return;
  if (!sources.length) {
    list.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  list.innerHTML = sources.map((source) => `
    <article class="source-card compact-source-card registry-source-card">
      <div class="source-card-compact-head">
        <div class="source-card-compact-title">
          <strong>${esc(source.name || source.source_id || "Source")}</strong>
        </div>
        <div class="source-card-compact-actions">
          ${statusPill(source.status || "idle")}
          <button type="button" class="ghost-btn" data-edit-source="${esc(source.source_id || "")}">Edit</button>
          <button type="button" class="ghost-btn" data-delete-source="${esc(source.source_id || "")}">Delete</button>
        </div>
      </div>
      <div class="source-card-compact-url">${esc(source.base_url || "")}</div>
      <div class="source-card-compact-meta">
        ${esc(`${source.sector || "generic platform"} | ${source.scanner_key || ""} | ${source.browser_mode || "headless"} | ${source.location_scope === "worldwide" ? "Worldwide" : "Swiss only"} | ${source.enabled ? "Enabled" : "Disabled"} | ${formatDateTime(source.last_success_at) || "Never synced"}`)}
      </div>
    </article>
  `).join("");
  wireSourceRegistryActions();
}

async function renderJobsPage() {
  if (pageType !== "jobs") return;
  if (jobsRefreshPromise) return jobsRefreshPromise;
  stopJobsRefresh();
  jobsRefreshPromise = (async () => {
    const [jobs, state] = await Promise.all([
      fetchJson("/api/jobs"),
      fetchJson("/api/state"),
    ]);
    const list = document.getElementById("jobs-list");
    const empty = document.getElementById("jobs-empty");
    const counter = document.getElementById("jobs-count");
    const automateAllBtn = document.getElementById("automate-all-btn");
    const automatableJobs = jobs.filter((job) => !!job.automation_possible);
    const activeBulkRun = activeBulkRunFromState(state);
    renderJobsStatusBanner(state);
    updateAutomationControls(activeBulkRun);
    if (counter) {
      counter.textContent = `${jobs.length} job${jobs.length === 1 ? "" : "s"} displayed | ${automatableJobs.length} automatable`;
    }
    if (automateAllBtn) {
      automateAllBtn.textContent = `Automate All Jobs (${automatableJobs.length})`;
      automateAllBtn.disabled = automatableJobs.length === 0 || Boolean(activeBulkRun);
    }

    if (!jobs.length) {
      list.innerHTML = "";
      empty.classList.remove("hidden");
    } else {
      empty.classList.add("hidden");
      list.innerHTML = jobs.map((job) => {
        const ficheUrl = job.url || job.url_add || "";
        const applicationUrl = job.application_url || "";
        return `
          <article class="card backend-card">
            <div class="backend-card-head">
              <div>
                <h2>${esc(job.title || "Untitled")}</h2>
                <p class="backend-subtitle">${esc(job.hiring_org || "")} ${job.job_location ? " - " + esc(job.job_location) : ""}</p>
              </div>
              ${statusPill(job.application_status || "unknown")}
            </div>
            <div class="backend-card-meta">
              <span><strong>Key:</strong> ${esc(job.job_key || "")}</span>
              <span><strong>Source:</strong> ${esc(job.source_name || job.source_id || "Unknown")}</span>
              <span><strong>Application URL:</strong> ${applicationUrl ? `<a href="${esc(applicationUrl)}" target="_blank" rel="noreferrer">open</a>` : "missing"}</span>
            </div>
            <div class="actions">
              <button type="button" data-automate-job="${esc(job.job_key || "")}" ${job.automation_possible ? "" : "disabled"}>Automate</button>
              ${ficheUrl ? `<a class="ghost" href="${esc(ficheUrl)}" target="_blank" rel="noreferrer">URL Link</a>` : `<span class="ghost ghost-disabled">URL Link</span>`}
              ${applicationUrl ? `<a class="ghost" href="${esc(applicationUrl)}" target="_blank" rel="noreferrer">Application Link</a>` : `<span class="ghost ghost-disabled">Application Link</span>`}
            </div>
          </article>
        `;
      }).join("");
    }

    wireJobActions();
    updateJobsRefreshPolling(state);
  })();
  try {
    return await jobsRefreshPromise;
  } finally {
    jobsRefreshPromise = null;
  }
}

function renderScannerRuns(runs, sources) {
  const list = document.getElementById("scanner-runs-list");
  const empty = document.getElementById("scanner-runs-empty");
  if (!list || !empty) return;
  if (!runs.length) {
    list.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  list.innerHTML = runs.map((run) => `
    <article class="source-card compact-source-card">
      <div class="backend-card-head">
        <div>
          <h3>${esc(formatSourceNames(run.selected_source_ids, sources))}</h3>
          <p class="backend-subtitle">Started ${esc(formatDateTime(run.started_at))}</p>
        </div>
        ${statusPill(run.status || "unknown")}
      </div>
      <div class="backend-card-meta">
        <span><strong>Found:</strong> ${esc(run.jobs_found ?? 0)}</span>
        <span><strong>Saved:</strong> ${esc(run.jobs_saved ?? 0)}</span>
        <span><strong>Skipped:</strong> ${esc(run.jobs_skipped_existing ?? 0)}</span>
        <span><strong>Failed:</strong> ${esc(run.jobs_failed ?? 0)}</span>
      </div>
      <div class="compact-run-items">
        ${(run.items || []).map((item) => `
          <div class="compact-run-item">
            <strong>${esc(item.source_name || item.source_id || "Source")}</strong>
            ${statusPill(item.status || "unknown")}
            <span>${esc(`found ${item.jobs_found ?? 0} / saved ${item.jobs_saved ?? 0}`)}</span>
          </div>
        `).join("")}
      </div>
    </article>
  `).join("");
}

async function renderScannersPage() {
  if (pageType !== "scanners") return;
  const previousSelection = getSelectedSourceIds();
  const [state, sources, runs] = await Promise.all([
    fetchJson("/api/state"),
    fetchJson("/api/retrieval/sources"),
    fetchJson("/api/listings"),
  ]);
  latestSources = sources || [];
  const preferredIds = previousSelection.length
    ? previousSelection
    : ((state.scheduler || {}).source_ids || []);

  renderStatusBanner(state, sources);
  renderSourceSelector(sources, preferredIds);
  renderSourceRegistry(sources);
  renderScannerRuns(runs, sources);
}

async function renderApplicationsPageLegacy() {
  return renderApplicationsPage();
  if (pageType !== "applications") return;
  const runs = await fetchJson("/api/applications");
  const list = document.getElementById("applications-list");
  const empty = document.getElementById("applications-empty");
  if (!runs.length) {
    list.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  const renderApplicationQuestion = (question, namePrefix, index) => {
    const label = esc(question?.label || "");
    const fieldType = (question?.field_type || "text").toString().toLowerCase();
    const options = Array.isArray(question?.options) ? question.options : [];
    if (fieldType === "dropdown") {
      return `
        <label class="application-question-field">
          <span class="application-question-label">${label}</span>
          <select class="application-question-select">
            <option value="">Select an option</option>
            ${options.map((option) => `<option>${esc(option)}</option>`).join("")}
          </select>
        </label>
      `;
    }
    if (fieldType === "checkbox") {
      return `
        <fieldset class="application-question-field">
          <legend class="application-question-label">${label}</legend>
          <div class="application-question-options">
            ${options.map((option, optionIndex) => `
              <label class="application-question-choice">
                <input type="checkbox" disabled name="${esc(`${namePrefix}-checkbox-${index}-${optionIndex}`)}">
                <span>${esc(option)}</span>
              </label>
            `).join("")}
          </div>
        </fieldset>
      `;
    }
    if (fieldType === "segment" || fieldType === "radio") {
      return `
        <fieldset class="application-question-field">
          <legend class="application-question-label">${label}</legend>
          <div class="application-question-options">
            ${options.map((option, optionIndex) => `
              <label class="application-question-choice">
                <input type="radio" disabled name="${esc(`${namePrefix}-radio-${index}`)}" value="${esc(option)}">
                <span>${esc(option)}</span>
              </label>
            `).join("")}
          </div>
        </fieldset>
      `;
    }
    return `
      <label class="application-question-field">
        <span class="application-question-label">${label}</span>
        <input type="text" class="application-question-input" readonly value="">
      </label>
    `;
  };

  list.innerHTML = runs.map((run) => `
    <article class="card backend-card">
      <div class="backend-card-head">
        <div>
          <h2>${esc(run.origin || "run")} automation</h2>
          <p class="backend-subtitle">Started ${esc(formatDateTime(run.started_at))}</p>
        </div>
        ${statusPill(run.status || "unknown")}
      </div>
      <div class="backend-card-meta">
        <span><strong>Total:</strong> ${esc(run.jobs_total ?? ((run.items || []).length || 0))}</span>
        <span><strong>Successful:</strong> ${esc(run.jobs_success ?? 0)}</span>
        <span><strong>Skipped:</strong> ${esc(run.jobs_skipped ?? 0)}</span>
        <span><strong>Failed:</strong> ${esc(run.jobs_failed ?? 0)}</span>
        ${Number(run.jobs_running ?? 0) ? `<span><strong>Running:</strong> ${esc(run.jobs_running ?? 0)}</span>` : ""}
      </div>
      <div class="backend-run-items">
        ${(run.items || []).map((item, itemIndex) => {
          const questions = Array.isArray(item.questions) ? item.questions : [];
          const questionPanelId = `application-questions-${esc(run.id || "run")}-${esc(item.job_key || itemIndex)}`;
          return `
          <div class="backend-run-item">
            <div class="backend-run-item-top">
              <div>
                <strong>${esc(item.title || "Untitled")}</strong>
                <div class="backend-subtitle">${esc(item.company || "")}</div>
                <div class="backend-subtitle">${esc(`ATS: ${item.ats_program || "unknown"}`)}</div>
                <div class="backend-subtitle">${esc(`Language: ${item.application_language || "unknown"}`)}</div>
              </div>
              <div class="backend-run-item-status">
                ${statusPill(item.status || "unknown")}
                <span>${esc(item.application_status || "")}</span>
              </div>
            </div>
            ${questions.length ? `
              <div class="backend-run-item-actions">
                <button
                  type="button"
                  class="ghost-btn application-questions-toggle"
                  data-app-questions-toggle="${questionPanelId}"
                  aria-expanded="false"
                >
                  ▾ Questions (${esc(questions.length)})
                </button>
              </div>
              <div id="${questionPanelId}" class="application-questions hidden">
                ${questions.map((question, questionIndex) => renderApplicationQuestion(question, `${run.id || "run"}-${item.job_key || itemIndex}`, questionIndex)).join("")}
              </div>
            ` : ""}
            ${item.error ? `
              <div class="backend-subtitle">${esc(`Error: ${item.error}`)}</div>
            ` : ""}
          </div>
        `;
        }).join("")}
      </div>
    </article>
  `).join("");

  document.querySelectorAll("[data-app-questions-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const panelId = button.dataset.appQuestionsToggle || "";
      const panel = document.getElementById(panelId);
      if (!panel) return;
      const willOpen = panel.classList.contains("hidden");
      panel.classList.toggle("hidden");
      button.setAttribute("aria-expanded", willOpen ? "true" : "false");
      const current = button.textContent || "";
      button.textContent = current.replace(willOpen ? "▾" : "▴", willOpen ? "▴" : "▾");
    });
  });
}

async function renderApplicationsPage() {
  if (pageType !== "applications") return;
  const runs = await fetchJson("/api/applications");
  const list = document.getElementById("applications-list");
  const empty = document.getElementById("applications-empty");
  if (!runs.length) {
    list.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");

  const renderApplicationQuestion = (question, namePrefix, index) => {
    const label = esc(question?.label || "");
    const fieldType = (question?.field_type || "text").toString().toLowerCase();
    const rawOptions = Array.isArray(question?.options) ? question.options : [];
    const options = rawOptions.length ? rawOptions : [question?.label || ""];
    if (fieldType === "dropdown") {
      return `
        <label class="application-question-field">
          <span class="application-question-label">${label}</span>
          <select class="application-question-select">
            <option value="">Select an option</option>
            ${options.map((option) => `<option>${esc(option)}</option>`).join("")}
          </select>
        </label>
      `;
    }
    if (fieldType === "checkbox") {
      return `
        <fieldset class="application-question-field">
          <legend class="application-question-label">${label}</legend>
          <div class="application-question-options">
            ${options.map((option, optionIndex) => `
              <label class="application-question-choice">
                <input type="checkbox" disabled name="${esc(`${namePrefix}-checkbox-${index}-${optionIndex}`)}">
                <span>${esc(option)}</span>
              </label>
            `).join("")}
          </div>
        </fieldset>
      `;
    }
    if (fieldType === "segment" || fieldType === "radio") {
      return `
        <fieldset class="application-question-field">
          <legend class="application-question-label">${label}</legend>
          <div class="application-question-options">
            ${options.map((option) => `
              <label class="application-question-choice">
                <input type="radio" disabled name="${esc(`${namePrefix}-radio-${index}`)}" value="${esc(option)}">
                <span>${esc(option)}</span>
              </label>
            `).join("")}
          </div>
        </fieldset>
      `;
    }
    return `
      <label class="application-question-field">
        <span class="application-question-label">${label}</span>
        <input type="text" class="application-question-input" readonly value="">
      </label>
    `;
  };

  list.innerHTML = runs.map((run) => `
    <article class="card backend-card">
      <div class="backend-card-head">
        <div>
          <h2>${esc(run.origin || "run")} automation</h2>
          <p class="backend-subtitle">Started ${esc(formatDateTime(run.started_at))}</p>
        </div>
        ${statusPill(run.status || "unknown")}
      </div>
      <div class="backend-card-meta">
        <span><strong>Total:</strong> ${esc(run.jobs_total ?? ((run.items || []).length || 0))}</span>
        <span><strong>Successful:</strong> ${esc(run.jobs_success ?? 0)}</span>
        <span><strong>Skipped:</strong> ${esc(run.jobs_skipped ?? 0)}</span>
        <span><strong>Failed:</strong> ${esc(run.jobs_failed ?? 0)}</span>
        ${Number(run.jobs_running ?? 0) ? `<span><strong>Running:</strong> ${esc(run.jobs_running ?? 0)}</span>` : ""}
      </div>
      <div class="backend-run-items">
        ${(run.items || []).map((item, itemIndex) => {
          const questions = Array.isArray(item.questions) ? item.questions : [];
          const questionPanelId = `application-questions-${esc(run.id || "run")}-${esc(item.job_key || itemIndex)}`;
          return `
            <div class="backend-run-item">
              <div class="backend-run-item-top">
                <div>
                  <strong>${esc(item.title || "Untitled")}</strong>
                  <div class="backend-subtitle">${esc(item.company || "")}</div>
                  <div class="backend-subtitle">${esc(`ATS: ${item.ats_program || "unknown"}`)}</div>
                  <div class="backend-subtitle">${esc(`Language: ${item.application_language || "unknown"}`)}</div>
                </div>
                <div class="backend-run-item-status">
                  ${statusPill(item.status || "unknown")}
                  <span>${esc(item.application_status || "")}</span>
                </div>
              </div>
              ${questions.length ? `
                <div class="backend-run-item-actions">
                  <button
                    type="button"
                    class="ghost-btn application-questions-toggle"
                    data-app-questions-toggle="${questionPanelId}"
                    data-question-count="${esc(questions.length)}"
                    aria-expanded="false"
                  ><span class="application-toggle-icon" aria-hidden="true">&#9662;</span> Questions (${esc(questions.length)})</button>
                </div>
                <div id="${questionPanelId}" class="application-questions hidden">
                  ${questions.map((question, questionIndex) => renderApplicationQuestion(question, `${run.id || "run"}-${item.job_key || itemIndex}`, questionIndex)).join("")}
                </div>
              ` : ""}
              ${item.error ? `<div class="backend-subtitle">${esc(`Error: ${item.error}`)}</div>` : ""}
            </div>
          `;
        }).join("")}
      </div>
    </article>
  `).join("");

  document.querySelectorAll("[data-app-questions-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const panelId = button.dataset.appQuestionsToggle || "";
      const panel = document.getElementById(panelId);
      if (!panel) return;
      const willOpen = panel.classList.contains("hidden");
      panel.classList.toggle("hidden");
      button.setAttribute("aria-expanded", willOpen ? "true" : "false");
      const questionCount = button.dataset.questionCount || "0";
      button.innerHTML = `<span class="application-toggle-icon" aria-hidden="true">${willOpen ? "&#9652;" : "&#9662;"}</span> Questions (${esc(questionCount)})`;
    });
  });
}

function renderCandidateDetails(candidate) {
  const details = candidate.details || {};
  const rows = [
    ["Profile path", candidate.profile_path || ""],
    ["Experience count", candidate.summary?.experience_count ?? ""],
    ["Education count", candidate.summary?.education_count ?? ""],
    ["Language count", candidate.summary?.language_count ?? ""],
    ["Phone", details.phone_number || ""],
    ["City", details.city || ""],
    ["Country", details.country || ""],
    ["Resume", details.resume_path || ""],
  ];
  return rows.map(([label, value]) => `
    <div class="detail-row">
      <strong>${esc(label)}</strong>
      <span>${esc(value)}</span>
    </div>
  `).join("");
}

async function renderCandidatesPage() {
  if (pageType !== "candidates") return;
  const candidates = await fetchJson("/api/candidates");
  const list = document.getElementById("candidates-list");
  const empty = document.getElementById("candidates-empty");
  if (!candidates.length) {
    list.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  list.innerHTML = candidates.map((candidate) => `
    <article class="card backend-card candidate-card">
      <div class="candidate-row">
        <span>${esc(candidate.first_name || "")}</span>
        <span>${esc(candidate.last_name || "")}</span>
        <span>${esc(candidate.email || "")}</span>
        <span>${esc(candidate.ip_address || "Hidden")}</span>
        <span>${esc(candidate.plan || "Unknown")}</span>
        <button
          type="button"
          class="ghost-btn"
          data-candidate-toggle="${esc(candidate.id || "")}"
          aria-controls="candidate-${esc(candidate.id || "")}"
          aria-expanded="false"
        >Expand</button>
      </div>
      <div id="candidate-${esc(candidate.id || "")}" class="candidate-details hidden">
        ${renderCandidateDetails(candidate)}
      </div>
    </article>
  `).join("");

  document.querySelectorAll("[data-candidate-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const panel = document.getElementById(`candidate-${button.dataset.candidateToggle}`);
      if (!panel) return;
      const willOpen = panel.classList.contains("hidden");
      panel.classList.toggle("hidden");
      button.setAttribute("aria-expanded", willOpen ? "true" : "false");
      button.textContent = willOpen ? "Collapse" : "Expand";
    });
  });
}

function initJobsControls() {
  const manualRefreshBtn = document.getElementById("manual-refresh-btn");
  manualRefreshBtn?.addEventListener("click", async () => {
    await renderCurrentPage();
  });

  const automateAllBtn = document.getElementById("automate-all-btn");
  automateAllBtn?.addEventListener("click", async () => {
    try {
      await automateAllJobs();
    } catch (error) {
      alert(error.message);
    }
  });

  const automationPauseBtn = document.getElementById("automation-pause-btn");
  automationPauseBtn?.addEventListener("click", async () => {
    const runId = automationPauseBtn.dataset.runId || activeBulkApplicationRunId;
    if (!runId) return;
    try {
      await pauseApplicationRun(runId);
    } catch (error) {
      alert(error.message);
    }
  });

  const automationResumeBtn = document.getElementById("automation-resume-btn");
  automationResumeBtn?.addEventListener("click", async () => {
    const runId = automationResumeBtn.dataset.runId || activeBulkApplicationRunId;
    if (!runId) return;
    try {
      await resumeApplicationRun(runId);
    } catch (error) {
      alert(error.message);
    }
  });

  const automationRestartBtn = document.getElementById("automation-restart-btn");
  automationRestartBtn?.addEventListener("click", async () => {
    const runId = automationRestartBtn.dataset.runId || activeBulkApplicationRunId;
    if (!runId) return;
    try {
      await restartApplicationRun(runId);
    } catch (error) {
      alert(error.message);
    }
  });

  if (pageType === "applications") {
    const clearBulkApplicationsBtn = document.getElementById("clear-bulk-applications-btn");
    const clearSingleApplicationsBtn = document.getElementById("clear-single-applications-btn");
    const clearUrlApplicationsBtn = document.getElementById("clear-url-applications-btn");
    const applicationUrlForm = document.getElementById("application-url-form");
    const applicationUrlInput = document.getElementById("application-url-input");
    const applicationUrlSubmitBtn = document.getElementById("application-url-submit-btn");

    clearBulkApplicationsBtn?.addEventListener("click", async () => {
      if (!window.confirm("Clear all bulk automation runs?")) {
        return;
      }
      try {
        await clearApplicationRuns("bulk");
      } catch (error) {
        alert(error.message);
      }
    });

    clearSingleApplicationsBtn?.addEventListener("click", async () => {
      if (!window.confirm("Clear all single automation runs?")) {
        return;
      }
      try {
        await clearApplicationRuns("single");
      } catch (error) {
        alert(error.message);
      }
    });

    clearUrlApplicationsBtn?.addEventListener("click", async () => {
      if (!window.confirm("Clear all direct URL automation runs?")) {
        return;
      }
      try {
        await clearApplicationRuns("url");
      } catch (error) {
        alert(error.message);
      }
    });

    applicationUrlForm?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const applicationUrl = (applicationUrlInput?.value || "").trim();
      if (!applicationUrl) {
        alert("Please paste an application URL first.");
        return;
      }
      if (applicationUrlSubmitBtn) applicationUrlSubmitBtn.disabled = true;
      try {
        await automateApplicationUrl(applicationUrl);
        if (applicationUrlInput) applicationUrlInput.value = "";
      } catch (error) {
        alert(error.message);
      } finally {
        if (applicationUrlSubmitBtn) applicationUrlSubmitBtn.disabled = false;
      }
    });
  }

  if (pageType !== "scanners") return;
  const runListingBtn = document.getElementById("run-listing-btn");
  const startSchedulerBtn = document.getElementById("start-scheduler-btn");
  const stopSchedulerBtn = document.getElementById("stop-scheduler-btn");
  const stopListingBtn = document.getElementById("stop-listing-btn");
  const clearListingsBtn = document.getElementById("clear-listings-btn");
  const newSourceBtn = document.getElementById("new-source-btn");
  const resetSourceBtn = document.getElementById("reset-source-btn");
  const sourceEditorForm = document.getElementById("source-editor-form");

  runListingBtn?.addEventListener("click", async () => {
    try {
      await runListingNow();
    } catch (error) {
      alert(error.message);
    }
  });

  stopListingBtn?.addEventListener("click", async () => {
    try {
      await stopListingNow();
    } catch (error) {
      alert(error.message);
    }
  });

  startSchedulerBtn?.addEventListener("click", async () => {
    try {
      await startScheduler();
    } catch (error) {
      alert(error.message);
    }
  });

  stopSchedulerBtn?.addEventListener("click", async () => {
    try {
      await stopScheduler();
    } catch (error) {
      alert(error.message);
    }
  });

  clearListingsBtn?.addEventListener("click", async () => {
    if (!window.confirm("Clear all retrieval runs from history?")) {
      return;
    }
    try {
      await clearListingRuns();
    } catch (error) {
      alert(error.message);
    }
  });

  newSourceBtn?.addEventListener("click", () => {
    resetSourceForm();
  });

  resetSourceBtn?.addEventListener("click", () => {
    resetSourceForm();
  });

  sourceEditorForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await saveSource();
      resetSourceForm();
    } catch (error) {
      alert(error.message);
    }
  });
}

async function renderCurrentPage() {
  try {
    await renderJobsPage();
    await renderScannersPage();
    await renderApplicationsPage();
    await renderCandidatesPage();
  } catch (error) {
    console.error(error);
  }
}

initJobsControls();
if (pageType === "jobs") {
  resetSourceForm();
}
renderCurrentPage();
