const DEMO_USERS = [
  { id: "1001", name: "Ravi" },
  { id: "1002", name: "Sita" },
];

const els = {
  app: document.getElementById("app"),
  welcome: document.getElementById("welcome-screen"),
  welcomeActions: document.getElementById("welcome-actions"),
  signinForm: document.getElementById("signin-form"),
  signupForm: document.getElementById("signup-form"),
  authError: document.getElementById("auth-error"),
  goSignin: document.getElementById("go-signin"),
  goSignup: document.getElementById("go-signup"),
  goDemo: document.getElementById("go-demo"),
  signinEmail: document.getElementById("signin-email"),
  signinPassword: document.getElementById("signin-password"),
  signupName: document.getElementById("signup-name"),
  signupEmail: document.getElementById("signup-email"),
  signupPassword: document.getElementById("signup-password"),
  signupVillage: document.getElementById("signup-village"),
  signupState: document.getElementById("signup-state"),
  signupLanguage: document.getElementById("signup-language"),
  accountName: document.getElementById("account-name"),
  logoutBtn: document.getElementById("logout-btn"),
  form: document.getElementById("chat-form"),
  input: document.getElementById("chat-input"),
  send: document.getElementById("send-btn"),
  reset: document.getElementById("reset-btn"),
  userSelect: document.getElementById("user-select"),
  userSelectWrap: document.getElementById("user-select-wrap"),
  fieldSelect: document.getElementById("field-select"),
  langSelect: document.getElementById("lang-select"),
  newFieldBtn: document.getElementById("new-field-btn"),
  fieldForm: document.getElementById("field-form"),
  fieldName: document.getElementById("new-field-name"),
  fieldCrop: document.getElementById("new-field-crop"),
  fieldCancel: document.getElementById("field-form-cancel"),
  demoBadge: document.getElementById("demo-badge"),
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
  actUsed: document.getElementById("act-used"),
  actRetained: document.getElementById("act-retained"),
  actHistory: document.getElementById("act-history"),
  actDup: document.getElementById("act-dup"),
  memoryUsed: document.getElementById("memory-used"),
  whyCard: document.getElementById("why-card"),
  whyList: document.getElementById("why-list"),
  compareAnswer: document.getElementById("compare-answer"),
  compareMeta: document.getElementById("compare-meta"),
};

let busy = false;
let latestRetainedDate = null;
let mode = "welcome"; // "welcome" | "demo" | "signed-in"
let currentUser = null;
let currentField = null;
let availableFields = [];

function userHeaders(extra) {
  const headers = Object.assign({}, extra || {});
  if (mode === "demo" && currentUser) {
    headers["X-User-ID"] = currentUser.id;
  }
  return headers;
}

function updateScope() {
  const fieldName = currentField ? currentField.name : "—";
  const farmerName = currentUser ? currentUser.name : "—";
  els.memoryScope.textContent = `Memory scope: ${farmerName} • ${fieldName}`;
  els.profileFarmer.textContent = farmerName;
  els.profileField.textContent = currentField ? currentField.name : "—";
  els.profileCrop.textContent = (currentField && currentField.crop) || "—";
  els.profileBank.textContent = currentUser
    ? `private to ${currentUser.name}`
    : "—";
  els.timelineHint.textContent = currentField
    ? `Persistent history · ${farmerName} · ${fieldName}`
    : "Persistent history for this farmer and field";
  els.emptySub.textContent = currentUser
    ? `Ask above — KisanMemory answers from ${currentUser.name}'s own recorded field history, not generic advice.`
    : "Ask above — KisanMemory answers from this farmer's own recorded field history.";
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
  return String(text).replace(/\s*\|\s*[^|]+/g, "");
}

const FAIL_RE =
  /\b(did not|didn'?t|failed|ineffective|no effect|not help|not improv|not effective|no improvement|no benefit|without (?:improvement|success|benefit)|unsuccessful)\b/i;
const SUCCESS_RE = /\b(?:reduc|improv|recover|lessen|helped|worked|effective|success|better|resolved)/i;
const APPLIED_RE = /\b(?:applied|re-applied|tried|sprayed|treated|used)\b/i;
const INTENT_RE =
  /\b(?:to|in order to|aimed at|so as to)\s+(?:improv|reduc|help|recover|resolve|control|prevent)/i;
const TREATMENT_RE = /\btreatment\s+[a-z0-9]+\b/gi;
const MONTHS_JS = {
  january: 1, february: 2, march: 3, april: 4, may: 5, june: 6,
  july: 7, august: 8, september: 9, october: 10, november: 11, december: 12,
  jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6,
  jul: 7, aug: 8, sep: 9, sept: 9,
  oct: 10, nov: 11, dec: 12,
};
const OBJECT_WORDS = [
  "soil moisture", "leaf yellowing", "yellowing", "fungal symptoms", "disease symptoms",
  "waterlogging", "irrigation", "aphids", "pest damage", "yield",
];
const EVENT_ICONS = {
  planting: "🌱", weather: "🌧", irrigation: "💧", soil: "⚠",
  disease: "🍄", treatment: "🌿", outcome_ok: "✅", outcome_fail: "❌", other: "📌",
};

function titleCase(value) {
  return value.replace(/\b\w/g, (char) => char.toUpperCase());
}

function lowerFirst(value) {
  return value.charAt(0).toLowerCase() + value.slice(1);
}

function shortDate(isoDate) {
  if (!isoDate) return "";
  const parsed = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return parsed.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function explicitDates(text) {
  const found = [];
  let masked = text;
  const add = (start, end, year, month, day) => {
    if (month < 1 || month > 12 || day < 1 || day > 31) return false;
    if (found.some((item) => item.start === start)) return false;
    const iso = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const check = new Date(`${iso}T00:00:00`);
    if (Number.isNaN(check.getTime()) || check.getDate() !== day) return false;
    found.push({ start, end, iso });
    masked = masked.slice(0, start) + " ".repeat(end - start) + masked.slice(end);
    return true;
  };
  let match;

  const rangeIso = /\b(?:between|from)\s+(20\d{2}-\d{2}-\d{2})\s+(?:and|to|-)\s+(20\d{2}-\d{2}-\d{2})\b/gi;
  while ((match = rangeIso.exec(masked))) {
    const [year, month, day] = match[1].split("-").map(Number);
    add(match.index, match.index + match[0].length, year, month, day);
  }
  const rangeText =
    /\b(?:between|from)\s+([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s+(?:and|to|-)\s+([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b/gi;
  while ((match = rangeText.exec(masked))) {
    const month = MONTHS_JS[match[1].toLowerCase()];
    if (month) add(match.index, match.index + match[0].length, +match[5], month, +match[2]);
  }

  const isoRe = /\b(20\d{2})-(\d{2})-(\d{2})\b/g;
  while ((match = isoRe.exec(masked))) {
    add(match.index, match.index + match[0].length, +match[1], +match[2], +match[3]);
  }
  const monthFirst = /\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b/gi;
  while ((match = monthFirst.exec(masked))) {
    const month = MONTHS_JS[match[1].toLowerCase()];
    if (month) add(match.index, match.index + match[0].length, +match[3], month, +match[2]);
  }
  const dayFirst = /\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?,?\s+(20\d{2})\b/gi;
  while ((match = dayFirst.exec(masked))) {
    const month = MONTHS_JS[match[2].toLowerCase()];
    if (month) add(match.index, match.index + match[0].length, +match[3], month, +match[1]);
  }
  return found.sort((a, b) => a.start - b.start);
}

function splitSegments(text, fallbackDate) {
  const cleaned = stripWhen(text).replace(/\s+/g, " ").trim();
  if (!cleaned) return [];
  const dates = explicitDates(cleaned);
  if (!dates.length) return [{ date: fallbackDate || "", clause: cleaned }];

  const segments = [];
  let previousEnd = 0;
  dates.forEach((item) => {
    const clause = cleaned.slice(previousEnd, item.end).trim();
    previousEnd = item.end;
    if (/[a-z]{4}/i.test(clause.replace(/[\d-]/g, ""))) {
      segments.push({ date: item.iso, clause });
    }
  });

  const trailing = cleaned.slice(previousEnd).trim();
  if (/[a-z]/i.test(trailing)) {
    if (segments.length) {
      segments[segments.length - 1].clause += ` ${trailing}`;
    } else {
      return [{ date: fallbackDate || "", clause: cleaned }];
    }
  }
  if (!segments.length) return [{ date: fallbackDate || "", clause: cleaned }];

  return segments.map((segment) => ({
    date: segment.date,
    clause: segment.clause
      .replace(/^(?:and|but|then|so|later)\s+/i, "")
      .replace(/\s+([.,;])/g, "$1")
      .trim(),
  }));
}

function objectPhrase(lowered) {
  return OBJECT_WORDS.find((word) => lowered.includes(word)) || "";
}

function contextKind(lowered) {
  if (/\bplant(?:ed|ing)?\b|\bsow(?:n|ing)?\b|\btransplant/.test(lowered)) return "planting";
  if (/\bfung|\bdisease|\bblight|\bpathogen/.test(lowered)) return "disease";
  if (/\brain|\bflood|waterlog|water-log/.test(lowered)) return "weather";
  if (lowered.includes("irrigat")) return "irrigation";
  if (lowered.includes("soil moisture")) return "soil";
  return null;
}

function contextEvent(kind, lowered, crop) {
  if (kind === "planting") return { kind, label: `${(crop || "Crop").trim()} planted` };
  if (kind === "weather") {
    const rain = /\brain/.test(lowered);
    const water = /waterlog|water-log|\bflood/.test(lowered);
    if (rain && water) return { kind, label: "Heavy rain caused waterlogging" };
    if (water) return { kind, label: "Waterlogging recorded" };
    return { kind, label: "Heavy rain recorded" };
  }
  if (kind === "irrigation") {
    return {
      kind,
      label: /problem|issue|irregular|poor/.test(lowered) ? "Irrigation problem" : "Irrigation recorded",
    };
  }
  const failed = FAIL_RE.test(lowered);
  const succeeded = !failed && !INTENT_RE.test(lowered) && SUCCESS_RE.test(lowered);
  if (kind === "soil") {
    if (succeeded) return { kind: "outcome_ok", label: "Soil moisture improved" };
    const dropped = /\b(?:drop(?:ped)?|fell|low|declin\w*|dry)/.test(lowered);
    if (failed || dropped) {
      return {
        kind: "soil",
        label: dropped || /reduc|fell/.test(lowered)
          ? "Soil moisture dropped"
          : "Soil moisture problem",
      };
    }
    return { kind, label: "Soil moisture recorded" };
  }
  if (succeeded) return { kind: "outcome_ok", label: "Fungal symptoms reduced" };
  if (failed) return { kind: "outcome_fail", label: "Fungal symptoms worsened" };
  return { kind, label: "Fungal symptoms recorded" };
}

function pushOutcome(byName, name, outcome) {
  const entry = byName.get(name) || { name, appliedDates: [], outcomes: [] };
  if (outcome.status === "applied") {
    if (outcome.date && !entry.appliedDates.includes(outcome.date)) {
      entry.appliedDates.push(outcome.date);
    }
  } else {
    const duplicate = entry.outcomes.some(
      (item) =>
        item.date === outcome.date &&
        item.status === outcome.status &&
        item.object === outcome.object
    );
    if (!duplicate) entry.outcomes.push(outcome);
  }
  byName.set(name, entry);
}

function evidenceRows(memories, crop) {
  const byName = new Map();
  const context = [];
  const contextKeys = new Set();

  memories.forEach((memory) => {
    const text = stripWhen(memory.text || "");
    if (!text.trim()) return;
    const segments = splitSegments(text, memory.date);
    let carry = null;

    segments.forEach((segment) => {
      const clause = segment.clause;
      const lowered = clause.toLowerCase();
      const namedMatch = clause.match(TREATMENT_RE);
      const named = namedMatch ? namedMatch[0].toLowerCase() : null;
      if (named) carry = named;

      const failed = FAIL_RE.test(clause);
      const succeeded = !failed && !INTENT_RE.test(clause) && SUCCESS_RE.test(clause);
      const applied = APPLIED_RE.test(clause);
      const linked = named || (carry && (failed || succeeded || applied) ? carry : null);

      if (linked && !failed && !succeeded && applied) {
        pushOutcome(byName, linked, { status: "applied", date: segment.date, object: "" });
        return;
      }
      if (linked && (failed || succeeded)) {
        pushOutcome(byName, linked, {
          status: failed ? "failure" : "success",
          date: segment.date,
          object: objectPhrase(lowered),
        });
        return;
      }
      const kind = contextKind(lowered);
      if (kind) {
        const event = contextEvent(kind, lowered, crop);
        const key = `${segment.date}|${event.kind}|${event.label}`;
        if (!contextKeys.has(key)) {
          contextKeys.add(key);
          context.push({ kind: event.kind, date: segment.date, label: event.label });
        }
        return;
      }
      if (linked) {
        pushOutcome(byName, linked, { status: "applied", date: segment.date, object: "" });
      }
    });
  });

  const rows = [];
  byName.forEach((entry) => {
    const label = titleCase(entry.name);
    if (entry.outcomes.length) {
      const sorted = entry.outcomes
        .slice()
        .sort((a, b) => (a.date || "").localeCompare(b.date || ""));
      const latest = sorted[sorted.length - 1];
      const earlier = sorted.slice(0, -1);
      const object = latest.object;
      const text =
        latest.status === "success"
          ? object
            ? `${label} previously improved ${lowerFirst(object)}`
            : `${label} previously helped`
          : object
            ? `${label} previously failed to improve ${lowerFirst(object)}`
            : `${label} previously did not help`;
      const appliedDate =
        latest.status === "success"
          ? entry.appliedDates
              .filter((day) => day && (!latest.date || day <= latest.date))
              .sort()
              .pop() || ""
          : "";
      const when =
        appliedDate && latest.date && appliedDate !== latest.date
          ? `${shortDate(appliedDate)} → ${shortDate(latest.date)}`
          : latest.date
            ? shortDate(latest.date)
            : "";
      rows.push({
        order: latest.date || appliedDate || "",
        mark: latest.status === "success" ? "ok" : "fail",
        text,
        when,
        sub: earlier.length
          ? `earlier: ${earlier
              .map(
                (item) =>
                  `${item.status === "success" ? "helped" : "failed"}${
                    item.date ? ` (${shortDate(item.date)})` : ""
                  }`
              )
              .join(" · ")}`
          : "",
      });
    } else if (entry.appliedDates.length) {
      const last = entry.appliedDates.slice().sort().pop();
      rows.push({ order: last, mark: "neutral", text: `${label} was applied`, when: shortDate(last), sub: "" });
    }
  });

  context.forEach((event) => {
    rows.push({
      order: event.date || "",
      mark: "context",
      text: `${EVENT_ICONS[event.kind] || "📌"} ${event.label}`,
      when: event.date ? shortDate(event.date) : "",
      sub: "",
    });
  });

  rows.sort((a, b) => {
    if (a.order && b.order) return a.order.localeCompare(b.order);
    if (a.order) return -1;
    if (b.order) return 1;
    return 0;
  });
  return rows;
}

function renderWhy(memories) {
  const crop = currentField ? currentField.crop : "";
  const rows = memories.length ? evidenceRows(memories, crop) : [];
  if (!rows.length) {
    els.whyCard.hidden = true;
    els.whyList.innerHTML = "";
    return;
  }

  els.whyList.innerHTML = rows
    .map((row) => {
      const cls =
        row.mark === "ok"
          ? "why-ok"
          : row.mark === "fail"
            ? "why-fail"
            : row.mark === "neutral"
              ? "why-neutral"
              : "why-context";
      const when = row.when ? `<span class="why-when">${escapeHtml(row.when)}</span>` : "";
      const sub = row.sub ? `<div class="why-earlier">${escapeHtml(row.sub)}</div>` : "";
      return `<li class="${cls}">${escapeHtml(row.text)}${when}${sub}</li>`;
    })
    .join("");
  els.whyCard.hidden = false;
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
  const retrieved = data.memory_count;
  const used =
    typeof data.memories_used_count === "number" ? data.memories_used_count : retrieved;
  els.actRecalled.textContent = String(retrieved);
  els.actUsed.textContent = String(used);
  els.memoryUsed.textContent = String(used);
  els.actRetained.textContent = String(data.new_memories_stored);
  const usedHistory = retrieved > 0;
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

function renderMemories(memories) {
  els.memoryCount.textContent = String(memories.length);
  const heading = document.getElementById("memory-heading");
  if (!memories.length) {
    if (heading) heading.textContent = "🧠 No previous field history yet";
    els.memoryList.innerHTML =
      '<li class="memory-empty">No previous field history yet — this answer is general guidance for the question you asked. KisanMemory will remember useful field experiences for next time.</li>';
    return;
  }
  if (heading) heading.textContent = "🧠 Memory Used";

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
        `<span class="chip">saved to your field history</span>` +
        `</div></li>`
    );
  });

  skipped.forEach((text) => {
    items.push(
      `<li class="learning-dup"><div>${escapeHtml(stripWhen(text))}</div>` +
        `<div class="learning-meta">` +
        `<span class="chip">already remembered</span>` +
        `<span class="chip">no duplicate created</span>` +
        `</div></li>`
    );
  });

  els.learningList.innerHTML = items.join("");
  title.textContent = hasRetained
    ? "💾 Memory Updated — what KisanMemory now remembers"
    : "💾 ALREADY REMEMBERED — duplicate ignored, nothing stored twice";
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
        const icon = EVENT_ICONS[event.kind] || EVENT_ICONS.other;
        const headline =
          event.kind && event.kind !== "other" && event.label
            ? `<div class="timeline-event">${escapeHtml(icon)} ${escapeHtml(event.label)}</div>`
            : "";
        return (
          `<li class="${isLatest ? "timeline-new" : event.date ? "" : "timeline-undated"}">` +
          `<div class="timeline-date">${escapeHtml(dateText)}${isLatest ? " · new" : ""}</div>` +
          headline +
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
    setPill(els.statusHindsight, Boolean(data.hindsight), "Memory");
    setPill(els.statusLlm, Boolean(data.llm), "AI");
  } catch (error) {
    setPill(els.statusHindsight, false, "Memory");
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
    els.fieldSelect.innerHTML = '<option value="">No fields yet — create one</option>';
    currentField = null;
    if (mode === "signed-in") openFieldForm();
  }
  updateScope();
  await loadTimeline();
  await loadHistory();
}

async function loadHistory() {
  if (!currentField) return;
  try {
    const response = await fetch(`/conversations?field_id=${currentField.id}`, {
      headers: userHeaders(),
    });
    if (!response.ok) throw new Error("history unavailable");
    const conversations = await response.json();
    if (!conversations.length) return;
    const messagesResponse = await fetch(`/conversations/${conversations[0].id}/messages`, {
      headers: userHeaders(),
    });
    if (!messagesResponse.ok) throw new Error("history unavailable");
    const messages = await messagesResponse.json();
    if (!messages.length) return;
    els.messages.innerHTML = "";
    messages.forEach((message) => {
      if (message.role === "user") {
        appendMessage(
          "farmer",
          "SAVED MESSAGE",
          `${currentUser ? currentUser.name : "Farmer"} · ${currentField.name}`,
          message.message
        );
      } else if (message.role === "assistant") {
        appendMessage("ai", "SAVED AI RESPONSE", "from your saved field history", message.message);
      }
    });
  } catch (error) {
    // Conversation history is optional; the live chat still works without it.
  }
}

async function askQuestion(message) {
  if (busy || !message) return;
  if (!currentField) {
    showError("Create or select a field first.");
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
    "Recalling your field history…"
  );
  thinking.classList.add("msg-thinking");

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: userHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        field_id: currentField.id,
        message,
        language: els.langSelect.value || "English",
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail =
        typeof data.detail === "string" && data.detail
          ? data.detail
          : "Something went wrong. Please try again.";
      throw new Error(detail);
    }

    thinking.remove();
    const usedCount = (data.memories_used || []).length;
    appendMessage(
      "ai",
      "AI RESPONSE",
      usedCount ? "personalized from field memory" : "answered from current question · general guidance",
      data.response
    );
    renderMemories(data.memories_used || []);
    renderActivity(data);
    renderWhy(data.memories_used || []);
    renderLearning(data.retained_memories || [], data.skipped_experiences || []);
    els.compareAnswer.textContent = data.response;
    els.compareMeta.textContent = usedCount
      ? `${usedCount} real memories from ${currentUser.name}'s field history`
      : "No previous field history yet — answered from the current question";
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
  const memoryHeading = document.getElementById("memory-heading");
  if (memoryHeading) memoryHeading.textContent = "🧠 Memory Used";
  els.learningPanel.hidden = true;
  els.learningList.innerHTML = "";
  els.whyCard.hidden = true;
  els.whyList.innerHTML = "";
  els.actRecalled.textContent = "0";
  els.actUsed.textContent = "0";
  els.memoryUsed.textContent = "0";
  els.actRetained.textContent = "0";
  els.actHistory.textContent = "—";
  els.actHistory.classList.remove("activity-yes", "activity-no");
  els.actDup.hidden = true;
  els.actDup.textContent = "";
  clearError();
  latestRetainedDate = null;
  els.input.value = "";
  els.compareAnswer.textContent =
    "Ask a question above to see a real personalized answer from this field's own history.";
  els.compareMeta.textContent = "Your actual answer will appear here after you ask.";
  checkHealth();
  els.input.focus();
}

/* ---------------- welcome / auth ---------------- */

function showAuthError(message) {
  els.authError.textContent = message;
  els.authError.hidden = false;
}

function hideAuthError() {
  els.authError.hidden = true;
  els.authError.textContent = "";
}

function showWelcome() {
  mode = "welcome";
  els.app.hidden = true;
  els.welcome.hidden = false;
  els.welcomeActions.hidden = false;
  els.signinForm.hidden = true;
  els.signupForm.hidden = true;
  hideAuthError();
}

function showAuthForm(which) {
  hideAuthError();
  els.welcomeActions.hidden = true;
  els.signinForm.hidden = which !== "signin";
  els.signupForm.hidden = which !== "signup";
  if (which === "signin") {
    els.signinPassword.value = "";
    els.signinEmail.focus();
  } else {
    els.signupName.focus();
  }
}

function enterApp(user, chosenMode) {
  mode = chosenMode;
  currentUser = user;
  els.welcome.hidden = true;
  els.app.hidden = false;
  els.accountName.hidden = false;
  els.logoutBtn.hidden = false;
  els.reset.hidden = chosenMode !== "demo";
  els.demoBadge.hidden = chosenMode !== "demo";
  els.userSelectWrap.hidden = chosenMode !== "demo";
  els.newFieldBtn.hidden = false;
  els.accountName.textContent =
    chosenMode === "demo" ? "Demo mode" : `${user.name}${user.village ? ` · ${user.village}` : ""}`;
  if (user.preferred_language) {
    const match = Array.from(els.langSelect.options).find(
      (option) => option.value === user.preferred_language
    );
    if (match) els.langSelect.value = user.preferred_language;
  }
  resetDemo();
  updateScope();
  loadFields();
}

async function boot() {
  checkHealth();
  try {
    const response = await fetch("/auth/me");
    if (response.ok) {
      const user = await response.json();
      enterApp(user, "signed-in");
      return;
    }
  } catch (error) {
    // Fall through to the welcome screen.
  }
  showWelcome();
}

els.goSignin.addEventListener("click", () => showAuthForm("signin"));
els.goSignup.addEventListener("click", () => showAuthForm("signup"));
els.goDemo.addEventListener("click", () => {
  hideAuthError();
  currentUser = DEMO_USERS[0];
  els.userSelect.value = currentUser.id;
  enterApp(DEMO_USERS[0], "demo");
});

document.querySelectorAll("[data-back]").forEach((button) => {
  button.addEventListener("click", showWelcome);
});

els.signinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideAuthError();
  const email = els.signinEmail.value.trim();
  const password = els.signinPassword.value;
  if (!email || !password) {
    showAuthError("Enter your email and password.");
    return;
  }
  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      showAuthError(typeof data.detail === "string" ? data.detail : "Sign in failed.");
      return;
    }
    els.signinPassword.value = "";
    enterApp(data, "signed-in");
  } catch (error) {
    showAuthError("Network problem — check your connection and try again.");
  }
});

els.signupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideAuthError();
  const name = els.signupName.value.trim();
  const email = els.signupEmail.value.trim();
  const password = els.signupPassword.value;
  if (!name || !email || !password) {
    showAuthError("Fill in your name, email, and password.");
    return;
  }
  if (password.length < 8) {
    showAuthError("Password must be at least 8 characters.");
    return;
  }
  try {
    const response = await fetch("/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        email,
        password,
        village: els.signupVillage.value.trim() || null,
        state: els.signupState.value.trim() || null,
        preferred_language: els.signupLanguage.value,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      showAuthError(typeof data.detail === "string" ? data.detail : "Registration failed.");
      return;
    }
    els.signupPassword.value = "";
    enterApp(data, "signed-in");
  } catch (error) {
    showAuthError("Network problem — check your connection and try again.");
  }
});

els.logoutBtn.addEventListener("click", async () => {
  try {
    await fetch("/auth/logout", { method: "POST" });
  } catch (error) {
    // Signing out locally is still correct if the network fails.
  }
  currentUser = null;
  currentField = null;
  availableFields = [];
  els.accountName.hidden = true;
  els.logoutBtn.hidden = true;
  showWelcome();
});

/* ---------------- field creation ---------------- */

function openFieldForm() {
  els.fieldForm.hidden = false;
  els.fieldName.value = "";
  els.fieldCrop.value = "";
  els.fieldName.focus();
}

els.newFieldBtn.addEventListener("click", openFieldForm);
els.fieldCancel.addEventListener("click", () => {
  els.fieldForm.hidden = true;
});

els.fieldForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();
  const name = els.fieldName.value.trim();
  if (!name) return;
  try {
    const response = await fetch("/fields", {
      method: "POST",
      headers: userHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ name, crop: els.fieldCrop.value.trim() }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      showError(typeof data.detail === "string" ? data.detail : "Could not create the field.");
      return;
    }
    els.fieldForm.hidden = true;
    await loadFields();
  } catch (error) {
    showError("Network problem — check your connection and try again.");
  }
});

/* ---------------- chat wiring ---------------- */

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
  loadTimeline();
  loadHistory();
});

boot();
setInterval(checkHealth, 30000);
