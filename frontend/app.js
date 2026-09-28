const DEMO_USERS = [
  { id: "1001", name: "Ravi" },
  { id: "1002", name: "Sita" },
];

const els = {
  form: document.getElementById("chat-form"),
  input: document.getElementById("chat-input"),
  send: document.getElementById("send-btn"),
  reset: document.getElementById("reset-btn"),
  userSelect: document.getElementById("user-select"),
  fieldSelect: document.getElementById("field-select"),
  memoryScope: document.getElementById("memory-scope"),
  profileFarmer: document.getElementById("profile-farmer"),
  profileField: document.getElementById("profile-field"),
  profileCrop: document.getElementById("profile-crop"),
  profileBank: document.getElementById("profile-bank"),
  emptySub: document.getElementById("empty-sub"),
  timelineHint: document.getElementById("timeline-hint"),
  messages: document.getElementById("messages"),
  empty: document.getElementById("empty-state"),
  memoryList: document.getElementById("memory-list"),
  memoryCount: document.getElementById("memory-count"),
  learningPanel: document.getElementById("learning-panel"),
  learningList: document.getElementById("learning-list"),
  error: document.getElementById("error-banner"),
  errorText: document.getElementById("error-text"),
  errorDismiss: document.getElementById("error-dismiss"),
  timeline: document.getElementById("timeline"),
  statusHindsight: document.getElementById("status-hindsight"),
  statusLlm: document.getElementById("status-llm"),
  actRecalled: document.getElementById("act-recalled"),
  actRetained: document.getElementById("act-retained"),
  actHistory: document.getElementById("act-history"),
  actDup: document.getElementById("act-dup"),
  whyCard: document.getElementById("why-card"),
  whyList: document.getElementById("why-list"),
};

let busy = false;
let latestRetainedDate = null;
let currentUser = DEMO_USERS[0];
let currentField = null;
let availableFields = [];

function userHeaders(extra) {
  return Object.assign({ "X-User-ID": currentUser.id }, extra || {});
}

function updateScope() {
  const fieldName = currentField ? currentField.name : "—";
  els.memoryScope.textContent = `Memory scope: ${currentUser.name} • ${fieldName}`;
  els.profileFarmer.textContent = currentUser.name;
  els.profileField.textContent = currentField ? currentField.name : "—";
  els.profileCrop.textContent = (currentField && currentField.crop) || "—";
  els.profileBank.textContent = `kisan-user-${currentUser.id}`;
  els.timelineHint.textContent = `Live from Hindsight · ${fieldName}`;
  els.emptySub.textContent =
    `Ask above — KisanMemory answers from ${currentUser.name}'s own recorded field history, not generic advice.`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function stripWhen(text) {
  return String(text).replace(/\s*\|\s*When:\s*\d{4}-\d{2}-\d{2}/g, "");
}

function formatDate(isoDate) {
  if (!isoDate) return "";
  const parsed = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return parsed.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
}

function setPill(element, online, label) {
  element.className = `pill ${online ? "pill-ok" : "pill-down"}`;
  element.textContent = online ? `🟢 ${label} connected` : `🔴 ${label} not connected`;
}

function showError(message) {
  els.errorText.textContent = message;
  els.error.hidden = false;
}

function clearError() {
  els.error.hidden = true;
  els.errorText.textContent = "";
}

function appendMessage(kind, kindLabel, metaLabel, body) {
  els.empty.hidden = true;
  const wrapper = document.createElement("div");
  wrapper.className = `msg msg-${kind}`;
  wrapper.innerHTML =
    `<div class="msg-label"><span class="label-kind">${escapeHtml(kindLabel)}</span>` +
    `<span>${escapeHtml(metaLabel)}</span></div>` +
    `<div class="msg-body">${escapeHtml(body)}</div>`;
  els.messages.appendChild(wrapper);
  wrapper.scrollIntoView({ block: "nearest", behavior: "smooth" });
  return wrapper;
}

function renderActivity(data) {
  els.actRecalled.textContent = String(data.memory_count);
  els.actRetained.textContent = String(data.new_memories_stored);
  const usedHistory = data.memory_count > 0;
  els.actHistory.textContent = usedHistory ? "YES" : "NO";
  els.actHistory.classList.toggle("activity-yes", usedHistory);
  els.actHistory.classList.toggle("activity-no", !usedHistory);

  const skipped = data.duplicates_skipped || 0;
  if (skipped > 0) {
    els.actDup.textContent =
      `↻ ${skipped} duplicate experience ignored — already remembered, no repeat memory created.`;
    els.actDup.hidden = false;
  } else {
    els.actDup.hidden = true;
    els.actDup.textContent = "";
  }
}

function classifyMemory(text) {
  const failSignal = /\bfail|failed|did not|didn't|no effect|not help|unsuccess|ineffective/i;
  const successSignal = /\breduc|improv|recover|lessened|symptoms reduced|helped|worked/i;

  if (/\brain|rainfall|waterlog|water-log/i.test(text)) {
    return "Previous heavy-rain / waterlogging event found";
  }
  if (/\bfung|disease|pathogen|blight/i.test(text)) {
    return "Previous fungal episode found";
  }
  const treatment = text.match(/treatment\s+[a-z0-9]+/i);
  if (treatment) {
    const name = treatment[0].replace(/\b\w/g, (char) => char.toUpperCase());
    if (failSignal.test(text)) return `${name} failure found`;
    if (successSignal.test(text)) return `${name} success found`;
    return `${name} outcome found`;
  }
  if (/\bplant|sow|seed|transplant/i.test(text)) {
    return "Planting / crop history found";
  }
  if (failSignal.test(text)) return "Unsuccessful field treatment found";
  if (successSignal.test(text)) return "Field recovery outcome found";
  const words = text.split(/\s+/).slice(0, 8).join(" ");
  return `Field record found: ${words}`;
}

function renderWhy(memories) {
  if (!memories.length) {
    els.whyCard.hidden = true;
    els.whyList.innerHTML = "";
    return;
  }

  const buckets = new Map();
  memories.forEach((memory) => {
    const label = classifyMemory(stripWhen(memory.text || ""));
    const entry = buckets.get(label) || { label, count: 0, dates: [] };
    entry.count += 1;
    if (memory.date && !entry.dates.includes(memory.date)) entry.dates.push(memory.date);
    buckets.set(label, entry);
  });

  const sorted = Array.from(buckets.values()).sort((a, b) => b.count - a.count);
  els.whyList.innerHTML = sorted
    .map((entry) => {
      const when = entry.dates.length
        ? `<span class="why-when">${escapeHtml(entry.dates.map(formatDate).join(" · "))}${
            entry.count > 1 ? ` · ${entry.count} memories` : ""
          }</span>`
        : entry.count > 1
          ? `<span class="why-when">${entry.count} memories</span>`
          : "";
      return `<li>${escapeHtml(entry.label)}${when}</li>`;
    })
    .join("");
  els.whyCard.hidden = false;
}

function renderMemories(memories) {
  els.memoryCount.textContent = String(memories.length);
  if (!memories.length) {
    els.memoryList.innerHTML =
      '<li class="memory-empty">No relevant past memories were found for this question — the answer is general guidance, not field history.</li>';
    return;
  }

  const groups = [];
  const indexByKey = new Map();
  memories.forEach((memory) => {
    const key = `${memory.date || ""}|${memory.type || ""}`;
    if (indexByKey.has(key)) {
      groups[indexByKey.get(key)].count += 1;
      return;
    }
    indexByKey.set(key, groups.length);
    groups.push({ memory, count: 1 });
  });

  els.memoryList.innerHTML = groups
    .map(({ memory, count }) => {
      const chips = [];
      if (memory.date) chips.push(`<span class="chip chip-date">${escapeHtml(formatDate(memory.date))}</span>`);
      chips.push(`<span class="chip chip-type">${escapeHtml(memory.type)}</span>`);
      if (count > 1) chips.push(`<span class="chip">${count} similar records</span>`);
      return (
        `<li><div class="memory-meta">${chips.join("")}</div>` +
        `<div class="memory-text">${escapeHtml(stripWhen(memory.text))}</div></li>`
      );
    })
    .join("");
}

function renderLearning(retained, skipped) {
  const hasRetained = retained.length > 0;
  const hasSkipped = skipped.length > 0;
  if (!hasRetained && !hasSkipped) return;

  const title = document.getElementById("learning-title");
  const items = [];

  retained.forEach((item) => {
    items.push(
      `<li><div>${escapeHtml(stripWhen(item.text))}</div>` +
        `<div class="learning-meta">` +
        `<span class="chip">${escapeHtml(formatDate(item.date))}</span>` +
        `<span class="chip">${escapeHtml(item.field)}</span>` +
        `<span class="chip">stored in Hindsight</span>` +
        `</div></li>`
    );
  });

  skipped.forEach((text) => {
    items.push(
      `<li class="learning-dup"><div>${escapeHtml(stripWhen(text))}</div>` +
        `<div class="learning-meta">` +
        `<span class="chip">already in Hindsight</span>` +
        `<span class="chip">no duplicate created</span>` +
        `</div></li>`
    );
  });

  els.learningList.innerHTML = items.join("");
  title.textContent = hasRetained
    ? "🌱 NEW MEMORY CREATED — field experience remembered"
    : "🌱 ALREADY REMEMBERED — duplicate ignored, nothing stored twice";
  els.learningPanel.classList.toggle("learning-panel-dup", !hasRetained && hasSkipped);
  els.learningPanel.hidden = false;
  if (hasRetained) latestRetainedDate = retained[retained.length - 1].date;
}

async function loadTimeline() {
  if (!currentField) {
    els.timeline.innerHTML = '<li class="timeline-empty">Select a field to see its timeline.</li>';
    return;
  }
  try {
    const response = await fetch(`/timeline?field_id=${currentField.id}`, {
      headers: userHeaders(),
    });
    if (!response.ok) throw new Error("timeline unavailable");
    const data = await response.json();
    const events = data.events || [];
    if (!events.length) {
      els.timeline.innerHTML = '<li class="timeline-empty">No field memories stored yet.</li>';
      return;
    }
    els.timeline.innerHTML = events
      .map((event) => {
        const isLatest = event.date && event.date === latestRetainedDate;
        const dateText = event.date ? formatDate(event.date) : "Date not recorded";
        const meta = [
          `<span class="chip chip-type">${escapeHtml(event.type)}</span>`,
          event.count > 1 ? `<span class="chip">${event.count} memories</span>` : "",
        ].join("");
        return (
          `<li class="${isLatest ? "timeline-new" : event.date ? "" : "timeline-undated"}">` +
          `<div class="timeline-date">${escapeHtml(dateText)}${isLatest ? " · new" : ""}</div>` +
          `<div class="timeline-text">${escapeHtml(stripWhen(event.text))}</div>` +
          `<div class="timeline-meta">${meta}</div></li>`
        );
      })
      .join("");
  } catch (error) {
    els.timeline.innerHTML = '<li class="timeline-empty">Timeline unavailable right now.</li>';
  }
}

async function checkHealth() {
  try {
    const response = await fetch("/health");
    const data = await response.json();
    setPill(els.statusHindsight, Boolean(data.hindsight), "Hindsight");
    setPill(els.statusLlm, Boolean(data.llm), "AI");
  } catch (error) {
    setPill(els.statusHindsight, false, "Hindsight");
    setPill(els.statusLlm, false, "AI");
  }
}

async function loadFields() {
  try {
    const response = await fetch("/fields", { headers: userHeaders() });
    if (!response.ok) throw new Error("fields unavailable");
    availableFields = await response.json();
  } catch (error) {
    availableFields = [];
  }

  if (availableFields.length) {
    els.fieldSelect.innerHTML = availableFields
      .map((field) => `<option value="${field.id}">${escapeHtml(field.name)}</option>`)
      .join("");
    currentField = availableFields[0];
    els.fieldSelect.value = String(currentField.id);
  } else {
    els.fieldSelect.innerHTML = '<option value="">No fields available</option>';
    currentField = null;
  }
  updateScope();
  await loadTimeline();
}

async function askQuestion(message) {
  if (busy || !message) return;
  if (!currentField) {
    showError("No field selected for this farmer yet.");
    return;
  }
  busy = true;
  els.send.disabled = true;
  els.input.disabled = true;
  clearError();

  appendMessage("farmer", "CURRENT FARMER MESSAGE", `${currentUser.name} · ${currentField.name}`, message);
  const thinking = appendMessage(
    "ai",
    "AI RESPONSE",
    "thinking…",
    "Recalling your field history from Hindsight…"
  );
  thinking.classList.add("msg-thinking");

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: userHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ field_id: currentField.id, message }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || "Something went wrong. Please try again.");
    }

    thinking.remove();
    appendMessage("ai", "AI RESPONSE", "personalized from field memory", data.response);
    renderMemories(data.memories_used || []);
    renderActivity(data);
    renderWhy(data.memories_used || []);
    renderLearning(data.retained_memories || [], data.skipped_experiences || []);
    if ((data.retained_memories || []).length) {
      await loadTimeline();
    }
  } catch (error) {
    thinking.remove();
    showError(error.message || "Something went wrong. Please try again.");
  } finally {
    busy = false;
    els.send.disabled = false;
    els.input.disabled = false;
    els.input.focus();
  }
}

function resetDemo() {
  if (busy) return;
  els.messages.innerHTML = "";
  els.empty.hidden = false;
  els.memoryCount.textContent = "0";
  els.memoryList.innerHTML =
    '<li class="memory-empty">No memories used yet. Ask a question to recall field history.</li>';
  els.learningPanel.hidden = true;
  els.learningList.innerHTML = "";
  els.whyCard.hidden = true;
  els.whyList.innerHTML = "";
  els.actRecalled.textContent = "0";
  els.actRetained.textContent = "0";
  els.actHistory.textContent = "—";
  els.actHistory.classList.remove("activity-yes", "activity-no");
  els.actDup.hidden = true;
  els.actDup.textContent = "";
  clearError();
  latestRetainedDate = null;
  els.input.value = "";
  loadTimeline();
  checkHealth();
  els.input.focus();
}

els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = els.input.value.trim();
  if (!message) return;
  els.input.value = "";
  askQuestion(message);
});

document.querySelectorAll(".demo-btn").forEach((button) => {
  button.addEventListener("click", () => askQuestion(button.dataset.message));
});

els.reset.addEventListener("click", resetDemo);
els.errorDismiss.addEventListener("click", clearError);

els.userSelect.addEventListener("change", () => {
  currentUser = DEMO_USERS.find((user) => user.id === els.userSelect.value) || DEMO_USERS[0];
  resetDemo();
  loadFields();
});

els.fieldSelect.addEventListener("change", () => {
  currentField =
    availableFields.find((field) => String(field.id) === els.fieldSelect.value) || null;
  updateScope();
  resetDemo();
});

checkHealth();
loadFields();
setInterval(checkHealth, 30000);
els.input.focus();
