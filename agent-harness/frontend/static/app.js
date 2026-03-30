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
const memorySearchCharacter = document.getElementById("memorySearchCharacter");
const memorySearchResult = document.getElementById("memorySearchResult");
const memorySearchBoss = document.getElementById("memorySearchBoss");
const memorySearchDeathEnemy = document.getElementById("memorySearchDeathEnemy");
const memorySearchCard = document.getElementById("memorySearchCard");
const memorySearchRelic = document.getElementById("memorySearchRelic");
const memorySearchFloorMin = document.getElementById("memorySearchFloorMin");
const memorySearchFloorMax = document.getElementById("memorySearchFloorMax");
const memorySearchLimit = document.getElementById("memorySearchLimit");
const memorySearchBtn = document.getElementById("memorySearchBtn");
const memorySearchResults = document.getElementById("memorySearchResults");
const memoryRunIdInput = document.getElementById("memoryRunIdInput");
const memoryRunLoadBtn = document.getElementById("memoryRunLoadBtn");
const memoryRunDetailPane = document.getElementById("memoryRunDetailPane");
const memoryStatsCharacter = document.getElementById("memoryStatsCharacter");
const memoryStatsBtn = document.getElementById("memoryStatsBtn");
const memoryStatsPane = document.getElementById("memoryStatsPane");
const memoryV3Root = document.getElementById("memoryV3Root");
const memoryV3Counts = document.getElementById("memoryV3Counts");
const memoryV3Invalid = document.getElementById("memoryV3Invalid");
const memoryV3SearchInput = document.getElementById("memoryV3SearchInput");
const memoryV3SearchBtn = document.getElementById("memoryV3SearchBtn");
const memoryV3RefreshBtn = document.getElementById("memoryV3RefreshBtn");
const memoryV3SearchResults = document.getElementById("memoryV3SearchResults");
const memoryV3PathInput = document.getElementById("memoryV3PathInput");
const memoryV3OpenBtn = document.getElementById("memoryV3OpenBtn");
const memoryV3FilePane = document.getElementById("memoryV3FilePane");

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

function formatJsonBlock(value) {
  return JSON.stringify(value, null, 2);
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

function buildMemorySearchQuery() {
  const params = new URLSearchParams();
  const mappings = [
    ["character", memorySearchCharacter.value],
    ["result", memorySearchResult.value],
    ["boss", memorySearchBoss.value],
    ["death_enemy", memorySearchDeathEnemy.value],
    ["card_name", memorySearchCard.value],
    ["relic_name", memorySearchRelic.value],
    ["floor_min", memorySearchFloorMin.value],
    ["floor_max", memorySearchFloorMax.value],
    ["limit", memorySearchLimit.value],
  ];
  for (const [key, value] of mappings) {
    if (String(value || "").trim()) {
      params.set(key, String(value).trim());
    }
  }
  return params.toString();
}

function renderMemorySearchResults(payload) {
  const runs = payload.runs || [];
  memorySearchResults.replaceChildren();
  if (runs.length === 0) {
    const empty = document.createElement("div");
    empty.className = "archive-empty";
    empty.textContent = "No archived runs matched.";
    memorySearchResults.appendChild(empty);
    return;
  }
  for (const run of runs) {
    const item = document.createElement("article");
    item.className = "archive-result";

    const header = document.createElement("div");
    header.className = "archive-result-header";

    const title = document.createElement("div");
    title.className = "archive-result-title";
    title.textContent = `${run.run_id} | ${run.character || "-"} A${run.ascension ?? "-"}`;

    const action = document.createElement("button");
    action.type = "button";
    action.className = "ghost archive-open-btn";
    action.textContent = "Load";
    action.dataset.runId = run.run_id;

    header.appendChild(title);
    header.appendChild(action);

    const meta = document.createElement("div");
    meta.className = "archive-result-meta";
    meta.textContent = `result=${run.result || "-"} floor=${run.final_floor ?? "-"} boss=${run.boss || "-"} ended=${run.ended_at || "-"}`;

    item.appendChild(header);
    item.appendChild(meta);
    memorySearchResults.appendChild(item);
  }
}

function formatTurnSummary(turn) {
  const commands = Array.isArray(turn.commands) ? turn.commands.map((item) => item.command).filter(Boolean) : [];
  return `- ${turn.turn_id}: ${turn.decision_before || "-"} -> ${turn.decision_after || "-"} | ${commands.join(", ") || "(no commands)"}`;
}

function renderMemoryRunDetail(payload) {
  const detail = payload.detail || {};
  const run = detail.run || {};
  const battles = Array.isArray(detail.battles) ? detail.battles : [];
  const rewards = Array.isArray(detail.rewards) ? detail.rewards : [];
  const turns = Array.isArray(detail.recent_turns) ? detail.recent_turns : [];
  const lines = [
    `Run: ${run.run_id || "-"}`,
    `Character: ${run.character || "-"} A${run.ascension ?? "-"}`,
    `Result: ${run.result || "-"} | Floor: ${run.final_floor ?? "-"} | Boss: ${run.boss || "-"}`,
    `Started: ${run.started_at || "-"}`,
    `Ended: ${run.ended_at || "-"}`,
  ];
  if (run.report_path) {
    lines.push(`Report: ${formatDisplayPath(run.report_path)}`);
  }
  lines.push("");
  lines.push("Recent Turns:");
  if (turns.length > 0) {
    lines.push(...turns.map(formatTurnSummary));
  } else {
    lines.push("- (none)");
  }
  lines.push("");
  lines.push("Battles:");
  if (battles.length > 0) {
    lines.push(...battles.map((battle) => `- ${battle.battle_id}: floor ${battle.floor ?? "-"} | ${battle.result || "-"} | ${(battle.enemy_names || []).join(", ") || "-"}`));
  } else {
    lines.push("- (none)");
  }
  lines.push("");
  lines.push("Rewards:");
  if (rewards.length > 0) {
    lines.push(...rewards.map((reward) => `- ${reward.reward_id}: floor ${reward.floor ?? "-"} | ${reward.source || "-"} | ${reward.chosen_command || "-"}`));
  } else {
    lines.push("- (none)");
  }
  lines.push("");
  lines.push("Derived:");
  lines.push(formatJsonBlock(detail.derived || {}));
  if (detail.report_content) {
    lines.push("");
    lines.push("Run Report:");
    lines.push(detail.report_content.trim());
  }
  memoryRunDetailPane.textContent = lines.join("\n");
}

function renderMemoryStats(payload) {
  memoryStatsPane.textContent = formatJsonBlock(payload.stats || {});
}

function renderMemoryV3Status(payload) {
  const workspace = payload.workspace || {};
  memoryV3Root.textContent = `root: ${formatDisplayPath(workspace.root)}`;
  memoryV3Counts.textContent = `files: ${workspace.file_count ?? 0}`;
  memoryV3Invalid.textContent = `invalid: ${workspace.invalid_file_count ?? 0}`;
}

function renderMemoryV3Search(payload) {
  const workspace = payload.workspace || {};
  const results = workspace.results || [];
  memoryV3SearchResults.replaceChildren();
  if (results.length === 0) {
    const empty = document.createElement("div");
    empty.className = "archive-empty";
    empty.textContent = "No Markdown files matched.";
    memoryV3SearchResults.appendChild(empty);
    return;
  }
  for (const item of results) {
    const article = document.createElement("article");
    article.className = "archive-result";

    const header = document.createElement("div");
    header.className = "archive-result-header";

    const title = document.createElement("div");
    title.className = "archive-result-title";
    title.textContent = item.path || "-";

    const action = document.createElement("button");
    action.type = "button";
    action.className = "ghost archive-open-btn";
    action.textContent = "Open";
    action.dataset.v3Path = item.path || "";

    header.appendChild(title);
    header.appendChild(action);

    const meta = document.createElement("div");
    meta.className = "archive-result-meta";
    meta.textContent = `size=${item.size_bytes ?? 0}B modified=${item.modified_ts || "-"}`;

    const preview = document.createElement("div");
    preview.className = "archive-result-meta";
    preview.textContent = item.preview || "(empty)";

    article.appendChild(header);
    article.appendChild(meta);
    article.appendChild(preview);
    memoryV3SearchResults.appendChild(article);
  }
}

function renderMemoryV3File(payload) {
  const file = payload.file || {};
  const lines = [
    `Path: ${file.path || "-"}`,
    `Size: ${file.info?.size_bytes ?? 0}B`,
    `Modified: ${file.info?.modified_ts || "-"}`,
    "",
    file.content || "",
  ];
  memoryV3FilePane.textContent = lines.join("\n");
}

async function searchMemoryArchive() {
  try {
    const query = buildMemorySearchQuery();
    const payload = await api(`/api/memory/search${query ? `?${query}` : ""}`);
    renderMemorySearchResults(payload);
  } catch (error) {
    memorySearchResults.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "archive-empty";
    empty.textContent = String(error);
    memorySearchResults.appendChild(empty);
  }
}

async function loadMemoryRunDetail(runId = memoryRunIdInput.value) {
  const value = String(runId || "").trim();
  if (!value) {
    memoryRunDetailPane.textContent = "Run ID is required.";
    return;
  }
  try {
    const payload = await api(`/api/memory/run?run_id=${encodeURIComponent(value)}`);
    memoryRunIdInput.value = value;
    renderMemoryRunDetail(payload);
  } catch (error) {
    memoryRunDetailPane.textContent = String(error);
  }
}

async function refreshMemoryStats() {
  try {
    const value = String(memoryStatsCharacter.value || "").trim();
    const query = value ? `?character=${encodeURIComponent(value)}` : "";
    const payload = await api(`/api/memory/stats${query}`);
    renderMemoryStats(payload);
  } catch (error) {
    memoryStatsPane.textContent = String(error);
  }
}

async function refreshMemoryV3Status() {
  try {
    const payload = await api("/api/memory/v3/status");
    renderMemoryV3Status(payload);
  } catch (error) {
    memoryV3Root.textContent = `root: ${String(error)}`;
  }
}

async function searchMemoryV3() {
  try {
    const value = String(memoryV3SearchInput.value || "").trim();
    const query = value ? `?q=${encodeURIComponent(value)}` : "";
    const payload = await api(`/api/memory/v3/search${query}`);
    renderMemoryV3Search(payload);
    renderMemoryV3Status({ workspace: payload.workspace });
  } catch (error) {
    memoryV3SearchResults.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "archive-empty";
    empty.textContent = String(error);
    memoryV3SearchResults.appendChild(empty);
  }
}

async function openMemoryV3File(path = memoryV3PathInput.value) {
  const value = String(path || "").trim();
  if (!value) {
    memoryV3FilePane.textContent = "Relative path is required.";
    return;
  }
  try {
    const payload = await api(`/api/memory/v3/file?path=${encodeURIComponent(value)}`);
    memoryV3PathInput.value = value;
    renderMemoryV3File(payload);
  } catch (error) {
    memoryV3FilePane.textContent = String(error);
  }
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
memorySearchBtn.addEventListener("click", () => searchMemoryArchive());
memoryRunLoadBtn.addEventListener("click", () => loadMemoryRunDetail());
memoryStatsBtn.addEventListener("click", () => refreshMemoryStats());
memoryV3RefreshBtn.addEventListener("click", () => refreshMemoryV3Status());
memoryV3SearchBtn.addEventListener("click", () => searchMemoryV3());
memoryV3OpenBtn.addEventListener("click", () => openMemoryV3File());
memorySearchResults.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const runId = target.dataset.runId;
  if (!runId) {
    return;
  }
  loadMemoryRunDetail(runId);
});
memoryV3SearchResults.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const path = target.dataset.v3Path;
  if (!path) {
    return;
  }
  openMemoryV3File(path);
});
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
  await refreshMemoryStats();
  await searchMemoryArchive();
  await refreshMemoryV3Status();
  await searchMemoryV3();
  setInterval(refreshStatus, 1000);
  setInterval(refreshState, 2000);
  setInterval(pollEvents, 700);
  renderButtonState();
}

init();
