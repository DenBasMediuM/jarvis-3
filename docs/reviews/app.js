const $ = (sel) => document.querySelector(sel);
const LS_DONE = "jarvis.reviews.doneTickets";
const LS_DEFER = "jarvis.reviews.deferred";
const SS_GATE = "jarvis.reviews.gateOk";

let DATA = null;
/** Рейтинги, введённые в текущей сессии (после гейта). */
let sessionGoogle = [];

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

function queueSize() {
  const n = Number(DATA?.queue_size ?? DATA?.counts?.queue_size ?? 10);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 10;
}

// ---------- состояние очереди ----------
// Общее для всех менеджеров: Worker хранит «отложено / сделано / звонит сейчас».
// Если Worker недоступен — работаем по старым отметкам этого браузера.
let QSTATE = null; // { tickets: {ticket: {s, by, at}} } | null (офлайн)
let qstateError = "";
let claimedTicket = null;
const LS_MIGRATED = "jarvis.reviews.migratedToShared";

function lsSet(key) {
  try {
    return new Set(JSON.parse(localStorage.getItem(key) || "[]"));
  } catch {
    return new Set();
  }
}
function lsSave(key, set) {
  try {
    localStorage.setItem(key, JSON.stringify([...set]));
  } catch {
    /* ignore */
  }
}
function stateTickets() {
  return QSTATE?.tickets || {};
}
function ticketsWith(status) {
  return new Set(
    Object.entries(stateTickets())
      .filter(([, v]) => v?.s === status)
      .map(([t]) => t),
  );
}
function loadDone() {
  return QSTATE ? ticketsWith("done") : lsSet(LS_DONE);
}
function loadDeferred() {
  return QSTATE ? ticketsWith("deferred") : lsSet(LS_DEFER);
}
function claimedByOthers() {
  const me = vitrineLogin();
  return new Set(
    Object.entries(stateTickets())
      .filter(([, v]) => v?.s === "claimed" && v.by && v.by !== me)
      .map(([t]) => t),
  );
}

async function stateRequest(method, body) {
  const res = await fetch(`${inboxBase()}/queue-state`, {
    method,
    headers: {
      Authorization: `Bearer ${writeKey()}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await res.json().catch(() => ({}));
  if (res.ok && j.tickets) QSTATE = { tickets: j.tickets };
  return { ok: res.ok, status: res.status, data: j };
}

async function fetchQueueState() {
  if (!inboxBase() || !writeKey()) {
    QSTATE = null;
    qstateError = "общая очередь не настроена в снимке";
    return;
  }
  try {
    const r = await stateRequest("GET");
    if (!r.ok) throw new Error(r.data.error || r.status);
    qstateError = "";
  } catch (err) {
    QSTATE = null;
    qstateError = `нет связи с общей очередью (${err.message || err}) — отметки только в этом браузере`;
  }
}

/** Один раз перенести старые отметки этого браузера в общую очередь. */
async function migrateLocalMarks() {
  if (!QSTATE) return;
  try {
    if (localStorage.getItem(LS_MIGRATED)) return;
  } catch {
    return;
  }
  const deferred = [...lsSet(LS_DEFER)];
  const done = [...lsSet(LS_DONE)];
  if (deferred.length || done.length) {
    const r = await stateRequest("POST", {
      migrate_deferred: deferred,
      migrate_done: done,
      by: vitrineLogin() || undefined,
    }).catch(() => ({ ok: false }));
    if (!r.ok) return;
  }
  try {
    localStorage.setItem(LS_MIGRATED, "1");
  } catch {
    /* ignore */
  }
}

/** defer | undefer | claim | release. Без связи — пишем в браузер. */
async function setTicketState(ticket, action) {
  const t = String(ticket);
  if (QSTATE) {
    try {
      const r = await stateRequest("POST", { ticket: t, action, by: vitrineLogin() || undefined });
      if (r.ok) return { ok: true };
      if (r.status === 409) return { ok: false, conflict: r.data.state || {}, error: r.data.error };
    } catch {
      /* упадём в локальный режим ниже */
    }
  }
  if (action === "defer" || action === "undefer") {
    const def = lsSet(LS_DEFER);
    if (action === "defer") def.add(t);
    else def.delete(t);
    lsSave(LS_DEFER, def);
  }
  return { ok: true, local: true };
}

function fmtStamp(iso) {
  const d = new Date(iso || "");
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
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

function poolCards() {
  return Array.isArray(DATA?.cards) ? DATA.cards : [];
}

/** Окно из QUEUE_SIZE — только активные; отложенные — отдельным блоком под очередью. */
function visibleQueue() {
  const done = loadDone();
  const deferred = loadDeferred();
  const busy = claimedByOthers();
  const pool = poolCards();
  const active = pool.filter((c) => {
    const t = String(c.ticket);
    return !done.has(t) && !deferred.has(t) && !busy.has(t);
  });
  const deferredCards = pool.filter((c) => {
    const t = String(c.ticket);
    return deferred.has(t) && !done.has(t);
  });
  const size = queueSize();
  const windowCards = active.slice(0, size);
  return {
    windowCards,
    deferredCards,
    busyCount: pool.filter((c) => busy.has(String(c.ticket)) && !done.has(String(c.ticket))).length,
    activeCount: active.length,
    deferredCount: deferredCards.length,
    doneCount: [...done].filter((t) => pool.some((c) => String(c.ticket) === t)).length,
    poolLeft: active.length + deferredCards.length,
    poolTotal: pool.length,
  };
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

function latestHint(branchId) {
  const rows = DATA?.google_latest || [];
  const hit = rows.find((r) => r.branch_id === branchId);
  if (!hit) return null;
  return { rating: hit.rating, review_count: hit.review_count, day: hit.day };
}

function showGate() {
  const gate = $("#reviews-gate");
  const work = $("#reviews-work");
  if (gate) {
    gate.hidden = false;
    gate.removeAttribute("hidden");
  }
  if (work) {
    work.hidden = true;
    work.setAttribute("hidden", "");
  }
  try {
    sessionStorage.removeItem(SS_GATE);
  } catch {
    /* ignore */
  }
  const branches = DATA?.branches || [];
  const box = $("#reviews-gate-branches");
  if (!box) return;
  box.innerHTML = branches
    .map((b, i) => {
      const hint = latestHint(b.id);
      const hintHtml = hint
        ? `<p class="reviews-branch-hint">В прошлом снимке: ★ ${escapeHtml(hint.rating)} · ${escapeHtml(hint.review_count)} отз. (${escapeHtml(String(hint.day || ""))})</p>`
        : `<p class="reviews-branch-hint">Откройте карточку в Google Maps и перенесите значения.</p>`;
      return `<article class="reviews-branch-card" data-branch="${escapeHtml(b.id)}">
        <div class="reviews-branch-top">
          <h3><span class="reviews-branch-num">${i + 1}</span>${escapeHtml(b.name)}</h3>
          <a class="reviews-btn is-primary" href="${escapeHtml(b.maps_url)}" target="_blank" rel="noopener">Открыть в Google ↗</a>
        </div>
        ${hintHtml}
        <div class="reviews-branch-fields">
          <label>Рейтинг ★ (1–5)
            <input type="number" min="1" max="5" step="0.1" inputmode="decimal" data-rating placeholder="4.5" required />
          </label>
          <label>Число отзывов
            <input type="number" min="0" step="1" inputmode="numeric" data-count placeholder="128" required />
          </label>
        </div>
      </article>`;
    })
    .join("");

  box.querySelectorAll("[data-branch]").forEach((el) => {
    const mark = () => {
      const rating = Number(el.querySelector("[data-rating]")?.value);
      const count = Number(el.querySelector("[data-count]")?.value);
      const ok =
        Number.isFinite(rating) &&
        rating >= 1 &&
        rating <= 5 &&
        Number.isFinite(count) &&
        count >= 0 &&
        Number.isInteger(count);
      el.classList.toggle("is-filled", ok);
    };
    el.querySelectorAll("input").forEach((inp) => {
      inp.addEventListener("input", mark);
      inp.addEventListener("change", mark);
    });
  });
}

function collectGateBranches() {
  const branches = [];
  const errors = [];
  document.querySelectorAll("#reviews-gate-branches [data-branch]").forEach((el) => {
    const id = el.getAttribute("data-branch");
    const name = el.querySelector("h3")?.textContent?.replace(/^\d+/, "").trim() || id;
    const rawRating = String(el.querySelector("[data-rating]")?.value ?? "").trim();
    const rawCount = String(el.querySelector("[data-count]")?.value ?? "").trim();
    const rating = Number(rawRating);
    const review_count = Number(rawCount);
    if (!rawRating || !Number.isFinite(rating) || rating < 1 || rating > 5) {
      errors.push(`${name}: укажите рейтинг 1–5`);
      return;
    }
    if (!rawCount || !Number.isFinite(review_count) || review_count < 0 || !Number.isInteger(review_count)) {
      errors.push(`${name}: укажите целое число отзывов`);
      return;
    }
    branches.push({ id, rating, review_count });
  });
  return { branches, errors };
}

async function submitGoogleGate() {
  const status = $("#reviews-gate-status");
  const btn = $("#reviews-start-btn");
  const { branches, errors } = collectGateBranches();
  if (errors.length) {
    if (status) status.textContent = errors[0];
    return;
  }
  if (branches.length < (DATA?.branches || []).length) {
    if (status) status.textContent = "Заполните все три филиала.";
    return;
  }
  if (!inboxBase() || !writeKey()) {
    if (status) status.textContent = "Inbox не настроен — опубликуйте витрину из Jarvis после деплоя Worker.";
    return;
  }
  if (status) status.textContent = "Отправка…";
  if (btn) btn.disabled = true;
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
    sessionGoogle = branches;
    try {
      sessionStorage.setItem(SS_GATE, "1");
    } catch {
      /* ignore */
    }
    if (status) status.textContent = "Сохранено.";
    showWork();
  } catch (err) {
    if (status) status.textContent = `Ошибка: ${err.message || err}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

function showWork() {
  const gate = $("#reviews-gate");
  const work = $("#reviews-work");
  if (gate) {
    gate.hidden = true;
    gate.setAttribute("hidden", "");
  }
  if (work) {
    work.hidden = false;
    work.removeAttribute("hidden");
  }
  renderSessionGoogle();
  renderQueue();
  refreshSharedQueue({ migrate: true });
  if (!window.__reviewsQueuePoll) {
    window.__reviewsQueuePoll = setInterval(() => {
      if (!document.hidden && !$("#reviews-work")?.hidden) refreshSharedQueue();
    }, 60_000);
    window.addEventListener("focus", () => refreshSharedQueue());
  }
}

async function refreshSharedQueue({ migrate = false } = {}) {
  await fetchQueueState();
  if (migrate) await migrateLocalMarks();
  renderQueue();
}

function alertInQueue(text) {
  const list = $("#reviews-queue");
  if (!list) return;
  const p = document.createElement("p");
  p.className = "reviews-busy";
  p.textContent = text;
  list.prepend(p);
  setTimeout(() => p.remove(), 6000);
}

function renderSessionGoogle() {
  const el = $("#reviews-session-google");
  if (!el) return;
  const byId = Object.fromEntries((DATA?.branches || []).map((b) => [b.id, b.name]));
  const rows = sessionGoogle.length
    ? sessionGoogle
    : (DATA?.google_latest || []).map((r) => ({
        id: r.branch_id,
        rating: r.rating,
        review_count: r.review_count,
      }));
  if (!rows.length) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = rows
    .map(
      (r) =>
        `<span class="chip">${escapeHtml(byId[r.id] || r.id)}: <strong>★ ${escapeHtml(r.rating)}</strong> · ${escapeHtml(r.review_count)}</span>`,
    )
    .join("");
}

function renderQueue() {
  const list = $("#reviews-queue");
  const meta = $("#reviews-queue-meta");
  const q = visibleQueue();
  if (meta) {
    meta.textContent =
      `В окне ${q.windowCards.length} из ${queueSize()} · в пуле ещё ${q.poolLeft} · сделано ${q.doneCount}` +
      (q.deferredCount ? ` · отложено ${q.deferredCount}` : "") +
      (q.busyCount ? ` · звонят коллеги ${q.busyCount}` : "") +
      ` · снимок ${DATA?.batch?.day || "—"} (${q.poolTotal} кандидатов)` +
      (qstateError ? ` · ⚠ ${qstateError}` : "");
  }
  if (!list) return;
  if (!q.poolTotal) {
    list.innerHTML = `<p class="empty">Пул пуст. В админке Jarvis: «Собрать пул кандидатов» → опубликовать витрину.</p>`;
    return;
  }
  const st = stateTickets();
  const windowHtml = q.windowCards.length
    ? q.windowCards
        .map((c, i) => {
          const t = String(c.ticket);
          return `<button type="button" class="reviews-queue-item" data-ticket="${escapeHtml(t)}">
        <span><span class="pos">${i + 1}.</span><strong>№${escapeHtml(t)}</strong> · ${escapeHtml(c.client_name || "клиент")}
          <br><span class="card-sub">${escapeHtml(c.device || "—")} · ${escapeHtml(c.branch_name || c.location || "—")}</span></span>
        <span class="card-sub">открыть</span>
      </button>`;
        })
        .join("")
    : `<p class="empty">${
        q.deferredCards.length
          ? "Новых квитанций в очереди нет — остались только отложенные (ниже)."
          : "Все кандидаты из пула обработаны. Соберите новый пул в Jarvis и опубликуйте витрину."
      }</p>`;
  const deferredHtml = q.deferredCards.length
    ? `<section class="reviews-deferred">
        <h3>Отложенные · ${q.deferredCards.length}</h3>
        <p class="card-sub">Видны всем менеджерам. Верните в очередь или откройте, когда будете готовы позвонить.</p>
        ${q.deferredCards
          .map((c) => {
            const t = String(c.ticket);
            const who = st[t]?.by ? `отложил(а) ${escapeHtml(st[t].by)}` : "отложено";
            const when = fmtStamp(st[t]?.at);
            return `<div class="reviews-queue-item is-deferred">
              <span><strong>№${escapeHtml(t)}</strong> · ${escapeHtml(c.client_name || "клиент")}
                <br><span class="card-sub">${escapeHtml(c.device || "—")} · ${escapeHtml(c.branch_name || c.location || "—")} · ${who}${when ? ` ${escapeHtml(when)}` : ""}</span></span>
              <span class="reviews-deferred-actions">
                <button type="button" class="reviews-btn" data-undefer="${escapeHtml(t)}">Вернуть в очередь</button>
                <button type="button" class="reviews-btn is-primary" data-ticket="${escapeHtml(t)}">Открыть</button>
              </span>
            </div>`;
          })
          .join("")}
      </section>`
    : "";
  list.innerHTML = windowHtml + deferredHtml;
  list.querySelectorAll("[data-ticket]").forEach((btn) => {
    btn.addEventListener("click", () => openCard(btn.getAttribute("data-ticket")));
  });
  list.querySelectorAll("[data-undefer]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      await setTicketState(btn.getAttribute("data-undefer"), "undefer");
      renderQueue();
    });
  });
}

function closeModal({ keepClaim = false } = {}) {
  document.getElementById("reviews-modal")?.remove();
  // закрыли без результата — карточка снова свободна для коллег
  if (claimedTicket && !keepClaim) setTicketState(claimedTicket, "release").then(() => renderQueue());
  claimedTicket = null;
}

async function openCard(ticket) {
  const card = poolCards().find((c) => String(c.ticket) === String(ticket));
  if (!card) return;
  closeModal();
  let busyNote = "";
  const claim = await setTicketState(ticket, "claim");
  if (claim.ok) claimedTicket = String(ticket);
  else if (claim.error === "already_done") {
    renderQueue();
    alertInQueue(`Квитанцию №${ticket} уже обработал(а) ${claim.conflict?.by || "коллега"}.`);
    return;
  } else if (claim.conflict?.by) {
    busyNote = `<p class="reviews-busy">Сейчас эту карточку открыл(а) <b>${escapeHtml(claim.conflict.by)}</b> — возможно, уже звонит.</p>`;
  }
  const outcomes = DATA?.outcomes || {};
  const feed = Array.isArray(card.live_feed) ? card.live_feed : [];
  const overlay = document.createElement("div");
  overlay.id = "reviews-modal";
  overlay.className = "reviews-modal-overlay";
  overlay.innerHTML = `<div class="reviews-modal">
    <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap">
      <div>
        <p class="card-sub">Сбор отзывов · карточка</p>
        ${busyNote}
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
  overlay.querySelector("[data-defer]")?.addEventListener("click", async () => {
    await setTicketState(ticket, "defer");
    closeModal({ keepClaim: true }); // defer уже заменил «звонит сейчас»
    claimedTicket = null;
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
        // Worker уже отметил «сделано» в общей очереди; здесь — локально и в кэше браузера
        if (QSTATE) {
          QSTATE.tickets[String(ticket)] = { s: "done", by: vitrineLogin() || null, at: new Date().toISOString() };
        }
        const done = lsSet(LS_DONE);
        done.add(String(ticket));
        lsSave(LS_DONE, done);
        const def = lsSet(LS_DEFER);
        def.delete(String(ticket));
        lsSave(LS_DEFER, def);
        claimedTicket = null;
        closeModal();
        // Сразу доливается следующая из пула (окно из 10).
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
    meta.textContent = `Снимок: ${when} · пул ${DATA.cards?.length ?? 0} · окно ${queueSize()}`;
  }
  if (!DATA.branches?.length) {
    DATA.branches = [];
  }
  $("#reviews-start-btn")?.addEventListener("click", () => submitGoogleGate());
  // Каждый заход — сначала гейт рейтинга (не пропускаем по localStorage).
  showGate();
}

boot();
