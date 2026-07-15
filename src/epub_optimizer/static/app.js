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
const fileSummary = document.querySelector("#file-summary");
const themeToggle = document.querySelector("#theme-toggle");
const automationForm = document.querySelector("#automation-form");
const automationEnabled = document.querySelector("#automation-enabled");
const automationAppendSuffix = document.querySelector("#automation-append-suffix");
const automationProfile = document.querySelector("#automation-profile");
const automationPollSeconds = document.querySelector("#automation-poll-seconds");
const automationStableSeconds = document.querySelector("#automation-stable-seconds");
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
const pipelineWatchCount = document.querySelector("#pipeline-watch-count");
const pipelineWatchSize = document.querySelector("#pipeline-watch-size");
const pipelineOutputCount = document.querySelector("#pipeline-output-count");
const pipelineOutputSize = document.querySelector("#pipeline-output-size");
const pipelineFailedCount = document.querySelector("#pipeline-failed-count");
const pipelineFailedSize = document.querySelector("#pipeline-failed-size");
const pipelineArchiveCount = document.querySelector("#pipeline-archive-count");
const pipelineArchiveSize = document.querySelector("#pipeline-archive-size");
const tabButtons = document.querySelectorAll(".tab-button");
const tabPanels = document.querySelectorAll(".tab-panel");

let queueTotal = 0;
let queueCompleted = 0;
let selectedFiles = [];
let selectionMade = false;
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

automationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    enabled: automationEnabled.checked,
    append_suffix: automationAppendSuffix.checked,
    profile: automationProfile.value,
    poll_seconds: Number.parseInt(automationPollSeconds.value, 10),
    stable_seconds: Number.parseInt(automationStableSeconds.value, 10),
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
    appendResult(event);
    return;
  }

  if (event.type === "file_error") {
    queueCompleted += 1;
    updateProgress();
    setStatus("Processing error", event.filename, "Error");
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
  details.append(stats);

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
  downloadAll.removeAttribute("href");
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
  const storedTheme = localStorage.getItem("epubOptimizerTheme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  setTheme(storedTheme || (prefersDark ? "dark" : "light"));
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  themeToggle.checked = theme === "dark";
  localStorage.setItem("epubOptimizerTheme", theme);
}

function initializeTabs() {
  const storedTab = localStorage.getItem("epubOptimizerTab");
  activateTab(storedTab || "optimizer");
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

  localStorage.setItem("epubOptimizerTab", nextTab);
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

function renderAutomation(status) {
  const config = status.config || {};
  const paths = status.paths || {};
  const pipeline = status.pipeline || {};
  renderAutomationProfiles(status.profiles || [], config.profile || "default");
  automationEnabled.checked = Boolean(config.enabled);
  automationAppendSuffix.checked = config.append_suffix !== false;
  automationProfile.value = config.profile || "default";
  automationPollSeconds.value = config.poll_seconds || 10;
  automationStableSeconds.value = config.stable_seconds || 15;
  automationWatchDir.textContent = paths.watch_dir || "/watch";
  automationOutputDir.textContent = paths.output_dir || "/output";
  automationFailedDir.textContent = paths.failed_dir || "/failed";
  automationUnprocessedDir.textContent = paths.unprocessed_dir || "/unprocessed";
  automationPill.textContent = config.enabled ? "Watching" : "Disabled";

  const history = status.history || [];
  const failedJobs = history.filter((job) => job.status === "failed");
  automationMode.textContent = config.enabled ? "Watching" : "Disabled";
  automationCadence.textContent = `${config.poll_seconds || 10}s poll / ${config.stable_seconds || 15}s stable`;
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

function renderAutomationProfiles(profiles, activeProfile) {
  const existingValues = Array.from(automationProfile.options).map((option) => option.value);
  const nextValues = profiles.map((profile) => profile.key);
  if (existingValues.join("|") === nextValues.join("|")) {
    return;
  }

  automationProfile.replaceChildren();
  for (const profile of profiles) {
    const option = document.createElement("option");
    option.value = profile.key;
    option.textContent = profile.label;
    option.selected = profile.key === activeProfile;
    automationProfile.append(option);
  }
}

function renderPipeline(pipeline) {
  renderPipelineCard(pipelineWatchCount, pipelineWatchSize, pipeline.watch);
  renderPipelineCard(pipelineOutputCount, pipelineOutputSize, pipeline.output);
  renderPipelineCard(pipelineFailedCount, pipelineFailedSize, pipeline.failed);
  renderPipelineCard(pipelineArchiveCount, pipelineArchiveSize, pipeline.archive);

  if (typeof pipeline.seconds_until_next_scan === "number") {
    automationScanState.textContent = `Next scan in ${pipeline.seconds_until_next_scan}s`;
  } else if (pipeline.last_scan_at) {
    automationScanState.textContent = "Watcher idle";
  } else {
    automationScanState.textContent = "No scans yet";
  }
}

function renderPipelineCard(countElement, sizeElement, value = {}) {
  countElement.textContent = String(value.count || 0);
  sizeElement.textContent = formatBytes(value.bytes || 0);
}

function createAutomationJob(job) {
  const item = document.createElement("article");
  item.className = `automation-job automation-job-${job.status}`;

  const title = document.createElement("h3");
  title.textContent =
    job.status === "success"
      ? `${job.filename} -> ${job.output_filename}`
      : `${job.filename} failed`;

  const detail = document.createElement("p");
  const elapsed =
    typeof job.elapsed_seconds === "number" ? ` ${job.elapsed_seconds.toFixed(2)}s.` : "";
  detail.textContent =
    job.status === "failed" ? `${failureSummary(job)}${elapsed}` : `${job.message || "No details."}${elapsed}`;

  item.append(title, detail);
  if (job.diagnostic) {
    item.append(createFailureDetails(job.diagnostic));
  }
  return item;
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
  details.append(list);
  return details;
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
