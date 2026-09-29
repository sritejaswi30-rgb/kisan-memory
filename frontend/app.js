const DEMO_USERS = [
  { id: "1001", name: "Ravi" },
  { id: "1002", name: "Sita" },
];

const els = {
  screenWelcome: document.getElementById("screen-welcome"),
  screenSignin: document.getElementById("screen-signin"),
  screenSignup: document.getElementById("screen-signup"),
  app: document.getElementById("app"),
  welcomeActions: document.getElementById("welcome-actions"),
  signinForm: document.getElementById("signin-form"),
  signupForm: document.getElementById("signup-form"),
  authError: document.getElementById("auth-error"),
  signinError: document.getElementById("signin-error"),
  signupError: document.getElementById("signup-error"),
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
  suggest: document.getElementById("suggest"),
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
  emptySub: document.getElementById("empty-sub"),
  messages: document.getElementById("messages"),
  empty: document.getElementById("empty-state"),
  historyOpen: document.getElementById("history-open"),
  historyModal: document.getElementById("history-modal"),
  historyTitle: document.getElementById("history-title"),
  historySub: document.getElementById("history-sub"),
  historyClose: document.getElementById("history-close"),
  timeline: document.getElementById("timeline"),
  error: document.getElementById("error-banner"),
  errorText: document.getElementById("error-text"),
  errorDismiss: document.getElementById("error-dismiss"),
  statusHindsight: document.getElementById("status-hindsight"),
  statusLlm: document.getElementById("status-llm"),
};

let busy = false;
let latestRetainedDate = null;
let mode = "welcome"; // "welcome" | "demo" | "signed-in"
let screen = "welcome"; // "welcome" | "signin" | "signup" | "app"
let currentUser = null;
let currentField = null;
let availableFields = [];
let turnsShown = 0;

/* ---------------- helpers ---------------- */

function userHeaders(extra) {
  const headers = Object.assign({}, extra || {});
  if (mode === "demo" && currentUser) {
    headers["X-User-ID"] = currentUser.id;
  }
  return headers;
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

function activeAuthError() {
  if (screen === "signin") return els.signinError;
  if (screen === "signup") return els.signupError;
  return els.authError;
}

function showAuthError(message) {
  [els.authError, els.signinError, els.signupError].forEach((node) => {
    node.hidden = true;
    node.textContent = "";
  });
  const target = activeAuthError();
  target.textContent = message;
  target.hidden = false;
}

function hideAuthErrors() {
  [els.authError, els.signinError, els.signupError].forEach((node) => {
    node.hidden = true;
    node.textContent = "";
  });
}

function updateScope() {
  const fieldName = currentField ? currentField.name : "—";
  const farmerName = currentUser ? currentUser.name : "—";
  els.memoryScope.textContent = `Memory scope: ${farmerName} • ${fieldName} • private`;
  els.emptySub.textContent = currentUser
    ? `Answers come from ${farmerName}'s own recorded field history when there is one, and from solid general guidance when there is not.`
    : "Answers come from this farmer's own recorded field history.";
  els.historyTitle.textContent = `🌱 Field history — ${fieldName}`;
  els.historySub.textContent = `Complete history for ${farmerName} · ${fieldName}`;
}

/* ---------------- relevance: only what matters to THIS question ---------------- */

const STOP_WORDS = new Set(
  `what when where which who whom how why should would could can will shall do does did done is are was
   were be been being it this that these those there here his her their your our my me you we they them
   him us a an the of in on at to for from with by as if or and but so than then too very just about into
   over after before again any some all each no not yes give take make help need want used using one two
   now today tomorrow please tell show much many more most other another also`
    .split(/\s+/)
    .filter(Boolean)
);

function tokenize(text) {
  const words = new Set();
  String(text || "")
    .toLowerCase()
    .split(/[^a-z0-9\u0900-\u097f\u0c00-\u0c7f]+/)
    .forEach((raw) => {
      const word = raw.replace(/(ing|ed|es|s)$/, "");
      if (word.length > 2 && !STOP_WORDS.has(word)) words.add(word);
    });
  return words;
}

function tokenMatches(token, set) {
  if (set.has(token)) return true;
  if (token.length < 4) return false;
  for (const other of set) {
    if (other.length >= 4 && (other.startsWith(token) || token.startsWith(other))) return true;
  }
  return false;
}

function containment(a, b) {
  if (!a.size || !b.size) return 0;
  let shared = 0;
  a.forEach((token) => {
    if (tokenMatches(token, b)) shared += 1;
  });
  return shared / Math.min(a.size, b.size);
}

function mentionsOtherField(text, fieldName) {
  const lowered = String(text || "").toLowerCase();
  const current = String(fieldName || "").toLowerCase();
  return availableFields.some((field) => {
    const name = String(field.name || "").toLowerCase().trim();
    if (!name || name.length < 3 || name === current) return false;
    return new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`).test(lowered);
  });
}

function selectRelevant(memories, facts, question) {
  const scoped = memories.filter(
    (memory) => !mentionsOtherField(memory.text, currentField ? currentField.name : "")
  );
  const questionTokens = tokenize(question);
  const factTokens = (facts || []).map(tokenize).filter((tokens) => tokens.size);

  const ranked = scoped
    .map((memory) => {
      const memoryTokens = tokenize(memory.text);
      let score = containment(questionTokens, memoryTokens);
      factTokens.forEach((tokens) => {
        score = Math.max(score, containment(tokens, memoryTokens));
      });
      return { memory, score };
    })
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score);

  // Strongly relevant only. Anything below this is not shown, so an unrelated
  // memory (another crop, another plot, a preference note) never appears.
  const strong = ranked.filter((entry) => entry.score >= 0.4).slice(0, 4);
  if (strong.length) return strong.map((entry) => entry.memory);

  const moderate = ranked.filter((entry) => entry.score >= 0.2).slice(0, 3);
  return moderate.map((entry) => entry.memory);
}

/* ---------------- conversation rendering (question → memory → answer) ---------------- */

function buildTurn(question, metaLabel) {
  els.empty.hidden = true;
  const turn = document.createElement("div");
  turn.className = "turn";
  turn.innerHTML =
    `<div class="turn-part turn-you">` +
    `<div class="turn-role">YOU</div>` +
    `<div class="turn-text">${escapeHtml(question)}</div>` +
    `<div class="turn-meta">${escapeHtml(metaLabel)}</div>` +
    `</div>`;
  els.messages.appendChild(turn);
  turn.scrollIntoView({ block: "nearest", behavior: "smooth" });
  return turn;
}

function memoryBlock(head, items, kind, sub) {
  const hasItems = items && items.length;
  if (!hasItems && !sub) return "";
  const list = hasItems
    ? `<ul class="mem-list">` +
      items
        .map((item) => {
          const chip = item.date
            ? `<span class="chip chip-date">${escapeHtml(formatDate(item.date))}</span>`
            : item.tag
              ? `<span class="chip chip-type">${escapeHtml(item.tag)}</span>`
              : "";
          return `<li>${chip}<span class="mem-line">${escapeHtml(stripWhen(item.text))}</span></li>`;
        })
        .join("") +
      `</ul>`
    : "";
  const subLine = sub ? `<div class="mem-sub">${escapeHtml(sub)}</div>` : "";
  return (
    `<div class="mem-block mem-${kind}">` +
    `<div class="mem-head">${escapeHtml(head)}</div>` +
    subLine +
    list +
    `</div>`
  );
}

function appendTurn(question, metaLabel, data) {
  const turn = buildTurn(question, metaLabel);
  const memories = data.memories_used || [];
  const relevant = selectRelevant(memories, data.memory_facts_used || [], question);
  const retained = data.retained_memories || [];
  const skipped = data.skipped_experiences || [];

  const memoryItems = relevant.map((memory) => ({
    date: memory.date,
    tag: memory.type,
    text: memory.text,
  }));

  const savedItems = retained.map((item) => ({
    date: item.date,
    tag: item.field,
    text: item.text,
  }));
  skipped.forEach((text) => {
    savedItems.push({ date: "", tag: "already remembered", text });
  });

  // 1. The answer sits DIRECTLY under the question.
  // 2. The memory indicator sits DIRECTLY under the answer.
  let indicator = "";
  if (relevant.length) {
    const countLabel =
      relevant.length === 1 ? "1 relevant memory used" : `${relevant.length} relevant memories used`;
    indicator = memoryBlock("🧠 Based on your field history", memoryItems, "relevant", countLabel);
  } else if (data.memory_saved) {
    indicator = memoryBlock(
      "✨ First answer for this topic",
      [],
      "fresh",
      "Saved for future conversations"
    );
  } else {
    indicator = memoryBlock(
      "✨ No directly relevant previous experience",
      [],
      "fresh",
      "Answered from your current question"
    );
  }

  const unavailable = data.memory_unavailable
    ? `<div class="mem-note">Memory temporarily unavailable — answer generated without previous field history.</div>`
    : "";

  const ai = document.createElement("div");
  ai.className = "turn-part turn-ai";
  ai.innerHTML =
    `<div class="turn-role">KISANMEMORY</div>` +
    `<div class="turn-answer">${escapeHtml(data.response)}</div>` +
    unavailable +
    indicator +
    (savedItems.length ? memoryBlock("💾 Saved for future use", savedItems, "new") : "");
  turn.appendChild(ai);

  if (retained.length) latestRetainedDate = retained[retained.length - 1].date;
  turn.scrollIntoView({ block: "nearest", behavior: "smooth" });
  return turn;
}

function appendSavedTurn(question, answer) {
  const turn = buildTurn(question, "saved to your account");
  const ai = document.createElement("div");
  ai.className = "turn-part turn-ai";
  ai.innerHTML =
    `<div class="turn-role">KISANMEMORY</div>` +
    `<div class="turn-answer">${escapeHtml(answer)}</div>` +
    `<div class="turn-note">✓ saved earlier — open “View all field history” for the full record</div>`;
  turn.appendChild(ai);
  return turn;
}

function appendThinking(question) {
  const turn = buildTurn(question, "asking…");
  const ai = document.createElement("div");
  ai.className = "turn-part turn-ai turn-thinking";
  ai.innerHTML =
    `<div class="turn-role">KISANMEMORY</div>` +
    `<div class="turn-answer thinking-text">Recalling your field history…</div>`;
  turn.appendChild(ai);
  return turn;
}

/* ---------------- field history (separate view) ---------------- */

async function loadTimeline() {
  if (!currentField) {
    els.timeline.innerHTML = '<li class="timeline-empty">Select a field to see its history.</li>';
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
      els.timeline.innerHTML =
        '<li class="timeline-empty">No field memories stored yet. Ask a question and useful experiences will be saved here.</li>';
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
        const headline =
          event.kind && event.kind !== "other" && event.label
            ? `<div class="timeline-event">${escapeHtml(event.label)}</div>`
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
    els.timeline.innerHTML = '<li class="timeline-empty">History is unavailable right now.</li>';
  }
}

function openHistory() {
  updateScope();
  els.historyModal.hidden = false;
  document.body.classList.add("modal-open");
  loadTimeline();
}

function closeHistory() {
  els.historyModal.hidden = true;
  document.body.classList.remove("modal-open");
}

/* ---------------- health / fields / history ---------------- */

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
    let question = null;
    messages.forEach((message) => {
      if (message.role === "user") {
        question = message.message;
      } else if (message.role === "assistant" && question !== null) {
        appendSavedTurn(question, message.message);
        question = null;
      }
    });
    els.suggest.hidden = true;
  } catch (error) {
    // Conversation history is optional; live chat still works without it.
  }
}

/* ---------------- asking ---------------- */

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

  const metaLabel = `${currentUser.name} · ${currentField.name}`;
  const thinking = appendThinking(message);

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
    appendTurn(message, metaLabel, data);
    turnsShown += 1;
    els.suggest.hidden = true;
    if ((data.retained_memories || []).length && !els.historyModal.hidden) loadTimeline();
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
  els.suggest.hidden = false;
  turnsShown = 0;
  latestRetainedDate = null;
  els.input.value = "";
  clearError();
  checkHealth();
  els.input.focus();
}

/* ---------------- screens ---------------- */

function showScreen(name) {
  screen = name;
  document.body.dataset.screen = name;
  els.screenWelcome.hidden = name !== "welcome";
  els.screenSignin.hidden = name !== "signin";
  els.screenSignup.hidden = name !== "signup";
  els.app.hidden = name !== "app";

  const inApp = name === "app";
  els.accountName.hidden = !inApp;
  els.logoutBtn.hidden = !inApp;
  hideAuthErrors();

  if (inApp) {
    if (location.hash) history.replaceState(null, "", location.pathname);
  } else if (mode === "welcome") {
    const hash = name === "welcome" ? "" : `#${name}`;
    if (location.hash !== hash) history.replaceState(null, "", hash || location.pathname);
  }
}

function showWelcome() {
  mode = "welcome";
  showScreen("welcome");
}

function enterApp(user, chosenMode) {
  mode = chosenMode;
  currentUser = user;
  showScreen("app");
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
  els.input.focus();
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
  const hash = (location.hash || "").replace("#", "");
  showScreen(hash === "signin" || hash === "signup" ? hash : "welcome");
}

/* ---------------- auth wiring ---------------- */

els.goSignin.addEventListener("click", () => showScreen("signin"));
els.goSignup.addEventListener("click", () => showScreen("signup"));
els.goDemo.addEventListener("click", () => {
  hideAuthErrors();
  currentUser = DEMO_USERS[0];
  els.userSelect.value = currentUser.id;
  enterApp(DEMO_USERS[0], "demo");
});

document.querySelectorAll("[data-go]").forEach((button) => {
  button.addEventListener("click", () => showScreen(button.dataset.go));
});

window.addEventListener("hashchange", () => {
  if (mode !== "welcome") return;
  const hash = (location.hash || "").replace("#", "");
  showScreen(hash === "signin" || hash === "signup" ? hash : "welcome");
});

els.signinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideAuthErrors();
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
  hideAuthErrors();
  const name = els.signupName.value.trim();
  const email = els.signupEmail.value.trim();
  const password = els.signupPassword.value;
  if (!name || !email || !password) {
    showAuthError("Fill in your farmer name, email, and password.");
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
  turnsShown = 0;
  els.messages.innerHTML = "";
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

els.historyOpen.addEventListener("click", openHistory);
els.historyClose.addEventListener("click", closeHistory);
els.historyModal.addEventListener("click", (event) => {
  if (event.target === els.historyModal) closeHistory();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !els.historyModal.hidden) closeHistory();
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
