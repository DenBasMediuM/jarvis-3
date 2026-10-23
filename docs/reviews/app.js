/* global Chart */

const $ = (sel) => document.querySelector(sel);
const LS_GOOGLE = "jarvis.reviews.googleDay";
const LS_DONE = "jarvis.reviews.doneTickets";
const LS_DEFER = "jarvis.reviews.deferred";

let DATA = null;
let googleChart = null;

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function todayISO() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

function vitrineLogin() {
  try {
    return window.JarvisVitrineAuth?.session()?.login || "";
  } catch {
    return "";
  }
}

function loadDone() {
  try {
    return new Set(JSON.parse(localStorage.getItem(LS_DONE) || "[]"));
  } catch {
    return new Set();
  }
}

function saveDone(set) {
  localStorage.setItem(LS_DONE, JSON.stringify([...set]));
}

function loadDeferred() {
  try {
    return new Set(JSON.parse(localStorage.getItem(LS_DEFER) || "[]"));
  } catch {
    return new Set();
  }
}

function saveDeferred(set) {
  localStorage.setItem(LS_DEFER, JSON.stringify([...set]));
}

function googleGateDoneToday() {
  try {
    return localStorage.getItem(LS_GOOGLE) === todayISO();
  } catch {
    return false;
  }
}

function markGoogleGateDone() {
  localStorage.setItem(LS_GOOGLE, todayISO());
}

function inboxBase() {
  return String(DATA?.inbox?.url || "").replace(/\/$/, "");
}

function writeKey() {
  return DATA?.inbox?.write_key || "";
}

function fmtWhen(issuedAt) {
  if (!issuedAt) return " недавно";
  const d = String(issuedAt);
  const m = d.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return ` (${d})`;
  return ` ${m[3]}.${m[2]}.${m[1]}`;
}

function renderScript(card) {
  const script = DATA?.call_script || {};
  const steps = Array.isArray(script.steps) ? script.steps : [];
  const device = card.device || "технику";
  const when = fmtWhen(card.issued_at);
  return steps
    .map((s) => {
      const text = String(s.text || "")
        .replaceAll("{device}", device)
        .replaceAll("{when_phrase}", when ? `, выдача${when}` : "");
      return `<div class="reviews-script">
        <h4>${escapeHtml(s.label || "")}</h4>
        <p>${escapeHtml(text)}</p>
      </div>`;
    })
    .join("");
}

function showGate() {
  const gate = $("#reviews-gate");
  const work = $("#reviews-work");
  if (gate) gate.hidden = false;
  if (work) work.hidden = true;
  const branches = DATA?.branches || [];
  const box = $("#reviews-gate-branches");
  if (!box) return;
  box.innerHTML = branches
    .map(
      (b) => `<article class="reviews-branch-card" data-branch="${escapeHtml(b.id)}">
        <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center">
          <h3>${escapeHtml(b.name)}</h3>
          <a class="reviews-btn" href="${escapeHtml(b.maps_url)}" target="_blank" rel="noopener">Открыть в Google ↗</a>
        </div>
        <p class="card-sub">Откройте карточку, посмотрите рейтинг и число отзывов, введите сюда.</p>
        <div class="reviews-branch-fields">
          <label>Рейтинг (1–5)<input type="number" min="1" max="5" step="0.1" data-rating required /></label>
          <label>Число отзывов<input type="number" min="0" step="1" data-count required /></label>
        </div>
      </article>`,
    )
    .join("");
}

async function submitGoogleGate() {
  const status = $("#reviews-gate-status");
  const branches = [];
  document.querySelectorAll("#reviews-gate-branches [data-branch]").forEach((el) => {
    const id = el.getAttribute("data-branch");
    const rating = Number(el.querySelector("[data-rating]")?.value);
    const review_count = Number(el.querySelector("[data-count]")?.value);
    branches.push({ id, rating, review_count });
  });
  if (!inboxBase() || !writeKey()) {
    if (status) status.textContent = "Inbox не настроен — экспортируйте модуль из Jarvis после деплоя Worker.";
    return;
  }
  if (status) status.textContent = "Отправка…";
  try {
    const res = await fetch(`${inboxBase()}/google-stats`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${writeKey()}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        day: todayISO(),
        manager: vitrineLogin() || undefined,
        branches,
      }),
    });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(j.error || res.statusText);
    markGoogleGateDone();
    if (status) status.textContent = "Сохранено. Можно начинать прозвон.";
    showWork();
  } catch (err) {
    if (status) status.textContent = `Ошибка: ${err.message || err}`;
  }
}

function showWork() {
  const gate = $("#reviews-gate");
  const work = $("#reviews-work");
  if (gate) gate.hidden = true;
  if (work) work.hidden = false;
  renderQueue();
  renderGoogleLatest();
}

function renderGoogleLatest() {
  const el = $("#reviews-google-latest");
  if (!el) return;
  const rows = DATA?.google_latest || [];
  if (!rows.length) {
    el.textContent = "В снимке ещё нет сохранённых рейтингов (появятся после ingest в Jarvis).";
    return;
  }
  const byId = Object.fromEntries((DATA?.branches || []).map((b) => [b.id, b.name]));
  el.innerHTML = rows
    .map(
      (r) => `<span class="chip">${escapeHtml(byId[r.branch_id] || r.branch_id)}:
        <strong>${escapeHtml(r.rating)}</strong> · ${escapeHtml(r.review_count)} отз.
        · ${escapeHtml(String(r.day || ""))}</span>`,
    )
    .join(" ");
}

function renderQueue() {
  const list = $("#reviews-queue");
  const meta = $("#reviews-queue-meta");
  const cards = Array.isArray(DATA?.cards) ? DATA.cards : [];
  const done = loadDone();
  const deferred = loadDeferred();
  const active = cards.filter((c) => !done.has(String(c.ticket)) && !deferred.has(String(c.ticket)));
  const deferredCards = cards.filter((c) => deferred.has(String(c.ticket)) && !done.has(String(c.ticket)));
  if (meta) {
    meta.textContent = `Очередь на ${DATA?.batch?.day || "—"} · осталось ${active.length} · отложено ${deferredCards.length} · сделано ${done.size}`;
  }
  if (!list) return;
  if (!cards.length) {
    list.innerHTML = `<p class="empty">Нет карточек в снимке. В админке Jarvis: Сбор отзывов → «Собрать очередь» → экспорт/публикация.</p>`;
    return;
  }
  const ordered = [...active, ...deferredCards];
  list.innerHTML = ordered
    .map((c) => {
      const t = String(c.ticket);
      const isDef = deferred.has(t);
      const isDone = done.has(t);
      return `<button type="button" class="reviews-queue-item${isDone ? " is-done" : ""}" data-ticket="${escapeHtml(t)}">
        <span><strong>№${escapeHtml(t)}</strong> · ${escapeHtml(c.client_name || "клиент")}
          <br><span class="card-sub">${escapeHtml(c.device || "—")} · ${escapeHtml(c.branch_name || c.location || "—")}</span></span>
        <span class="card-sub">${isDef ? "отложено" : isDone ? "готово" : "открыть"}</span>
      </button>`;
    })
    .join("");
  list.querySelectorAll("[data-ticket]").forEach((btn) => {
    btn.addEventListener("click", () => openCard(btn.getAttribute("data-ticket")));
  });
}

function closeModal() {
  document.getElementById("reviews-modal")?.remove();
}

function openCard(ticket) {
  const card = (DATA?.cards || []).find((c) => String(c.ticket) === String(ticket));
  if (!card) return;
  closeModal();
  const outcomes = DATA?.outcomes || {};
  const feed = Array.isArray(card.live_feed) ? card.live_feed : [];
  const overlay = document.createElement("div");
  overlay.id = "reviews-modal";
  overlay.className = "reviews-modal-overlay";
  overlay.innerHTML = `<div class="reviews-modal">
    <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap">
      <div>
        <p class="card-sub">Сбор отзывов · карточка</p>
        <h2 style="margin:4px 0">№${escapeHtml(card.ticket)} · ${escapeHtml(card.client_name || "клиент")}</h2>
        <p>${escapeHtml(card.phone || "телефон не найден")} · ${escapeHtml(card.device || "—")}</p>
      </div>
      <div class="reviews-actions">
        ${card.crm_url ? `<a class="reviews-btn" href="${escapeHtml(card.crm_url)}" target="_blank" rel="noopener">CRM ↗</a>` : ""}
        ${card.review_url ? `<a class="reviews-btn is-primary" href="${escapeHtml(card.review_url)}" target="_blank" rel="noopener">Ссылка на отзыв ↗</a>` : ""}
        <button type="button" class="reviews-btn" data-close>Закрыть</button>
      </div>
    </div>
    <p class="card-sub">Выдача: ${escapeHtml(card.issued_at || "—")} · ремонт ~ ${escapeHtml(card.repair_days ?? "—")} дн. · филиал ${escapeHtml(card.branch_name || "—")}</p>
    <h3>Скрипт</h3>
    ${renderScript(card)}
    <h3>Комментарии CRM</h3>
    <div class="reviews-feed">${
      feed.length
        ? feed
            .map(
              (f) => `<article><header><span>${escapeHtml(f.date || "")}</span><span>${escapeHtml(f.author || "")}</span></header>
              <p>${escapeHtml(f.text || "")}</p></article>`,
            )
            .join("")
        : "<p class=\"card-sub\">Ленты нет в снимке</p>"
    }</div>
    <h3>Результат звонка</h3>
    <div class="reviews-outcomes">
      ${Object.entries(outcomes)
        .map(
          ([code, label]) =>
            `<button type="button" class="reviews-btn ${code === "will_review" ? "is-ok" : code === "unhappy" ? "is-bad" : ""}" data-outcome="${escapeHtml(code)}">${escapeHtml(label)}</button>`,
        )
        .join("")}
    </div>
    <label class="card-sub" style="display:grid;gap:6px;margin-top:10px">Комментарий (обязателен, если клиент не доволен)
      <textarea class="reviews-comment" data-comment placeholder="Чем не доволен / детали"></textarea>
    </label>
    <div class="reviews-actions">
      <button type="button" class="reviews-btn" data-defer>Отложить</button>
      <span class="reviews-status" data-status></span>
    </div>
  </div>`;
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });
  overlay.querySelector("[data-close]")?.addEventListener("click", closeModal);
  overlay.querySelector("[data-defer]")?.addEventListener("click", () => {
    const def = loadDeferred();
    def.add(String(ticket));
    saveDeferred(def);
    closeModal();
    renderQueue();
  });
  overlay.querySelectorAll("[data-outcome]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const outcome = btn.getAttribute("data-outcome");
      const comment = overlay.querySelector("[data-comment]")?.value || "";
      const statusEl = overlay.querySelector("[data-status]");
      if (!inboxBase() || !writeKey()) {
        if (statusEl) statusEl.textContent = "Inbox не настроен в снимке.";
        return;
      }
      if (statusEl) statusEl.textContent = "Отправка…";
      try {
        const res = await fetch(`${inboxBase()}/result`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${writeKey()}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            ticket: String(ticket),
            outcome,
            comment: comment || undefined,
            manager: vitrineLogin() || undefined,
            phone: card.phone,
            client_name: card.client_name,
            device: card.device,
            branch_id: card.branch_id,
            issued_at: card.issued_at,
            repair_days: card.repair_days,
          }),
        });
        const j = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(j.error || res.statusText);
        const done = loadDone();
        done.add(String(ticket));
        saveDone(done);
        const def = loadDeferred();
        def.delete(String(ticket));
        saveDeferred(def);
        closeModal();
        renderQueue();
      } catch (err) {
        if (statusEl) statusEl.textContent = `Ошибка: ${err.message || err}`;
      }
    });
  });
  document.body.appendChild(overlay);
}

async function boot() {
  const meta = $("#export-meta");
  try {
    const res = await fetch(`./data.json?t=${Date.now()}`);
    if (!res.ok) throw new Error(`data.json: ${res.status}`);
    DATA = await res.json();
  } catch (err) {
    if (meta) meta.textContent = `Нет снимка: ${err.message || err}`;
    showGate();
    return;
  }
  if (meta) {
    const when = DATA.exported_at ? new Date(DATA.exported_at).toLocaleString("ru-RU") : "—";
    meta.textContent = `Снимок: ${when} · карточек ${DATA.cards?.length ?? 0}`;
  }
  if (!DATA.branches?.length) {
    DATA.branches = [];
  }
  $("#reviews-start-btn")?.addEventListener("click", () => submitGoogleGate());
  if (googleGateDoneToday()) showWork();
  else showGate();
}

boot();
