const form = document.querySelector("#optimizer-form");
const fileInput = document.querySelector("#files");
const button = document.querySelector("#optimize-button");
const statusTitle = document.querySelector("#status-title");
const statusDetail = document.querySelector("#status-detail");
const statusPill = document.querySelector("#status-pill");
const progressMeter = document.querySelector("#progress-meter");
const logWindow = document.querySelector("#processing-log");
const logCount = document.querySelector("#log-count");
const resultsPanel = document.querySelector("#results-panel");
const resultsList = document.querySelector("#results-list");
const downloadAll = document.querySelector("#download-all");
const fileSummary = document.querySelector("#file-summary");
const themeToggle = document.querySelector("#theme-toggle");

let logEntries = 0;
let queueTotal = 0;
let queueCompleted = 0;

initializeTheme();
updateFileSummary();

themeToggle.addEventListener("change", () => {
  setTheme(themeToggle.checked ? "dark" : "light");
});

fileInput.addEventListener("change", updateFileSummary);

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const files = Array.from(fileInput.files || []);
  if (files.length === 0) {
    setStatus("No files selected", "Select one or more EPUB files.");
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
    appendLog("Error", message, "error");
  } finally {
    setBusy(false);
  }
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
    appendLog(event.filename, "Started optimization.");
    return;
  }

  if (event.type === "log") {
    appendLog(event.filename, event.message);
    return;
  }

  if (event.type === "file_complete") {
    queueCompleted += 1;
    updateProgress();
    setStatus("Optimizing", `Finished ${event.filename}.`, "Active");
    appendLog(event.filename, `Completed in ${event.elapsed_seconds.toFixed(2)} seconds.`);
    appendResult(event);
    return;
  }

  if (event.type === "file_error") {
    queueCompleted += 1;
    updateProgress();
    setStatus("Processing error", event.filename, "Error");
    appendLog(event.filename, event.message, "error");
    return;
  }

  if (event.type === "error") {
    setStatus("Processing error", event.message, "Error");
    appendLog("Error", event.message, "error");
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

function appendLog(filename, message, level = "info") {
  const item = document.createElement("li");
  item.className = `log-${level}`;

  const label = document.createElement("span");
  label.className = "log-label";
  label.textContent = filename;

  const text = document.createElement("span");
  text.textContent = message;

  item.append(label, text);
  logWindow.append(item);
  logEntries += 1;
  logCount.textContent = `${logEntries} ${logEntries === 1 ? "entry" : "entries"}`;
  logWindow.scrollTop = logWindow.scrollHeight;
}

function appendResult(event) {
  resultsPanel.hidden = false;

  const item = document.createElement("article");
  item.className = "result-item";

  const header = document.createElement("div");
  header.className = "result-header";

  const title = document.createElement("h3");
  title.textContent = event.output_filename;

  const download = document.createElement("a");
  download.className = "button";
  download.href = event.download_url;
  download.textContent = "Download EPUB";

  header.append(title, download);
  item.append(header);

  const stats = document.createElement("dl");
  stats.className = "stats";
  addStat(stats, "Input", event.filename);
  addStat(stats, "EPUB version", event.epub_version || "Unknown");
  addStat(stats, "Package", event.package_path);
  addStat(stats, "Documents", event.content_documents_processed);
  addStat(stats, "Stylesheets", event.stylesheets_replaced);
  addStat(stats, "Images", event.images_preserved);
  addStat(stats, "Time", `${event.elapsed_seconds.toFixed(2)} seconds`);
  item.append(stats);

  if (event.warnings && event.warnings.length > 0) {
    const warnings = document.createElement("ul");
    warnings.className = "log warnings";
    for (const warning of event.warnings) {
      const warningItem = document.createElement("li");
      warningItem.textContent = warning;
      warnings.append(warningItem);
    }
    item.append(warnings);
  }

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
  logEntries = 0;
  logWindow.replaceChildren();
  resultsList.replaceChildren();
  logCount.textContent = "0 entries";
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
  button.textContent = isBusy ? "Optimizing..." : "Optimize EPUB";
}

function updateProgress() {
  const percent = queueTotal === 0 ? 0 : Math.min(100, (queueCompleted / queueTotal) * 100);
  progressMeter.style.width = `${percent}%`;
}

function updateFileSummary() {
  const files = Array.from(fileInput.files || []);
  if (files.length === 0) {
    fileSummary.textContent = "No files selected";
    return;
  }

  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  fileSummary.textContent = `${files.length} file${files.length === 1 ? "" : "s"} selected, ${formatBytes(totalBytes)} total`;
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
