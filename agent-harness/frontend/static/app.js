const agentStatus = document.getElementById("agentStatus");
const gameStatus = document.getElementById("gameStatus");
const decisionStatus = document.getElementById("decisionStatus");
const sessionDir = document.getElementById("sessionDir");
const iterationInfo = document.getElementById("iterationInfo");
const lastExit = document.getElementById("lastExit");
const warningValue = document.getElementById("warningValue");
const warningToggle = document.getElementById("warningToggle");
const errorValue = document.getElementById("errorValue");

const decisionValue = document.getElementById("decisionValue");
const actValue = document.getElementById("actValue");
const floorValue = document.getElementById("floorValue");
const characterValue = document.getElementById("characterValue");
const hpValue = document.getElementById("hpValue");
const goldValue = document.getElementById("goldValue");

const thinkingScrollToggle = document.getElementById("thinkingScrollToggle");
const thinkingPane = document.getElementById("thinkingPane");
const outputPane = document.getElementById("outputPane");
const commandPane = document.getElementById("commandPane");
const eventTimeline = document.getElementById("eventTimeline");
const statePane = document.getElementById("statePane");
const memoryRunId = document.getElementById("memoryRunId");
const memorySummaryPath = document.getElementById("memorySummaryPath");
const memorySummaryPane = document.getElementById("memorySummaryPane");
const skillsRoot = document.getElementById("skillsRoot");
const skillsCount = document.getElementById("skillsCount");
const skillsLoadedList = document.getElementById("skillsLoadedList");
const skillsActivityPane = document.getElementById("skillsActivityPane");
const memoryFetchCount = document.getElementById("memoryFetchCount");
const memoryFetchHint = document.getElementById("memoryFetchHint");
const memoryFetchCategories = document.getElementById("memoryFetchCategories");
const memoryFetchPane = document.getElementById("memoryFetchPane");

let lastEventId = 0;
let stateCache = null;
let statusCache = null;
let thinkingAutoScroll = true;
let showWarnings = true;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

function setPaneText(pre, text, { autoScroll = true } = {}) {
  const previousScrollTop = pre.scrollTop;
  pre.textContent = text;
  pre.scrollTop = autoScroll ? pre.scrollHeight : previousScrollTop;
}

function appendPane(pre, text, maxLines = 400, { autoScroll = true } = {}) {
  const previousScrollTop = pre.scrollTop;
  const next = (pre.textContent + text).split("\n");
  pre.textContent = next.slice(-maxLines).join("\n");
  pre.scrollTop = autoScroll ? pre.scrollHeight : previousScrollTop;
}

function appendCommandLine(text) {
  appendPane(commandPane, `${text}\n`, 300);
}

function formatClock(ts) {
  if (!ts) {
    return "--:--:--";
  }
  return new Date(ts * 1000).toLocaleTimeString();
}

function formatDisplayPath(path) {
  if (!path) {
    return "-";
  }
  const normalized = String(path).replaceAll("\\", "/");
  const marker = "STS2CLI/";
  const index = normalized.indexOf(marker);
  return index >= 0 ? normalized.slice(index) : normalized;
}

function appendTimelineItem({ time, label, text, tone = "neutral" }) {
  const item = document.createElement("article");
  item.className = `timeline-item ${tone}`;

  const meta = document.createElement("div");
  meta.className = "timeline-meta";

  const timeNode = document.createElement("span");
  timeNode.className = "timeline-time";
  timeNode.textContent = time;

  const badge = document.createElement("span");
  badge.className = `timeline-badge ${tone}`;
  badge.textContent = label;

  meta.appendChild(timeNode);
  meta.appendChild(badge);

  const body = document.createElement("div");
  body.className = "timeline-text";
  body.textContent = text;

  item.appendChild(meta);
  item.appendChild(body);
  eventTimeline.appendChild(item);

  while (eventTimeline.children.length > 220) {
    eventTimeline.removeChild(eventTimeline.firstChild);
  }

  eventTimeline.scrollTop = eventTimeline.scrollHeight;
}

function syncThinkingScrollToggle() {
  thinkingScrollToggle.textContent = thinkingAutoScroll ? "Pause Scroll" : "Resume Scroll";
  thinkingScrollToggle.classList.toggle("active", !thinkingAutoScroll);
}

function syncWarningToggle() {
  warningToggle.textContent = showWarnings ? "Hide Warnings" : "Show Warnings";
  warningToggle.classList.toggle("active", !showWarnings);
  document.body.classList.toggle("warnings-hidden", !showWarnings);
}

function renderSkills(status) {
  const skills = status.skills || {};
  const loaded = Array.isArray(skills.loaded) ? skills.loaded : [];
  const invocations = Array.isArray(skills.recent_invocations) ? skills.recent_invocations : [];
  skillsRoot.textContent = `root: ${formatDisplayPath(skills.root)}`;
  skillsCount.textContent = `loaded: ${loaded.length}`;

  skillsLoadedList.replaceChildren();
  for (const skill of loaded) {
    const chip = document.createElement("span");
    chip.className = "tag-chip";
    chip.textContent = skill.name || "(unnamed)";
    chip.title = skill.description || skill.path || "";
    skillsLoadedList.appendChild(chip);
  }
  if (loaded.length === 0) {
    const chip = document.createElement("span");
    chip.className = "tag-chip muted";
    chip.textContent = "No skills discovered";
    skillsLoadedList.appendChild(chip);
  }

  if (invocations.length === 0) {
    skillsActivityPane.textContent = "No skill reads detected yet.";
    return;
  }
  skillsActivityPane.textContent = invocations
    .map((item) => `[${formatClock(item.ts)}] ${item.skill_name} -> ${formatDisplayPath(item.path)}`)
    .join("\n");
}

function renderMemoryFetches(status) {
  const fetches = status.memory_fetches?.items || [];
  memoryFetchCount.textContent = `fetches: ${fetches.length}`;
  memoryFetchHint.textContent = fetches.some((item) => item.via_memory_skill)
    ? "memory skill: active"
    : "memory skill: idle";
  const categoryCounts = new Map();
  for (const item of fetches) {
    const category = item.category || "memory";
    categoryCounts.set(category, (categoryCounts.get(category) || 0) + 1);
  }
  memoryFetchCategories.replaceChildren();
  const sortedCategories = Array.from(categoryCounts.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  for (const [category, count] of sortedCategories) {
    const chip = document.createElement("span");
    chip.className = "tag-chip";
    chip.textContent = `${category}: ${count}`;
    memoryFetchCategories.appendChild(chip);
  }
  if (sortedCategories.length === 0) {
    const chip = document.createElement("span");
    chip.className = "tag-chip muted";
    chip.textContent = "No categories yet";
    memoryFetchCategories.appendChild(chip);
  }
  if (fetches.length === 0) {
    memoryFetchPane.textContent = "No memory fetched yet.";
    return;
  }
  const groups = new Map();
  for (const item of fetches) {
    const category = item.category || "memory";
    if (!groups.has(category)) {
      groups.set(category, []);
    }
    groups.get(category).push(item);
  }
  const sections = Array.from(groups.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([category, items]) => {
      const body = items
        .map((item) => {
          const source = item.source || "unknown";
          const where = item.path ? formatDisplayPath(item.path) : item.command || "-";
          const via = item.via_memory_skill ? " [via memory skill]" : "";
          const preview = item.preview?.trim() || "(no preview)";
          return `[${formatClock(item.ts)}] ${source}: ${item.label}${via}\n${where}\n${preview}`;
        })
        .join("\n\n");
      return `## ${category}\n${body}`;
    });
  memoryFetchPane.textContent = sections.join("\n\n");
}

function updateSummary(status) {
  statusCache = status;
  agentStatus.textContent = status.status;
  sessionDir.textContent = `session: ${formatDisplayPath(status.session_dir)}`;
  iterationInfo.textContent = `iteration: ${status.current_iteration || status.iteration || "-"}`;
  lastExit.textContent = `last exit: ${status.last_exit_code ?? "-"}`;
  warningValue.textContent = showWarnings ? status.last_warning || "-" : "Hidden";
  errorValue.textContent = status.last_error || "-";

  setPaneText(thinkingPane, status.live?.thinking || "", { autoScroll: thinkingAutoScroll });
  setPaneText(outputPane, status.live?.output || "");
  if (!commandPane.textContent.trim() && (status.live?.recent_commands || []).length > 0) {
    commandPane.textContent = (status.live?.recent_commands || []).join("\n");
  }
  const memorySummary = status.memory_summary || null;
  const memoryInfo = status.memory || null;
  memoryRunId.textContent = `run: ${memorySummary?.run_id || memoryInfo?.run_id || "-"}`;
  memorySummaryPath.textContent = `summary: ${formatDisplayPath(memorySummary?.path)}`;
  memorySummaryPane.textContent = memorySummary?.content?.trim() || "No run summary yet.";
  renderSkills(status);
  renderMemoryFetches(status);
  renderButtonState();
}

function updateState(statePayload) {
  stateCache = statePayload.state;
  const summary = statePayload.summary || {};
  gameStatus.textContent = statePayload.ok ? "game: connected" : "game: disconnected";
  decisionStatus.textContent = `decision: ${summary.decision || "-"}`;
  decisionValue.textContent = summary.decision || "-";
  actValue.textContent = summary.act ?? "-";
  floorValue.textContent = summary.floor ?? "-";
  characterValue.textContent = summary.character || "-";
  hpValue.textContent =
    summary.hp != null && summary.max_hp != null ? `${summary.hp} / ${summary.max_hp}` : "-";
  goldValue.textContent = summary.gold ?? "-";
  statePane.textContent = JSON.stringify(statePayload.state, null, 2);
  renderButtonState();
}

function handleEvents(events) {
  for (const event of events) {
    lastEventId = Math.max(lastEventId, event.id);
    const timeLabel = new Date(event.ts * 1000).toLocaleTimeString();

    if (event.kind === "thinking_delta") {
      appendPane(thinkingPane, event.text, 400, { autoScroll: thinkingAutoScroll });
      continue;
    }
    if (event.kind === "assistant_text_delta") {
      outputPane.textContent += event.text;
      outputPane.scrollTop = outputPane.scrollHeight;
      continue;
    }
    if (event.kind === "assistant_done") {
      if (!outputPane.textContent.endsWith("\n")) {
        outputPane.textContent += "\n";
      }
      outputPane.scrollTop = outputPane.scrollHeight;
      continue;
    }
    if (event.kind === "sts2_command") {
      appendCommandLine(`[${timeLabel}] ${event.text}`);
      appendTimelineItem({
        time: timeLabel,
        label: "STS2",
        text: event.text,
        tone: "command",
      });
      continue;
    }
    if (event.kind === "tool_start" || event.kind === "tool_end" || event.kind === "tool_error") {
      appendTimelineItem({
        time: timeLabel,
        label: "TOOL",
        text: event.text,
        tone: event.kind === "tool_error" ? "error" : "tool",
      });
      continue;
    }
    appendTimelineItem(formatSystemEvent(timeLabel, event));
  }
}

function formatSystemEvent(timeLabel, event) {
  switch (event.kind) {
    case "state_transition":
      return { time: timeLabel, label: "STATE", text: event.text, tone: "state" };
    case "hp_change":
      return { time: timeLabel, label: "HP", text: event.text, tone: "hp" };
    case "floor_change":
      return { time: timeLabel, label: "FLOOR", text: event.text, tone: "floor" };
    case "act_change":
      return { time: timeLabel, label: "ACT", text: event.text, tone: "state" };
    case "gold_change":
      return { time: timeLabel, label: "GOLD", text: event.text, tone: "gold" };
    case "runner":
      return { time: timeLabel, label: "RUNNER", text: event.text, tone: "runner" };
    case "skill":
      return { time: timeLabel, label: "SKILL", text: event.text, tone: "skill" };
    case "memory_fetch":
      return { time: timeLabel, label: "MEMORY", text: event.text, tone: "memory" };
    case "error":
    case "manual_error":
    case "state_error":
      return { time: timeLabel, label: "ERROR", text: event.text, tone: "error" };
    case "log":
      return { time: timeLabel, label: "WARN", text: event.text, tone: "warn" };
    case "state":
      return { time: timeLabel, label: "SUMMARY", text: event.text, tone: "neutral" };
    default:
      return { time: timeLabel, label: event.kind, text: event.text, tone: "neutral" };
  }
}

function renderButtonState() {
  const status = statusCache?.status || "idle";
  const gameConnected = gameStatus.textContent === "game: connected";
  const running = status.startsWith("running_") || status === "pausing" || status === "stopping";
  const paused = status === "paused";
  const runningSingle = status === "running_single";
  const runningFullAuto = status === "running_full_auto";

  document.getElementById("stepBtn").disabled = !gameConnected || running || paused;
  document.getElementById("fullAutoBtn").disabled = !gameConnected || running || paused;
  document.getElementById("pauseBtn").disabled = !running || runningSingle;
  document.getElementById("resumeBtn").disabled = !paused;
  document.getElementById("stopBtn").disabled = !(running || paused || status === "pausing");
  document.getElementById("refreshBtn").disabled = false;

  if (runningFullAuto) {
    document.getElementById("fullAutoBtn").classList.add("active");
  } else {
    document.getElementById("fullAutoBtn").classList.remove("active");
  }
}

async function refreshStatus() {
  try {
    const status = await api("/api/status");
    updateSummary(status);
  } catch (error) {
    warningValue.textContent = String(error);
  }
}

async function refreshState() {
  try {
    const statePayload = await api("/api/state");
    updateState(statePayload);
  } catch (error) {
    gameStatus.textContent = "game: disconnected";
    statePane.textContent = String(error);
  }
}

async function pollEvents() {
  try {
    const payload = await api(`/api/events?after=${lastEventId}`);
    handleEvents(payload.events || []);
  } catch (error) {
    appendTimelineItem({
      time: new Date().toLocaleTimeString(),
      label: "POLL",
      text: String(error),
      tone: "error",
    });
  }
}

async function startMode(mode) {
  try {
    await api("/api/agent/start", {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
    await refreshStatus();
  } catch (error) {
    appendTimelineItem({
      time: new Date().toLocaleTimeString(),
      label: "START",
      text: String(error),
      tone: "error",
    });
  }
}

async function simplePost(path) {
  try {
    await api(path, { method: "POST", body: "{}" });
    await refreshStatus();
  } catch (error) {
    appendTimelineItem({
      time: new Date().toLocaleTimeString(),
      label: "ACTION",
      text: String(error),
      tone: "error",
    });
  }
}

document.getElementById("stepBtn").addEventListener("click", () => startMode("single"));
document.getElementById("fullAutoBtn").addEventListener("click", () => startMode("full_auto"));
document.getElementById("pauseBtn").addEventListener("click", () => simplePost("/api/agent/pause"));
document.getElementById("resumeBtn").addEventListener("click", () => simplePost("/api/agent/resume"));
document.getElementById("stopBtn").addEventListener("click", () => simplePost("/api/agent/stop"));
thinkingScrollToggle.addEventListener("click", () => {
  thinkingAutoScroll = !thinkingAutoScroll;
  if (thinkingAutoScroll) {
    thinkingPane.scrollTop = thinkingPane.scrollHeight;
  }
  syncThinkingScrollToggle();
});
warningToggle.addEventListener("click", () => {
  showWarnings = !showWarnings;
  syncWarningToggle();
  if (statusCache) {
    updateSummary(statusCache);
  }
});
document.getElementById("refreshBtn").addEventListener("click", async () => {
  await refreshStatus();
  await refreshState();
});

async function init() {
  syncThinkingScrollToggle();
  syncWarningToggle();
  await refreshStatus();
  await refreshState();
  setInterval(refreshStatus, 1000);
  setInterval(refreshState, 2000);
  setInterval(pollEvents, 700);
  renderButtonState();
}

init();
