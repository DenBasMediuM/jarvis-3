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

/** Окно из QUEUE_SIZE: активные + при нехватке — отложенные. */
function visibleQueue() {
  const done = loadDone();
  const deferred = loadDeferred();
  const pool = poolCards();
  const active = pool.filter((c) => {
    const t = String(c.ticket);
    return !done.has(t) && !deferred.has(t);
  });
  const deferredCards = pool.filter((c) => {
    const t = String(c.ticket);
    return deferred.has(t) && !done.has(t);
  });
  const size = queueSize();
  const windowCards = [...active, ...deferredCards].slice(0, size);
  return {
    windowCards,
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
      ` · снимок ${DATA?.batch?.day || "—"} (${q.poolTotal} кандидатов)`;
  }
  if (!list) return;
  if (!q.poolTotal) {
    list.innerHTML = `<p class="empty">Пул пуст. В админке Jarvis: «Собрать пул кандидатов» → опубликовать витрину.</p>`;
    return;
  }
  if (!q.windowCards.length) {
    list.innerHTML = `<p class="empty">Все кандидаты из пула обработаны. Соберите новый пул в Jarvis и опубликуйте витрину.</p>`;
    return;
  }
  const deferred = loadDeferred();
  list.innerHTML = q.windowCards
    .map((c, i) => {
      const t = String(c.ticket);
      const isDef = deferred.has(t);
      return `<button type="button" class="reviews-queue-item${isDef ? " is-deferred" : ""}" data-ticket="${escapeHtml(t)}">
        <span><span class="pos">${i + 1}.</span><strong>№${escapeHtml(t)}</strong> · ${escapeHtml(c.client_name || "клиент")}
          <br><span class="card-sub">${escapeHtml(c.device || "—")} · ${escapeHtml(c.branch_name || c.location || "—")}</span></span>
        <span class="card-sub">${isDef ? "отложено" : "открыть"}</span>
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
  const card = poolCards().find((c) => String(c.ticket) === String(ticket));
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
