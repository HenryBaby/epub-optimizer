const form = document.querySelector("#optimizer-form");
const fileInput = document.querySelector("#files");
const dropzone = document.querySelector(".dropzone");
const sourcePicker = document.querySelector("#source-picker");
const chooseFolder = document.querySelector("#choose-folder");
const appendSuffix = document.querySelector("#append-suffix");
const button = document.querySelector("#optimize-button");
const statusTitle = document.querySelector("#status-title");
const statusDetail = document.querySelector("#status-detail");
const statusPill = document.querySelector("#status-pill");
const progressMeter = document.querySelector("#progress-meter");
const taskList = document.querySelector("#processing-log");
const taskCount = document.querySelector("#log-count");
const resultsPanel = document.querySelector("#results-panel");
const resultsList = document.querySelector("#results-list");
const downloadAll = document.querySelector("#download-all");
const exportReport = document.querySelector("#export-report");
const clearDownloads = document.querySelector("#clear-downloads");
const fileSummary = document.querySelector("#file-summary");
const themeToggle = document.querySelector("#theme-toggle");
const analyzeButton = document.querySelector("#analyze-button");
const analysisResults = document.querySelector("#analysis-results");
const automationForm = document.querySelector("#automation-form");
const automationEnabled = document.querySelector("#automation-enabled");
const automationAppendSuffix = document.querySelector("#automation-append-suffix");
const automationPollSeconds = document.querySelector("#automation-poll-seconds");
const automationStableSeconds = document.querySelector("#automation-stable-seconds");
const automationArchiveRetentionDays = document.querySelector("#automation-archive-retention-days");
const automationFailedRetentionDays = document.querySelector("#automation-failed-retention-days");
const automationPill = document.querySelector("#automation-pill");
const automationWatchDir = document.querySelector("#automation-watch-dir");
const automationOutputDir = document.querySelector("#automation-output-dir");
const automationFailedDir = document.querySelector("#automation-failed-dir");
const automationUnprocessedDir = document.querySelector("#automation-unprocessed-dir");
const automationMode = document.querySelector("#automation-mode");
const automationCadence = document.querySelector("#automation-cadence");
const automationRecentSuccess = document.querySelector("#automation-recent-success");
const automationRecentFailed = document.querySelector("#automation-recent-failed");
const automationLastFailure = document.querySelector("#automation-last-failure");
const automationScanState = document.querySelector("#automation-scan-state");
const automationSummary = document.querySelector("#automation-summary");
const automationHistory = document.querySelector("#automation-history");
const automationClearHistory = document.querySelector("#automation-clear-history");
const automationClearArchive = document.querySelector("#automation-clear-archive");
const automationClearFailed = document.querySelector("#automation-clear-failed");
const pipelineWatchCount = document.querySelector("#pipeline-watch-count");
const pipelineWatchSize = document.querySelector("#pipeline-watch-size");
const pipelineOutputCount = document.querySelector("#pipeline-output-count");
const pipelineOutputSize = document.querySelector("#pipeline-output-size");
const pipelineFailedCount = document.querySelector("#pipeline-failed-count");
const pipelineFailedSize = document.querySelector("#pipeline-failed-size");
const pipelineArchiveCount = document.querySelector("#pipeline-archive-count");
const pipelineArchiveSize = document.querySelector("#pipeline-archive-size");
const pipelineLastScan = document.querySelector("#pipeline-last-scan");
const pipelineNextScan = document.querySelector("#pipeline-next-scan");
const pipelineNextScanDetail = document.querySelector("#pipeline-next-scan-detail");
const tabButtons = document.querySelectorAll(".tab-button");
const tabPanels = document.querySelectorAll(".tab-panel");
const STORAGE_KEYS = {
  theme: "epubOptimizerTheme",
  tab: "epubOptimizerTab",
  appendSuffix: "epubOptimizerAppendSuffix",
};

let queueTotal = 0;
let queueCompleted = 0;
let selectedFiles = [];
let selectionMade = false;
let currentRunReport = null;
const TASKS = [
  { key: "start", label: "Preparing EPUB files", icon: "start" },
  { key: "validate", label: "Validating EPUB archives", icon: "validate" },
  { key: "extract", label: "Extracting EPUB workspaces", icon: "extract" },
  { key: "resolve", label: "Resolving package documents", icon: "resolve" },
  { key: "manifest-cleanup", label: "Removing old style and font manifest items", icon: "clean" },
  { key: "file-cleanup", label: "Deleting old style and font files", icon: "clean" },
  { key: "documents", label: "Normalizing content documents", icon: "process" },
  { key: "package", label: "Repackaging optimized EPUBs", icon: "package" },
  { key: "complete", label: "Completing optimized EPUBs", icon: "complete" },
];
const taskRows = new Map();

initializeTheme();
initializeTabs();
initializeManualPreferences();
initializeTasks();
updateFileSummary();
loadAutomation();
setInterval(loadAutomation, 5000);

themeToggle.addEventListener("change", () => {
  setTheme(themeToggle.checked ? "dark" : "light");
});

for (const tabButton of tabButtons) {
  tabButton.addEventListener("click", () => {
    activateTab(tabButton.dataset.tab || "optimizer");
  });
}

fileInput.addEventListener("change", updateFileSummary);

appendSuffix.addEventListener("change", () => {
  localStorage.setItem(STORAGE_KEYS.appendSuffix, appendSuffix.checked ? "true" : "false");
});

for (const eventName of ["dragenter", "dragover"]) {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    if (button.disabled) {
      return;
    }
    dropzone.classList.add("dropzone-active");
  });
}

dropzone.addEventListener("dragleave", (event) => {
  if (!dropzone.contains(event.relatedTarget)) {
    dropzone.classList.remove("dropzone-active");
  }
});

dropzone.addEventListener("drop", async (event) => {
  event.preventDefault();
  dropzone.classList.remove("dropzone-active");
  if (button.disabled) {
    return;
  }

  selectedFiles = await epubFilesFromDataTransfer(event.dataTransfer);
  selectionMade = true;
  fileInput.value = "";
  updateFileSummary();
});

sourcePicker.addEventListener("click", () => {
  fileInput.click();
});

chooseFolder.addEventListener("click", async () => {
  if (!window.showDirectoryPicker) {
    setStatus("Folder picker unavailable", "Use a Chromium-based browser to select folders.");
    return;
  }

  try {
    const directory = await window.showDirectoryPicker();
    selectedFiles = await epubFilesFromDirectory(directory);
    selectionMade = true;
    fileInput.value = "";
    updateFileSummary();
  } catch (error) {
    if (!(error instanceof DOMException && error.name === "AbortError")) {
      setStatus("Folder selection failed", "The folder could not be read.");
    }
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const files = selectedEpubFiles();
  if (files.length === 0) {
    setStatus("No EPUB files selected", "Select EPUB files or a folder containing EPUB files.");
    return;
  }

  resetRun();
  queueTotal = files.length;
  queueCompleted = 0;
  updateProgress();
  setBusy(true);
  setStatus("Uploading", `${files.length} file${files.length === 1 ? "" : "s"} queued.`, "Active");

  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  formData.append("append_suffix", appendSuffix.checked ? "true" : "false");

  try {
    const response = await fetch("/optimize", {
      method: "POST",
      body: formData,
    });

    if (!response.ok || !response.body) {
      throw new Error("Optimization request failed.");
    }

    await readEventStream(response.body);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Optimization failed unexpectedly.";
    setStatus("Processing failed", message, "Error");
    showTaskError(message);
  } finally {
    setBusy(false);
  }
});

analyzeButton.addEventListener("click", async () => {
  const files = selectedEpubFiles();
  analysisResults.replaceChildren();
  if (files.length === 0) {
    analysisResults.append(
      createNotice(
        "No EPUB files selected. Queue a folder or select a single EPUB before analyzing."
      )
    );
    return;
  }

  analyzeButton.disabled = true;
  analyzeButton.textContent = "Analyzing...";
  try {
    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }
    const [dryRunResponse, validationResponse] = await Promise.all([
      fetch("/dry-run", { method: "POST", body: formData }),
      fetch("/validate", { method: "POST", body: cloneFormData(formData) }),
    ]);
    if (!dryRunResponse.ok || !validationResponse.ok) {
      throw new Error("Analysis request failed.");
    }
    const dryRun = await dryRunResponse.json();
    const validation = await validationResponse.json();
    renderAnalysis(dryRun.previews || [], validation.reports || []);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Analysis failed unexpectedly.";
    analysisResults.append(createNotice(message));
  } finally {
    analyzeButton.disabled = false;
    analyzeButton.textContent = "Analyze selected";
  }
});

automationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    enabled: automationEnabled.checked,
    append_suffix: automationAppendSuffix.checked,
    poll_seconds: Number.parseInt(automationPollSeconds.value, 10),
    stable_seconds: Number.parseInt(automationStableSeconds.value, 10),
    archive_retention_days: Number.parseInt(automationArchiveRetentionDays.value, 10),
    failed_retention_days: Number.parseInt(automationFailedRetentionDays.value, 10),
  };
  const response = await fetch("/automation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    automationPill.textContent = "Error";
    return;
  }
  const data = await response.json();
  renderAutomation(data.status);
});

automationClearHistory.addEventListener("click", async () => {
  automationClearHistory.disabled = true;
  const response = await fetch("/automation/history", { method: "DELETE" });
  if (!response.ok) {
    automationPill.textContent = "Error";
    return;
  }
  renderAutomation(await response.json());
});

automationClearArchive.addEventListener("click", () => {
  clearAutomationRetainedFiles("archive", automationClearArchive);
});

automationClearFailed.addEventListener("click", () => {
  clearAutomationRetainedFiles("failed", automationClearFailed);
});

clearDownloads.addEventListener("click", async () => {
  clearDownloads.disabled = true;
  const response = await fetch("/downloads", { method: "DELETE" });
  if (response.ok) {
    resultsList.replaceChildren();
    resultsPanel.hidden = true;
    downloadAll.hidden = true;
    exportReport.hidden = true;
    currentRunReport = null;
  }
  clearDownloads.disabled = false;
});

exportReport.addEventListener("click", () => {
  if (!currentRunReport) {
    return;
  }
  downloadJson(
    `epub-optimizer-report-${new Date().toISOString().replace(/[:.]/g, "-")}.json`,
    currentRunReport,
  );
});

async function readEventStream(stream) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.trim()) {
        handleEvent(JSON.parse(line));
      }
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) {
    handleEvent(JSON.parse(buffer));
  }
}

function handleEvent(event) {
  if (event.type === "file_start") {
    setStatus("Optimizing", `${event.filename} (${event.index} of ${event.total})`, "Active");
    updateTask("start", event.index, event.total);
    return;
  }

  if (event.type === "log") {
    const activity = activityForOptimizerMessage(event.message);
    if (activity) {
      updateTask(activity.key, event.index, event.total);
    }
    return;
  }

  if (event.type === "file_complete") {
    queueCompleted += 1;
    updateProgress();
    setStatus("Optimizing", `Finished ${event.filename}.`, "Active");
    updateTask("complete", event.index, event.total);
    recordRunFile(event);
    appendResult(event);
    return;
  }

  if (event.type === "file_error") {
    queueCompleted += 1;
    updateProgress();
    setStatus("Processing error", event.filename, "Error");
    recordRunFailure(event);
    showTaskError(event.message, event);
    return;
  }

  if (event.type === "error") {
    setStatus("Processing error", event.message, "Error");
    showTaskError(event.message);
    return;
  }

  if (event.type === "complete") {
    queueCompleted = queueTotal;
    updateProgress();
    setStatus(
      "Optimization complete",
      `${event.successful} complete, ${event.failed} failed.`,
      event.failed > 0 ? "Review" : "Done",
    );
    if (event.batch_download_url) {
      downloadAll.href = event.batch_download_url;
      downloadAll.hidden = false;
    }
    finishRunReport(event);
  }
}

function initializeTasks() {
  taskList.replaceChildren();
  taskRows.clear();
  for (const task of TASKS) {
    const row = createTaskRow(task);
    taskRows.set(task.key, row);
    taskList.append(row.item);
  }
  updateTaskSummary();
}

function createTaskRow(task) {
  const item = document.createElement("div");
  item.className = "task-row task-idle";

  const icon = document.createElement("span");
  icon.className = `task-icon log-icon-${task.icon}`;
  icon.setAttribute("aria-hidden", "true");

  const text = document.createElement("span");
  text.className = "task-message";
  text.textContent = task.label;

  const state = document.createElement("span");
  state.className = "task-state";
  state.textContent = "Pending";

  const progress = document.createElement("span");
  progress.className = "task-progress";
  progress.textContent = "0 of 0";

  item.append(icon, text, state, progress);
  return { item, progress, state };
}

function updateTask(key, index, total) {
  const row = taskRows.get(key);
  if (!row) {
    return;
  }
  row.item.className = index >= total ? "task-row task-complete" : "task-row task-active";
  row.state.textContent = index >= total ? "Done" : "Active";
  row.progress.textContent = `${index} of ${total}`;
  updateTaskSummary();
}

function showTaskError(message, event = null) {
  let row = taskRows.get("error");
  const diagnostic = event && event.diagnostic ? event.diagnostic : null;
  const stage = diagnostic && diagnostic.stage ? `${diagnostic.stage}: ` : "";
  const errorMessage = event && event.filename ? `${event.filename}: ${stage}${message}` : `${stage}${message}`;
  if (!row) {
    const task = { key: "error", label: errorMessage, icon: "error" };
    row = createTaskRow(task);
    taskRows.set("error", row);
    taskList.append(row.item);
  }
  row.item.querySelector(".task-message").textContent = errorMessage;
  row.item.title = diagnostic && diagnostic.detail ? diagnostic.detail : "";
  row.item.className = "task-row task-error";
  row.state.textContent = "Error";
  row.progress.textContent =
    event && Number.isInteger(event.index) && Number.isInteger(event.total)
      ? `${event.index} of ${event.total}`
      : "Review";
  updateTaskSummary();
}

function updateTaskSummary() {
  const active = Array.from(taskRows.values()).filter((row) =>
    row.item.classList.contains("task-active") || row.item.classList.contains("task-complete"),
  ).length;
  taskCount.textContent = `${active} of ${TASKS.length} active`;
}

function activityForOptimizerMessage(message) {
  const normalized = message.toLowerCase();
  if (normalized.includes("validated epub archive")) {
    return { key: "validate", message: "Validating EPUB archives" };
  }
  if (normalized.includes("extracted epub")) {
    return { key: "extract", message: "Extracting EPUB workspaces" };
  }
  if (normalized.includes("resolved opf package")) {
    return { key: "resolve", message: "Resolving package documents" };
  }
  if (normalized.includes("removed") && normalized.includes("manifest")) {
    return { key: "manifest-cleanup", message: "Removing old style and font manifest items" };
  }
  if (normalized.includes("deleted") && normalized.includes("style/font file")) {
    return { key: "file-cleanup", message: "Deleting old style and font files" };
  }
  if (normalized.includes("processed") && normalized.includes("content document")) {
    return { key: "documents", message: "Normalizing content documents" };
  }
  if (normalized.includes("repackaged optimized epub")) {
    return { key: "package", message: "Repackaging optimized EPUBs" };
  }
  if (normalized.includes("finished in")) {
    return null;
  }
  return { key: `step:${message}`, message };
}

function appendResult(event) {
  resultsPanel.hidden = false;

  const item = document.createElement("article");
  item.className = "result-item";

  const row = document.createElement("div");
  row.className = "result-row";

  const status = document.createElement("span");
  status.className = "result-status";
  status.textContent = "OK";

  const title = document.createElement("h3");
  title.textContent = event.output_filename;

  const time = document.createElement("span");
  time.className = "result-time";
  time.textContent = `${event.elapsed_seconds.toFixed(2)}s`;

  const detailsToggle = document.createElement("button");
  detailsToggle.className = "details-toggle";
  detailsToggle.type = "button";
  detailsToggle.textContent = "Details";

  const download = document.createElement("a");
  download.className = "button";
  download.href = event.download_url;
  download.textContent = "Download";

  row.append(status, title, time, detailsToggle, download);
  item.append(row);

  const details = document.createElement("div");
  details.className = "result-details";
  details.hidden = true;

  const stats = document.createElement("dl");
  stats.className = "stats";
  addStat(stats, "Input", event.filename);
  addStat(stats, "EPUB version", event.epub_version || "Unknown");
  addStat(stats, "Package", event.package_path);
  addStat(stats, "Documents", event.content_documents_processed);
  addStat(stats, "Stylesheets", event.stylesheets_replaced);
  addStat(stats, "Images", event.images_preserved);
  addStat(stats, "Repairs", (event.repair_actions || []).length);
  const epubcheck = event.epubcheck || {};
  const counts = epubcheck.counts || {};
  addStat(stats, "EPUBCheck", epubcheck.available ? "Available" : "Unavailable");
  const outcome = event.validation_outcome || epubcheck.validation_outcome;
  if (outcome) {
    const labels = { clean: "Clean (no output errors)", legacy_issues: "Legacy issues (pre-existing errors persist)", unavailable: "Unavailable" };
    addStat(stats, "Validation outcome", labels[outcome] || outcome);
  }
  if (epubcheck.available) {
    addStat(stats, "EPUBCheck errors", `introduced ${counts.introduced || 0}, persisting ${counts.persisting || 0}, resolved ${counts.resolved || 0}`);
  }
  details.append(stats);
  details.append(createChangeReport(event));

  if (event.repair_actions && event.repair_actions.length > 0) {
    const repairs = document.createElement("ul");
    repairs.className = "change-report";
    for (const action of event.repair_actions) {
      const item = document.createElement("li");
      item.textContent = action;
      repairs.append(item);
    }
    details.append(repairs);
  }

  if (event.warnings && event.warnings.length > 0) {
    const warnings = document.createElement("ul");
    warnings.className = "log warnings";
    for (const warning of event.warnings) {
      const warningItem = document.createElement("li");
      warningItem.textContent = warning;
      warnings.append(warningItem);
    }
    details.append(warnings);
  }

  if (event.image_diagnostics && event.image_diagnostics.length > 0) {
    const diagnostics = document.createElement("ul");
    diagnostics.className = "change-report";
    for (const diagnostic of event.image_diagnostics) {
      const diagnosticItem = document.createElement("li");
      diagnosticItem.textContent = diagnostic;
      diagnostics.append(diagnosticItem);
    }
    details.append(diagnostics);
  }

  detailsToggle.addEventListener("click", () => {
    const isHidden = details.hidden;
    details.hidden = !isHidden;
    detailsToggle.textContent = isHidden ? "Hide" : "Details";
  });

  item.append(details);
  resultsList.append(item);
}

function addStat(container, labelText, valueText) {
  const wrapper = document.createElement("div");
  const label = document.createElement("dt");
  const value = document.createElement("dd");
  label.textContent = labelText;
  value.textContent = valueText;
  wrapper.append(label, value);
  container.append(wrapper);
}

function resetRun() {
  initializeTasks();
  resultsList.replaceChildren();
  resultsPanel.hidden = true;
  downloadAll.hidden = true;
  exportReport.hidden = true;
  downloadAll.removeAttribute("href");
  currentRunReport = {
    generated_by: "EPUB Optimizer",
    started_at: new Date().toISOString(),
    files: [],
    failures: [],
    summary: null,
  };
  updateProgress();
}

function setStatus(title, detail, pill = "Idle") {
  statusTitle.textContent = title;
  statusDetail.textContent = detail;
  statusPill.textContent = pill;
}

function setBusy(isBusy) {
  button.disabled = isBusy;
  fileInput.disabled = isBusy;
  sourcePicker.disabled = isBusy;
  chooseFolder.disabled = isBusy;
  appendSuffix.disabled = isBusy;
  dropzone.classList.toggle("dropzone-busy", isBusy);
  if (isBusy) {
    dropzone.classList.remove("dropzone-active");
    sourcePicker.blur();
    chooseFolder.blur();
  }
  button.textContent = isBusy ? "Optimizing..." : "Optimize EPUB";
}

function updateProgress() {
  const percent = queueTotal === 0 ? 0 : Math.min(100, (queueCompleted / queueTotal) * 100);
  progressMeter.style.width = `${percent}%`;
}

function updateFileSummary() {
  const inputFiles = Array.from(fileInput.files || []);
  if (inputFiles.length > 0) {
    selectedFiles = inputFiles.filter(isEpubFile);
    selectionMade = true;
  }

  const files = selectedEpubFiles();
  if (files.length === 0) {
    fileSummary.textContent = selectionMade ? "No EPUB files found in selection" : "No files selected";
    return;
  }

  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  fileSummary.textContent = `${files.length} EPUB file${files.length === 1 ? "" : "s"} selected, ${formatBytes(totalBytes)} total`;
}

function selectedEpubFiles() {
  return selectedFiles;
}

async function epubFilesFromDirectory(directory) {
  const files = [];
  await collectEpubFiles(directory, files);
  return files.sort((first, second) => first.name.localeCompare(second.name));
}

async function collectEpubFiles(directory, files) {
  for await (const entry of directory.values()) {
    if (entry.kind === "file" && entry.name.toLowerCase().endsWith(".epub")) {
      files.push(await entry.getFile());
    } else if (entry.kind === "directory") {
      await collectEpubFiles(entry, files);
    }
  }
}

async function epubFilesFromDataTransfer(dataTransfer) {
  const files = [];
  const items = Array.from(dataTransfer.items || []);

  if (items.length > 0 && items.some((item) => "webkitGetAsEntry" in item)) {
    for (const item of items) {
      const entry = item.webkitGetAsEntry();
      if (entry) {
        await collectEpubFilesFromEntry(entry, files);
      }
    }
  } else {
    files.push(...Array.from(dataTransfer.files || []).filter(isEpubFile));
  }

  return files.sort((first, second) => first.name.localeCompare(second.name));
}

async function collectEpubFilesFromEntry(entry, files) {
  if (entry.isFile && entry.name.toLowerCase().endsWith(".epub")) {
    files.push(await fileFromEntry(entry));
    return;
  }

  if (!entry.isDirectory) {
    return;
  }

  const reader = entry.createReader();
  while (true) {
    const entries = await readDirectoryEntries(reader);
    if (entries.length === 0) {
      break;
    }
    for (const child of entries) {
      await collectEpubFilesFromEntry(child, files);
    }
  }
}

function fileFromEntry(entry) {
  return new Promise((resolve, reject) => {
    entry.file(resolve, reject);
  });
}

function readDirectoryEntries(reader) {
  return new Promise((resolve, reject) => {
    reader.readEntries(resolve, reject);
  });
}

function isEpubFile(file) {
  return file.name.toLowerCase().endsWith(".epub");
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function initializeTheme() {
  const storedTheme = localStorage.getItem(STORAGE_KEYS.theme);
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  setTheme(storedTheme || (prefersDark ? "dark" : "light"));
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  themeToggle.checked = theme === "dark";
  localStorage.setItem(STORAGE_KEYS.theme, theme);
}

function initializeTabs() {
  const storedTab = localStorage.getItem(STORAGE_KEYS.tab);
  activateTab(storedTab || "optimizer");
}

function initializeManualPreferences() {
  const storedAppendSuffix = localStorage.getItem(STORAGE_KEYS.appendSuffix);
  if (storedAppendSuffix === "true" || storedAppendSuffix === "false") {
    appendSuffix.checked = storedAppendSuffix === "true";
  }
}

function activateTab(tabName) {
  const panelExists = Array.from(tabPanels).some((panel) => panel.dataset.tabPanel === tabName);
  const nextTab = panelExists ? tabName : "optimizer";

  for (const tabButton of tabButtons) {
    const isActive = tabButton.dataset.tab === nextTab;
    tabButton.classList.toggle("tab-button-active", isActive);
    tabButton.setAttribute("aria-selected", String(isActive));
  }

  for (const panel of tabPanels) {
    const isActive = panel.dataset.tabPanel === nextTab;
    panel.classList.toggle("tab-panel-active", isActive);
    panel.hidden = !isActive;
  }

  document.querySelector("#upload-queue").hidden = !["optimizer", "analyze"].includes(nextTab);

  localStorage.setItem(STORAGE_KEYS.tab, nextTab);
}

async function loadAutomation() {
  try {
    const response = await fetch("/automation", { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Automation status unavailable.");
    }
    renderAutomation(await response.json());
  } catch (_error) {
    automationPill.textContent = "Unavailable";
  }
}

async function clearAutomationRetainedFiles(kind, trigger) {
  trigger.disabled = true;
  const response = await fetch(`/automation/retained/${kind}`, { method: "DELETE" });
  if (response.ok) {
    const data = await response.json();
    renderAutomation(data.status);
  }
  trigger.disabled = false;
}

function renderAutomation(status) {
  const config = status.config || {};
  const paths = status.paths || {};
  const pipeline = status.pipeline || {};
  automationEnabled.checked = Boolean(config.enabled);
  automationAppendSuffix.checked = config.append_suffix !== false;
  automationPollSeconds.value = config.poll_seconds || 10;
  automationStableSeconds.value = config.stable_seconds || 15;
  automationArchiveRetentionDays.value = config.archive_retention_days || 30;
  automationFailedRetentionDays.value = config.failed_retention_days || 30;
  automationWatchDir.textContent = paths.watch_dir || "/watch";
  automationOutputDir.textContent = paths.output_dir || "/output";
  automationFailedDir.textContent = paths.failed_dir || "/failed";
  automationUnprocessedDir.textContent = paths.unprocessed_dir || "/unprocessed";
  automationPill.textContent = config.enabled ? "Watching" : "Disabled";

  const history = status.history || [];
  const failedJobs = history.filter(
    (job) => (job.display_status || job.status) === "failed",
  );
  automationMode.textContent = config.enabled ? "Watching" : "Disabled";
  automationCadence.textContent =
    `${config.poll_seconds || 10}s poll / ${config.stable_seconds || 15}s stable` +
    ` / ${config.archive_retention_days || 30}d archive`;
  automationRecentSuccess.textContent = String(history.filter((job) => job.status === "success").length);
  automationRecentFailed.textContent = String(failedJobs.length);
  automationLastFailure.textContent =
    failedJobs.length === 0 ? "None" : failureSummary(failedJobs[0]);
  renderPipeline(pipeline);
  automationSummary.textContent =
    history.length === 0 ? "No jobs yet" : `${history.length} recent job${history.length === 1 ? "" : "s"}`;
  automationClearHistory.disabled = history.length === 0;
  automationHistory.replaceChildren();
  for (const job of history) {
    automationHistory.append(createAutomationJob(job));
  }
}

function createChangeReport(event) {
  const report = document.createElement("ul");
  report.className = "change-report";
  const changes = [
    `Replaced ${event.stylesheets_replaced} stylesheet/font manifest item${event.stylesheets_replaced === 1 ? "" : "s"}.`,
    `Normalized ${event.content_documents_processed} content document${event.content_documents_processed === 1 ? "" : "s"}.`,
    `Preserved ${event.images_preserved} image resource${event.images_preserved === 1 ? "" : "s"}.`,
    `Resolved package document: ${event.package_path}.`,
  ];
  for (const change of changes) {
    const item = document.createElement("li");
    item.textContent = change;
    report.append(item);
  }
  return report;
}

function cloneFormData(formData) {
  const clone = new FormData();
  for (const [key, value] of formData.entries()) {
    clone.append(key, value);
  }
  return clone;
}

function renderAnalysis(previews, reports) {
  analysisResults.replaceChildren();
  if (previews.length === 0) {
    analysisResults.append(createNotice("No analyzable EPUB files found."));
    return;
  }
  const reportByName = new Map(reports.map((report) => [report.filename, report]));
  for (const preview of previews) {
    analysisResults.append(createAnalysisItem(preview, reportByName.get(preview.filename)));
  }
}

function createAnalysisItem(preview, report) {
  const item = document.createElement("article");
  item.className = `result-item analysis-item ${preview.status === "ok" ? "" : "automation-job-failed"}`;

  const row = document.createElement("div");
  row.className = "result-row";
  const status = document.createElement("span");
  status.className = "result-status";
  status.textContent = preview.status === "ok" && report && report.valid ? "OK" : "!";
  const title = document.createElement("h3");
  title.textContent = preview.filename;
  row.append(status, title);
  item.append(row);

  if (preview.status !== "ok") {
    item.append(createNotice(preview.message || "Analysis failed."));
    return item;
  }

  const stats = document.createElement("dl");
  stats.className = "stats";
  addStat(stats, "EPUB version", preview.epub_version || "Unknown");
  addStat(stats, "Package", preview.package_path);
  addStat(stats, "Documents", preview.content_documents);
  addStat(stats, "Style/font items", preview.stylesheets_and_fonts);
  addStat(stats, "Files removed", preview.removable_files);
  addStat(stats, "Images", preview.images_preserved);
  addStat(stats, "Validation", report && report.valid ? "Clean" : "Issues found");
  item.append(stats);

  if (preview.change_summary && preview.change_summary.length > 0) {
    const heading = document.createElement("h4");
    heading.className = "analysis-section-heading";
    heading.textContent = "Planned optimization";
    const summary = document.createElement("ul");
    summary.className = "change-report analysis-report";
    for (const change of preview.change_summary) {
      const summaryItem = document.createElement("li");
      summaryItem.textContent = change;
      summary.append(summaryItem);
    }
    item.append(heading);
    item.append(summary);
  }

  if (preview.image_diagnostics && preview.image_diagnostics.length > 0) {
    const heading = document.createElement("h4");
    heading.className = "analysis-section-heading";
    heading.textContent = "Image resources";
    const diagnostics = document.createElement("ul");
    diagnostics.className = "change-report analysis-report image-diagnostics";
    for (const diagnostic of preview.image_diagnostics) {
      const diagnosticItem = document.createElement("li");
      diagnosticItem.textContent = diagnostic;
      diagnostics.append(diagnosticItem);
    }
    item.append(heading);
    item.append(diagnostics);
  }

  if (report && report.issues && report.issues.length > 0) {
    const heading = document.createElement("h4");
    heading.className = "analysis-section-heading";
    heading.textContent = "Validation issues";
    const issues = document.createElement("ul");
    issues.className = "log warnings";
    for (const issue of report.issues) {
      const issueItem = document.createElement("li");
      issueItem.textContent = `${issue.code}: ${issue.message}`;
      issues.append(issueItem);
    }
    item.append(heading);
    item.append(issues);
  }
  return item;
}

function createNotice(message) {
  const notice = document.createElement("p");
  notice.className = "notice";
  notice.textContent = message;
  return notice;
}

function renderPipeline(pipeline) {
  renderPipelineCard(pipelineWatchCount, pipelineWatchSize, pipeline.watch);
  renderPipelineCard(pipelineOutputCount, pipelineOutputSize, pipeline.output);
  renderPipelineCard(pipelineFailedCount, pipelineFailedSize, pipeline.failed);
  renderPipelineCard(pipelineArchiveCount, pipelineArchiveSize, pipeline.archive);
  pipelineLastScan.textContent = pipeline.last_scan_at ? formatTimestamp(pipeline.last_scan_at) : "Never";

  if (typeof pipeline.seconds_until_next_scan === "number") {
    automationScanState.textContent = `Next scan in ${pipeline.seconds_until_next_scan}s`;
    pipelineNextScan.textContent = `${pipeline.seconds_until_next_scan}s`;
    pipelineNextScanDetail.textContent = pipeline.next_scan_at
      ? formatTimestamp(pipeline.next_scan_at)
      : "Scheduled";
  } else if (pipeline.last_scan_at) {
    automationScanState.textContent = "Watcher idle";
    pipelineNextScan.textContent = "Idle";
    pipelineNextScanDetail.textContent = "Disabled";
  } else {
    automationScanState.textContent = "No scans yet";
    pipelineNextScan.textContent = "Idle";
    pipelineNextScanDetail.textContent = "No schedule";
  }
}

function renderPipelineCard(countElement, sizeElement, value = {}) {
  countElement.textContent = String(value.count || 0);
  sizeElement.textContent = formatBytes(value.bytes || 0);
}

function formatTimestamp(timestampSeconds) {
  return new Date(timestampSeconds * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function createAutomationJob(job) {
  const displayStatus = job.display_status || job.status;
  const item = document.createElement("article");
  item.className = `automation-job automation-job-${displayStatus}`;

  const title = document.createElement("h3");
  title.textContent =
    displayStatus === "success"
      ? `${job.filename} -> ${job.output_filename}`
      : displayStatus === "requeued"
        ? `${job.filename} queued for reprocessing`
        : displayStatus === "resolved"
          ? `${job.filename} previous failure resolved`
          : `${job.filename} failed`;

  const detail = document.createElement("p");
  const elapsed =
    typeof job.elapsed_seconds === "number" ? ` ${job.elapsed_seconds.toFixed(2)}s.` : "";
  detail.textContent =
    displayStatus === "failed"
      ? `${failureSummary(job)}${elapsed}`
      : displayStatus === "resolved"
        ? "Resolved by a later successful run."
        : `${job.message || "No details."}${elapsed}`;

  item.append(title, detail);
  const validationOutcome = job.epubcheck && job.epubcheck.validation_outcome;
  if (validationOutcome) {
    const validation = document.createElement("p");
    validation.textContent =
      validationOutcome === "clean"
        ? "EPUBCheck clean."
        : validationOutcome === "legacy_issues"
          ? `Optimized with ${job.epubcheck.remaining || 0} pre-existing validation issue(s).`
          : "EPUBCheck unavailable.";
    item.append(validation);
  }
  if (job.repair_actions && job.repair_actions.length > 0) {
    const repairs = document.createElement("ul");
    repairs.className = "log";
    for (const action of job.repair_actions) {
      const repairItem = document.createElement("li");
      repairItem.textContent = action;
      repairs.append(repairItem);
    }
    item.append(repairs);
  }
  if (displayStatus === "failed" && job.diagnostic) {
    item.append(createFailureDetails(job.diagnostic));
  }
  if (displayStatus === "failed" && job.reprocessable) {
    item.append(createReprocessButton(job.failed_filename || job.filename));
  }
  return item;
}

function createReprocessButton(filename) {
  const control = document.createElement("div");
  control.className = "reprocess-control";
  const button = document.createElement("button");
  button.className = "details-toggle";
  button.type = "button";
  button.textContent = "Reprocess";
  button.addEventListener("click", async () => {
    control.querySelector(".reprocess-error")?.remove();
    button.disabled = true;
    button.textContent = "Queuing…";
    try {
      const response = await fetch("/automation/reprocess", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const error = document.createElement("p");
        error.className = "reprocess-error";
        error.textContent = payload.detail || "Could not queue this EPUB for reprocessing.";
        control.append(error);
        button.disabled = response.status === 404;
        button.textContent = response.status === 404 ? "Unavailable" : "Try again";
        if (response.status === 404) {
          window.setTimeout(loadAutomation, 1500);
        }
        return;
      }
      const data = await response.json();
      renderAutomation(data.status);
    } catch (_error) {
      const error = document.createElement("p");
      error.className = "reprocess-error";
      error.textContent = "Could not contact the optimizer. Check the connection and try again.";
      control.append(error);
      button.disabled = false;
      button.textContent = "Try again";
    }
  });
  control.append(button);
  return control;
}

function failureSummary(job) {
  const diagnostic = job.diagnostic || {};
  const stage = diagnostic.stage || "Unknown stage";
  const message = diagnostic.message || job.message || "Optimization failed.";
  return `${stage}: ${message}`;
}

function createFailureDetails(diagnostic) {
  const details = document.createElement("details");
  details.className = "failure-details";

  const summary = document.createElement("summary");
  summary.textContent = "Failure details";
  details.append(summary);

  const list = document.createElement("dl");
  list.className = "failure-detail-list";
  addFailureDetail(list, "Exception", diagnostic.exception_type);
  addFailureDetail(list, "Detail", diagnostic.detail);
  addFailureDetail(list, "Internal path", diagnostic.internal_path);
  addFailureDetail(list, "Failed file", diagnostic.failed_path);
  addFailureDetail(list, "Report", diagnostic.report_path);
  addFailureDetail(list, "Next action", failureAction(diagnostic));
  details.append(list);
  return details;
}

function failureAction(diagnostic) {
  if (diagnostic.exception_type === "InvalidEpubError") {
    return "Check EPUB structure, repair the source file, then reprocess it.";
  }
  if (diagnostic.failed_path) {
    return "Inspect the failed file and error report, then use Reprocess when ready.";
  }
  return "Review the error detail and retry after correcting the source EPUB.";
}

function addFailureDetail(list, labelText, valueText) {
  if (!valueText) {
    return;
  }
  const wrapper = document.createElement("div");
  const label = document.createElement("dt");
  const value = document.createElement("dd");
  label.textContent = labelText;
  value.textContent = valueText;
  wrapper.append(label, value);
  list.append(wrapper);
}

function recordRunFile(event) {
  if (!currentRunReport) {
    return;
  }
  currentRunReport.files.push({
    input_filename: event.filename,
    output_filename: event.output_filename,
    download_name: event.download_name,
    epub_version: event.epub_version,
    package_path: event.package_path,
    elapsed_seconds: event.elapsed_seconds,
    content_documents_processed: event.content_documents_processed,
    stylesheets_replaced: event.stylesheets_replaced,
    images_preserved: event.images_preserved,
    image_diagnostics: event.image_diagnostics || [],
    repair_actions: event.repair_actions || [],
    validation_outcome: event.validation_outcome || null,
    validation_remaining: event.validation_remaining || 0,
    validation_persisting: event.validation_persisting || 0,
    epubcheck: event.epubcheck || null,
    warnings: event.warnings || [],
  });
}

function recordRunFailure(event) {
  if (!currentRunReport) {
    return;
  }
  currentRunReport.failures.push({
    input_filename: event.filename,
    message: event.message,
    stage: event.stage,
    exception_type: event.exception_type,
    detail: event.detail,
    diagnostic: event.diagnostic || null,
  });
}

function finishRunReport(event) {
  if (!currentRunReport) {
    return;
  }
  currentRunReport.finished_at = new Date().toISOString();
  currentRunReport.summary = {
    total: event.total,
    successful: event.successful,
    failed: event.failed,
    batch_download_url: event.batch_download_url || null,
  };
  exportReport.hidden = false;
}

function downloadJson(filename, value) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// Grimmory is manual-only. Status reads never connect, scan, or start a job.
(() => {
  const panel = document.querySelector('[data-tab-panel="grimmory"]');
  if (!panel) return;
  const find = (name) => document.querySelector(`#grimmory-${name}`);
  const connectForm = find("connect-form");
  const mappingList = find("mappings");
  const maintenance = find("maintenance");
  let state = {};
  let plan = null;
  let busy = false;
  let pollTimer = null;
  let mappings = [];
  let mappingsBaseUrl = null;
  let choosingFolders = false;
  let busyAction = "";
  const renderSignatures = new Map();

  function message(text, error = false) {
    const target = find("message");
    target.textContent = text;
    target.hidden = !text;
    target.classList.toggle("is-error", error);
    target.setAttribute("role", error ? "alert" : "status");
  }

  // Reuse unchanged sections and restore disclosure state when status advances.
  function renderChanged(name, value, callback) {
    const signature = JSON.stringify(value);
    if (renderSignatures.get(name) === signature) return;
    const target = find(name);
    const focused = target.contains(document.activeElement) ? document.activeElement : null;
    const focusedKey = focused?.closest("details")?.dataset.key;
    const focusedTag = focused?.tagName;
    const open = new Map(Array.from(target.querySelectorAll("details")).map((node) => [node.dataset.key, node.open]));
    callback(target);
    target.querySelectorAll("details").forEach((node) => {
      if (open.has(node.dataset.key)) node.open = open.get(node.dataset.key);
      if (focusedKey && node.dataset.key === focusedKey && focusedTag) {
        node.querySelector(focusedTag.toLowerCase())?.focus({ preventScroll: true });
      }
    });
    renderSignatures.set(name, signature);
  }

  function currentJob() {
    if (state.active_job && typeof state.active_job === "object") return state.active_job;
    return state.job || state.jobs?.find((job) => job.id === state.active_job) || state.jobs?.at(-1);
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }

  function active() {
    const job = currentJob() || {};
    return state.running === true || Boolean(state.active_job) || state.active === true || job.active === true ||
      ["backing_up", "backup", "optimizing", "restoring", "running", "cancelling"].includes(job.phase || job.status);
  }

  function updateControls() {
    const locked = busy || active();
    connectForm.querySelectorAll("input, button").forEach((node) => { node.disabled = locked; });
    mappingList.querySelectorAll("input").forEach((node) => { node.disabled = locked; });
    maintenance.disabled = locked;
    find("preview").disabled = locked || !state.connected || !mappings.some((row) => row.selected.checked);
    const receipt = state.watcher_maintenance;
    const pendingReceipt = receipt && receipt.status !== "resumed";
    const selectedIds = selectedLibraryIds();
    const sameSelection = pendingReceipt && receipt.base_url === state.base_url &&
      receipt.libraries.length === selectedIds.length && receipt.libraries.every((library) => selectedIds.includes(library.library_id));
    find("pause-watching").disabled = locked || !state.connected || !selectedIds.length ||
      (pendingReceipt && (!sameSelection || receipt.libraries.some((library) => ["resume_pending", "restored"].includes(library.status))));
    find("resume-watching").disabled = locked || !state.connected || !pendingReceipt || receipt.base_url !== state.base_url;
    find("start").disabled = locked || !plan?.plan_id || !maintenance.checked;
    find("cancel").disabled = busy || !active();
    find("refresh").disabled = busy;
    find("snapshots").querySelectorAll("button").forEach((node) => {
      node.disabled = locked || !maintenance.checked;
    });
    find("edit-folders").disabled = locked;
    find("new-run").disabled = locked;
    const selected = mappings.filter((row) => row.selected.checked).length;
    find("selection-count").textContent = `${selected} selected`;
    const hasJob = Boolean(currentJob()) && !choosingFolders;
    const step = active() ? "run" : !state.connected ? "connect" : plan ? "prepare" : hasJob ? "review" : "folders";
    panel.dataset.uiPhase = step;
    panel.classList.toggle("is-busy", busy || active());
    panel.setAttribute("aria-busy", String(busy));
    panel.querySelectorAll("[data-step]").forEach((node) => {
      if (node.dataset.step === step) node.setAttribute("aria-current", "step");
      else node.removeAttribute("aria-current");
    });
    find("folder-step").hidden = step !== "folders";
    find("prepare-step").hidden = step !== "prepare";
    const watchingActions = find(step === "prepare" ? "prepare-actions" : "folder-actions");
    if (find("pause-watching").parentElement !== watchingActions) watchingActions.append(find("pause-watching"));
    find("progress").hidden = !["run", "review"].includes(step);
    find("maintenance-confirmation").hidden = !plan && !find("past-activity").open;
    find("start").hidden = step !== "prepare";
    find("cancel").hidden = !active();
    find("review-actions").hidden = step !== "review";
    find("next-step").textContent = {
      connect: "Connect to choose the folders you want to optimize.",
      folders: "Choose folders, pause watching, then preview the backup scope.",
      prepare: "Review the scope and confirm writers are paused before starting.",
      run: "Keep writers paused while your library is being maintained.",
      review: "Review the outcome, then explicitly resume previous watching states.",
    }[step];
    const labels = {
      preview: "Preview folders", "pause-watching": "Pause watching",
      "resume-watching": "Resume watching", start: "Back up & optimize", cancel: "Cancel safely",
    };
    for (const [name, label] of Object.entries(labels)) {
      find(name).textContent = busy && busyAction === name ? "Working…" : label;
      find(name).classList.toggle("is-loading", busy && busyAction === name);
    }
    const submit = connectForm.querySelector('button[type="submit"]');
    submit.textContent = busy && busyAction === "connect" ? "Connecting…" : "Connect";
  }

  function invalidatePlan() {
    plan = null;
    find("plan").hidden = true;
    maintenance.checked = false;
    updateControls();
  }

  function renderMappings() {
    const drafts = mappingsBaseUrl === state.base_url ? mappings.map((row) => ({
      library_id: row.library_id, remote_path: row.remote_path,
      checked: row.selected.checked, local_path: row.local.value,
    })) : [];
    mappingsBaseUrl = state.base_url;
    mappingList.replaceChildren();
    mappings = [];
    for (const library of state.libraries || []) {
      for (const remote of library.paths || []) {
        const remotePath = typeof remote === "string" ? remote : remote.path;
        const row = element("div", undefined, "grimmory-mapping");
        const label = element("label", undefined, "filename-option");
        const selected = document.createElement("input");
        selected.type = "checkbox";
        selected.setAttribute("aria-label", `Select ${library.name}: ${remotePath}`);
        const badge = element("span", library.watch === false ? "Watching off" : library.watch === true ? "Watching on" : "Watching unknown", "watch-badge");
        badge.dataset.libraryId = String(library.id);
        label.append(selected, element("strong", library.name), badge);
        const paths = element("div", undefined, "mapping-paths");
        paths.append(element("p", `Grimmory · ${remotePath}`, "notice"));
        const field = element("label", "Mounted path", "field-row");
        const local = document.createElement("input");
        local.type = "text";
        local.placeholder = "/libraries/books";
        local.autocomplete = "off";
        const draft = drafts.find((mapping) =>
          mapping.library_id === library.id && mapping.remote_path === remotePath);
        const saved = (state.mappings || []).find((mapping) =>
          mapping.library_id === library.id && mapping.remote_path === remotePath);
        if (draft) {
          selected.checked = draft.checked;
          local.value = draft.local_path;
        } else if (saved) {
          selected.checked = true;
          local.value = saved.local_path;
        }
        field.append(local);
        paths.append(field);
        row.append(label, paths);
        mappingList.append(row);
        mappings.push({ library_id: library.id, remote_path: remotePath, selected, local });
        selected.addEventListener("change", invalidatePlan);
        local.addEventListener("input", invalidatePlan);
      }
    }
    if (!mappings.length) mappingList.append(element("p", "No library folders discovered. Connect to Grimmory to continue.", "notice"));
  }

  function selectedLibraryIds() {
    return [...new Set(mappings.filter((row) => row.selected.checked).map((row) => row.library_id))];
  }

  function renderWatcherMaintenance() {
    const target = find("watcher-maintenance");
    target.replaceChildren();
    const receipt = state.watcher_maintenance;
    find("watching").hidden = !receipt;
    if (!receipt) return;
    const pending = receipt.status !== "resumed";
    find("watching").classList.toggle("watching-pending", pending);
    find("resume-watching").hidden = !pending;
    const heading = !pending ? "Previous watching states restored" : receipt.status === "paused" ? "Watching paused" : "Watching needs your attention";
    target.append(element("h3", heading));
    const list = element("ul");
    for (const library of receipt.libraries || []) {
      const labels = {
        paused: "Watching paused", already_disabled: "Watching was already disabled",
        failed: "Watching update failed", unmodified: "Watching was already disabled",
        pause_pending: "Pause not yet verified", resume_pending: "Resume not yet verified", resumed: "Previous watching state restored",
        restored: "Previous watching state restored", pending: "Awaiting watching update",
      };
      list.append(element("li", `${library.name || `Library ${library.library_id}`} — ${labels[library.status] || library.status}${library.error ? `: ${library.error}` : ""}`));
    }
    if (receipt.libraries?.some((library) => library.error)) list.setAttribute("role", "alert");
    target.append(list);
    if (pending) {
      target.append(element("p", "Watching stays paused after completion and restarts. Resume restores previous settings."));
      if (!state.connected || receipt.base_url !== state.base_url) {
        target.append(element("p", `Reconnect to ${receipt.base_url} to resume the saved previous watching states.`));
      }
    }
  }

  function renderPlan() {
    const target = find("plan");
    target.replaceChildren();
    target.hidden = !plan;
    if (!plan) return;
    target.append(element("h3", "Backup preview"));
    renderScope(target, plan);
  }

  function renderScope(target, preview) {
    target.append(element("p", `${preview.epub_count || 0} EPUBs to optimize · ${preview.files || 0} files to back up · ${formatBytes(preview.bytes || 0)}`));
    const scope = element("ul", undefined, "change-report");
    for (const mapping of preview.mappings || []) {
      scope.append(element("li", `${mapping.remote_path} → ${mapping.local_path} (optimizer container)`));
    }
    target.append(scope);
  }

  function renderJob(target, job) {
    const results = job.results || [];
    const finished = results.filter((item) => ["optimized", "restored"].includes(item.status)).length;
    const failed = results.filter((item) => item.status === "failed").length;
    const phases = {
      backing_up: "Backing up and verifying library folders",
      running: "Optimizing EPUBs",
      restoring: "Restoring library folders",
      completed: "Completed",
      cancelled: "Cancelled safely",
      failed: "Failed",
      interrupted: "Interrupted; review the snapshot before continuing",
    };
    target.append(element("h3", job.status === "completed" && failed ? "Completed with issues" : phases[job.phase || job.status] || job.phase || job.status || "Idle"));
    if (results.length) target.append(element("p", `${finished} completed · ${failed} failed`, failed ? "warnings" : undefined));
    if (active() && job === currentJob()) {
      const meter = element("div", undefined, "meter grimmory-meter");
      meter.setAttribute("role", "progressbar");
      meter.setAttribute("aria-label", "Library maintenance in progress");
      const total = (job.phase || job.status) === "backing_up" ? null : job.plan?.epub_count || plan?.epub_count;
      if (total) {
        meter.setAttribute("aria-valuemin", "0");
        meter.setAttribute("aria-valuemax", String(total));
        meter.setAttribute("aria-valuenow", String(Math.min(total, results.length)));
      } else meter.classList.add("is-indeterminate");
      const fill = element("span");
      fill.style.width = total ? `${Math.min(100, results.length / total * 100)}%` : "35%";
      meter.append(fill);
      target.append(meter);
    }
    if (job.message) target.append(element("p", job.message));
    if (results.length) {
      if (failed) {
        const failures = element("div", undefined, "grimmory-failures");
        failures.setAttribute("role", "alert");
        failures.append(element("h4", `${failed} ${failed === 1 ? "file needs" : "files need"} attention`));
        const list = element("ul", undefined, "change-report");
        results.filter((result) => result.status === "failed").forEach((result) => {
          list.append(element("li", `${result.path || result.filename || "File"}${result.message ? ` — ${result.message}` : ""}`));
        });
        failures.append(list);
        target.append(failures);
      }
      const details = element("details", undefined, "failure-details");
      details.dataset.key = `results-${job.id || job.job_id || "current"}`;
      details.append(element("summary", `Per-file results (${results.length})`));
      const list = element("ul", undefined, "change-report");
      for (const result of [...results].sort((left, right) => Number(right.status === "failed") - Number(left.status === "failed"))) {
        list.append(element("li", `${result.path || result.filename || "File"} — ${result.status}${result.message ? `: ${result.message}` : ""}`));
      }
      details.append(list);
      target.append(details);
      if (active()) target.append(element("p", `Latest file: ${results.at(-1).path || results.at(-1).filename || "Preparing"}`));
    }
  }

  function renderRecords(target, records, snapshot = false) {
    target.replaceChildren();
    for (const record of records || []) {
      const card = element("details", undefined, "grimmory-record");
      card.dataset.key = `${snapshot ? "snapshot" : "run"}-${record.snapshot_id || record.id || record.job_id}`;
      const date = record.created_at ? new Date(record.created_at * 1000).toLocaleString() : "Date unavailable";
      card.append(element("summary", `${snapshot ? "Backup" : "Run"} · ${date} · ${record.status || record.phase || "available"}`));
      card.append(element("p", `ID: ${record.snapshot_id || record.id || record.job_id || "Unavailable"}`, "technical-id notice"));
      if (snapshot) {
        card.append(element("p", `Snapshot status: ${record.status || "available"}`));
        renderScope(card, record.plan || {});
      } else renderJob(card, record);
      if (snapshot && (record.snapshot_id || record.id)) {
        const restore = element("button", "Restore this library-folder snapshot");
        restore.type = "button";
        restore.addEventListener("click", () => {
          if (!maintenance.checked) return;
          const scope = record.snapshot_id || record.id;
          if (!window.confirm(`Restore library-folder snapshot ${scope}? Files covered by this snapshot will be replaced. All writers must remain paused.`)) return;
          run("restore", { snapshot_id: scope, maintenance_confirmed: true });
        });
        card.append(restore);
      }
      target.append(card);
    }
    if (!target.childElementCount) target.append(element("p", "No records yet.", "notice"));
  }

  function render(next, refreshMappings = false) {
    const wasConnected = state.connected;
    state = next;
    find("pill").textContent = active() ? "Maintenance active" : (state.connected ? "Connected" : "Disconnected");
    if (refreshMappings) renderMappings();
    // Watch changes update badges without replacing the inputs or their drafts.
    mappingList.querySelectorAll(".watch-badge").forEach((badge) => {
      const library = (state.libraries || []).find((item) => String(item.id) === badge.dataset.libraryId);
      badge.textContent = library?.watch === false ? "Watching off" : library?.watch === true ? "Watching on" : "Watching unknown";
    });
    find("connection-summary").textContent = state.connected ? `Connected · ${state.base_url || "Grimmory"}` : "Connect to Grimmory";
    if (state.connected && !wasConnected) find("connection").open = false;
    if (!state.connected) find("connection").open = true;
    renderChanged("watcher-maintenance", [state.watcher_maintenance, state.connected, state.base_url], renderWatcherMaintenance);
    renderChanged("progress", [currentJob(), active()], (progress) => {
      progress.replaceChildren();
      if (currentJob()) renderJob(progress, currentJob());
    });
    renderChanged("history", state.history || state.jobs || [], (target) => renderRecords(target, state.history || state.jobs));
    renderChanged("snapshots", state.snapshots || [], (target) => renderRecords(target, state.snapshots, true));
    find("activity-count").textContent = `${(state.history || state.jobs || []).length} runs · ${(state.snapshots || []).length} backups`;
    updateControls();
    clearTimeout(pollTimer);
    if (active()) pollTimer = setTimeout(loadStatus, 1500);
  }

  async function request(path, payload) {
    const response = await fetch(`/grimmory${path}`, payload === undefined ? {
      cache: "no-store",
    } : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Grimmory request failed.");
    return result;
  }

  async function loadStatus() {
    try {
      render(await request(""), mappings.length === 0);
    } catch (error) {
      message(error.message, true);
      clearTimeout(pollTimer);
    }
  }

  async function run(action, payload) {
    busy = true;
    busyAction = action;
    message("");
    updateControls();
    try {
      const result = await request(`/${action}`, payload);
      if (action === "preview") {
        choosingFolders = false;
        plan = result;
        renderPlan();
      } else if (["connect", "pause-watching", "resume-watching"].includes(action)) {
        if (action === "connect") choosingFolders = true;
        invalidatePlan();
        maintenance.checked = false;
      } else if (action === "start" || action === "restore") {
        choosingFolders = false;
        invalidatePlan();
        maintenance.checked = false;
      }
      if (["connect", "pause-watching", "resume-watching"].includes(action)) render(result, true);
      else render(await request(""));
      if (action === "preview") message("Preview ready. Confirm maintenance before starting.");
      else if (action === "pause-watching") {
        const receipt = state.watcher_maintenance;
        const paused = receipt?.status === "paused" && !receipt.libraries?.some((library) => library.error);
        message(paused ? "Watching paused. Preview folders to continue." : "Watching updated. Review any watching errors, then preview folders again to confirm the current scope.");
      }
    } catch (error) {
      message(error.message, true);
    } finally {
      busy = false;
      updateControls();
    }
  }

  connectForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const payload = {
      base_url: find("url").value,
      username: find("username").value,
      password: find("password").value,
    };
    find("password").value = "";
    run("connect", payload);
  });
  find("preview").addEventListener("click", () => {
    invalidatePlan();
    run("preview", { mappings: mappings.filter((row) => row.selected.checked).map((row) => ({
      library_id: row.library_id,
      remote_path: row.remote_path,
      local_path: row.local.value,
    })) });
  });
  find("pause-watching").addEventListener("click", () => {
    const libraryIds = selectedLibraryIds();
    if (busy || active() || !state.connected || !libraryIds.length) return;
    invalidatePlan();
    maintenance.checked = false;
    run("pause-watching", { library_ids: libraryIds });
  });
  find("resume-watching").addEventListener("click", () => {
    const receipt = state.watcher_maintenance;
    if (busy || active() || !state.connected || !receipt?.session_id || receipt.base_url !== state.base_url) return;
    invalidatePlan();
    maintenance.checked = false;
    run("resume-watching", { session_id: receipt.session_id });
  });
  find("start").addEventListener("click", () => {
    if (!busy && !active() && plan?.plan_id && maintenance.checked) run("start", { plan_id: plan.plan_id, maintenance_confirmed: true });
  });
  find("cancel").addEventListener("click", () => { if (!busy && active()) run("cancel", {}); });
  find("refresh").addEventListener("click", loadStatus);
  maintenance.addEventListener("change", updateControls);
  find("past-activity").addEventListener("toggle", updateControls);
  function editFolders() {
    choosingFolders = true;
    invalidatePlan();
    message("");
  }
  find("edit-folders").addEventListener("click", editFolders);
  find("new-run").addEventListener("click", editFolders);
  loadStatus();
})();
