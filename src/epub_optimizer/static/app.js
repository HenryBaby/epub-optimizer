const form = document.querySelector("#optimizer-form");
const fileInput = document.querySelector("#files");
const button = document.querySelector("#optimize-button");
const statusTitle = document.querySelector("#status-title");
const statusDetail = document.querySelector("#status-detail");
const logWindow = document.querySelector("#processing-log");
const resultsPanel = document.querySelector("#results-panel");
const resultsList = document.querySelector("#results-list");

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const files = Array.from(fileInput.files || []);
  if (files.length === 0) {
    setStatus("No files selected", "Select one or more EPUB files.");
    return;
  }

  resetRun();
  setBusy(true);
  setStatus("Uploading", `${files.length} file${files.length === 1 ? "" : "s"} queued.`);

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
    setStatus("Processing failed", message);
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
    setStatus("Optimizing", `${event.filename} (${event.index} of ${event.total})`);
    appendLog(event.filename, "Started optimization.");
    return;
  }

  if (event.type === "log") {
    appendLog(event.filename, event.message);
    return;
  }

  if (event.type === "file_complete") {
    setStatus("Optimizing", `Finished ${event.filename}.`);
    appendLog(event.filename, `Completed in ${event.elapsed_seconds.toFixed(2)} seconds.`);
    appendResult(event);
    return;
  }

  if (event.type === "file_error") {
    setStatus("Processing error", event.filename);
    appendLog(event.filename, event.message, "error");
    return;
  }

  if (event.type === "error") {
    setStatus("Processing error", event.message);
    appendLog("Error", event.message, "error");
    return;
  }

  if (event.type === "complete") {
    setStatus(
      "Optimization complete",
      `${event.successful} complete, ${event.failed} failed.`,
    );
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
  logWindow.replaceChildren();
  resultsList.replaceChildren();
  resultsPanel.hidden = true;
}

function setStatus(title, detail) {
  statusTitle.textContent = title;
  statusDetail.textContent = detail;
}

function setBusy(isBusy) {
  button.disabled = isBusy;
  fileInput.disabled = isBusy;
  button.textContent = isBusy ? "Optimizing..." : "Optimize EPUB";
}
