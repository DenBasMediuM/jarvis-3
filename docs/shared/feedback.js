/* Модуль «Улучшения» на витрине: кнопка, диалог с ИИ, «Мои заявки». Требует shared/auth.js. */
(function () {
  const auth = window.JarvisVitrineAuth;
  if (!auth || window.__jarvisFeedback) return;
  window.__jarvisFeedback = true;

  const API = auth.feedbackUrl();
  const CONV_KEY = "jarvis.feedback.conv";
  const SEEN_KEY = "jarvis.feedback.seen";

  const TYPES = {
    feature: "Новая функция",
    improvement: "Улучшение",
    bug: "Ошибка",
    data: "Данные / расчёты",
    ux: "Удобство / интерфейс",
    other: "Другое",
  };
  const STATUS = {
    new: "На рассмотрении",
    approved: "Одобрено",
    in_progress: "В работе",
    done: "Готово",
    rejected: "Отклонено",
  };

  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  const nl2br = (s) => esc(s).replace(/\n/g, "<br>");

  function store(kind) {
    try {
      return kind === "local" ? window.localStorage : window.sessionStorage;
    } catch {
      return null;
    }
  }
  function readJson(kind, key, fallback) {
    try {
      const raw = store(kind)?.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch {
      return fallback;
    }
  }
  function writeJson(kind, key, value) {
    try {
      if (value == null) store(kind)?.removeItem(key);
      else store(kind)?.setItem(key, JSON.stringify(value));
    } catch {
      /* ignore */
    }
  }

  const state = {
    open: false,
    tab: "new",
    busy: false,
    error: "",
    conv: readJson("session", CONV_KEY, null), // {id, history:[{role,text}], reply, rounds, max_rounds}
    submitted: null,
    mine: null,
  };

  function login() {
    return auth.session()?.login || "";
  }
  function seenMap() {
    return readJson("local", `${SEEN_KEY}.${login()}`, {});
  }
  function markSeen(items) {
    const m = seenMap();
    for (const it of items || []) m[it.id] = it.updated_at;
    writeJson("local", `${SEEN_KEY}.${login()}`, m);
  }
  function unseenCount(items) {
    const m = seenMap();
    return (items || []).filter((it) => it.status !== "new" && m[it.id] !== it.updated_at).length;
  }

  async function api(path, { method = "GET", body } = {}) {
    const token = auth.feedbackToken();
    if (!token) throw Object.assign(new Error("need_auth"), { needAuth: true });
    const res = await fetch(`${API}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) {
      auth.setFeedbackToken(null);
      throw Object.assign(new Error(data.message || "Сессия истекла"), { needAuth: true });
    }
    if (!res.ok || data.ok === false) throw new Error(data.message || `Ошибка ${res.status}`);
    return data;
  }

  function pageContext() {
    const parts = location.pathname.split("/").filter(Boolean);
    const page = parts.length > 1 ? parts[parts.length - 1] : "главная";
    const tab = document.querySelector(".mod-tab.is-active")?.textContent?.trim() || "";
    return { page, tab, title: document.title };
  }

  // ---------- DOM ----------
  const ICON = `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M12 2a7 7 0 0 0-4 12.74V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.26A7 7 0 0 0 12 2Zm2 11.6V16h-4v-2.4l-.43-.3a5 5 0 1 1 4.86 0l-.43.3ZM9 20h6v2H9z"/></svg>`;

  const fab = document.createElement("button");
  fab.type = "button";
  fab.className = "fb-fab";
  fab.innerHTML = `${ICON}<span class="fb-fab-label">Предложить улучшение</span><span class="fb-fab-badge" hidden></span>`;
  fab.title = "Улучшения: пожелания, замечания, ошибки";

  const overlay = document.createElement("div");
  overlay.className = "fb-overlay";
  overlay.hidden = true;

  const panel = document.createElement("aside");
  panel.className = "fb-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Улучшения");
  panel.hidden = true;

  document.body.append(fab, overlay, panel);

  fab.addEventListener("click", () => toggle(true));
  overlay.addEventListener("click", () => toggle(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.open) toggle(false);
  });

  function toggle(open) {
    state.open = open;
    panel.hidden = !open;
    overlay.hidden = !open;
    document.body.classList.toggle("fb-lock", open);
    if (open) {
      render();
      if (state.tab === "mine") loadMine();
    }
  }

  function setBadge(n) {
    const b = fab.querySelector(".fb-fab-badge");
    b.hidden = !n;
    b.textContent = n > 9 ? "9+" : String(n || "");
  }

  // ---------- render ----------
  function render() {
    const needAuth = !auth.feedbackToken();
    panel.innerHTML = `
      <header class="fb-head">
        <div>
          <span class="fb-kicker">Улучшения</span>
          <h2>Пожелания и замечания</h2>
        </div>
        <button type="button" class="fb-close" aria-label="Закрыть">×</button>
      </header>
      <nav class="fb-tabs">
        <button type="button" data-fb-tab="new" class="${state.tab === "new" ? "is-active" : ""}">Новая заявка</button>
        <button type="button" data-fb-tab="mine" class="${state.tab === "mine" ? "is-active" : ""}">Мои заявки</button>
      </nav>
      <div class="fb-body">${needAuth ? renderAuth() : state.tab === "new" ? renderNew() : renderMine()}</div>`;
    panel.querySelector(".fb-close").addEventListener("click", () => toggle(false));
    panel.querySelectorAll("[data-fb-tab]").forEach((b) =>
      b.addEventListener("click", () => {
        state.tab = b.dataset.fbTab;
        state.error = "";
        render();
        if (state.tab === "mine" && auth.feedbackToken()) loadMine();
      }),
    );
    bind();
  }

  function renderError() {
    return state.error ? `<p class="fb-error">${esc(state.error)}</p>` : "";
  }

  function renderAuth() {
    return `
      <form class="fb-auth" data-fb="auth">
        <p>Для отправки заявок подтвердите вход — введите пароль от витрины ещё раз.</p>
        <label>Логин<input value="${esc(login())}" disabled></label>
        <label>Пароль<input name="password" type="password" autocomplete="current-password" required></label>
        ${renderError()}
        <button type="submit" class="fb-btn fb-btn-primary" ${state.busy ? "disabled" : ""}>${state.busy ? "Проверка…" : "Подтвердить"}</button>
      </form>`;
  }

  function renderNew() {
    if (state.submitted) {
      return `
        <div class="fb-done">
          <strong>${state.submitted.vote ? "Вы поддержали заявку" : "Заявка отправлена"} #${esc(state.submitted.id)}</strong>
          <p>Администратор рассмотрит её. Статус и ответ появятся во вкладке «Мои заявки».</p>
          <div class="fb-actions">
            <button type="button" class="fb-btn" data-fb="to-mine">Мои заявки</button>
            <button type="button" class="fb-btn fb-btn-primary" data-fb="restart">Новая заявка</button>
          </div>
        </div>`;
    }
    const c = state.conv;
    if (!c) {
      return `
        <p class="fb-lead">Опишите своими словами, что стоит изменить, добавить или исправить в витрине.
        ИИ при необходимости задаст пару уточняющих вопросов и оформит заявку — вы её проверите перед отправкой.</p>
        <form data-fb="start" class="fb-compose">
          <textarea name="message" rows="6" maxlength="2000" required
            placeholder="Например: в Дебиторке не хватает фильтра по филиалу — приходится листать всю таблицу"></textarea>
          ${renderError()}
          <button type="submit" class="fb-btn fb-btn-primary" ${state.busy ? "disabled" : ""}>${state.busy ? "ИИ думает…" : "Отправить ИИ"}</button>
          <p class="fb-hint">Раздел, где вы сейчас находитесь, подставится автоматически.</p>
        </form>`;
    }
    const r = c.reply || {};
    const log = (c.history || [])
      .map(
        (m) =>
          `<div class="fb-msg fb-msg-${m.role === "user" ? "user" : "ai"}">${nl2br(m.text)}</div>`,
      )
      .join("");
    const rounds = c.max_rounds ? `<span class="fb-rounds">Уточнения: ${c.rounds} из ${c.max_rounds}</span>` : "";
    let tail = "";
    if (r.action === "draft" && r.draft) tail = renderDraft(r);
    else
      tail = `
        <form data-fb="reply" class="fb-compose">
          <textarea name="message" rows="3" maxlength="2000" required placeholder="Ваш ответ…"></textarea>
          ${renderError()}
          <div class="fb-actions">
            <button type="button" class="fb-btn fb-btn-ghost" data-fb="restart">Начать заново</button>
            <button type="submit" class="fb-btn fb-btn-primary" ${state.busy ? "disabled" : ""}>${state.busy ? "ИИ думает…" : "Ответить"}</button>
          </div>
        </form>`;
    return `<div class="fb-log">${log}</div>${rounds}${tail}`;
  }

  function renderDraft(r) {
    const d = r.draft;
    const dup = r.duplicate_of
      ? `<div class="fb-dup">
           <p>Похоже, такая заявка уже есть: <strong>#${esc(r.duplicate_of)}</strong>${r.duplicate_reason ? ` — ${esc(r.duplicate_reason)}` : ""}.</p>
           <button type="button" class="fb-btn" data-fb="vote" data-id="${esc(r.duplicate_of)}">Поддержать #${esc(r.duplicate_of)} вместо новой</button>
         </div>`
      : "";
    const typeOpts = Object.entries(TYPES)
      .map(([k, v]) => `<option value="${k}" ${k === d.type ? "selected" : ""}>${v}</option>`)
      .join("");
    return `
      <form data-fb="submit" class="fb-draft">
        <h3>Ваша заявка</h3>
        <p class="fb-hint">Проверьте формулировки — можно поправить любое поле.</p>
        ${dup}
        <label>Заголовок<input name="title" maxlength="140" value="${esc(d.title)}" required></label>
        <div class="fb-row">
          <label>Тип<select name="type">${typeOpts}</select></label>
          <label>Раздел<input name="area" maxlength="120" value="${esc(d.area)}"></label>
        </div>
        <label>Что сейчас не так<textarea name="problem" rows="3" maxlength="1500">${esc(d.problem)}</textarea></label>
        <label>Что изменить<textarea name="proposal" rows="4" maxlength="2000" required>${esc(d.proposal)}</textarea></label>
        <label>Польза<textarea name="benefit" rows="2" maxlength="1000">${esc(d.benefit)}</textarea></label>
        <label>Как понять, что готово <span class="fb-hint">(по строке)</span>
          <textarea name="acceptance" rows="3">${esc((d.acceptance || []).join("\n"))}</textarea></label>
        ${renderError()}
        <div class="fb-actions">
          <button type="button" class="fb-btn fb-btn-ghost" data-fb="more">Уточнить ещё</button>
          <button type="submit" class="fb-btn fb-btn-primary" ${state.busy ? "disabled" : ""}>${state.busy ? "Отправка…" : "Отправить заявку"}</button>
        </div>
      </form>
      <form data-fb="reply" class="fb-compose" hidden>
        <textarea name="message" rows="3" maxlength="2000" placeholder="Что поправить или добавить?"></textarea>
        <button type="submit" class="fb-btn">Отправить ИИ</button>
      </form>`;
  }

  function renderMine() {
    if (state.mine == null) return `<p class="fb-lead">Загрузка…</p>${renderError()}`;
    if (!state.mine.length) {
      return `<p class="fb-lead">Заявок пока нет. Во вкладке «Новая заявка» можно предложить первое улучшение.</p>${renderError()}`;
    }
    const seen = seenMap();
    return (
      renderError() +
      state.mine
        .map((it) => {
          const fresh = it.status !== "new" && seen[it.id] !== it.updated_at;
          const date = String(it.created_at || "").slice(0, 10).split("-").reverse().join(".");
          return `
          <article class="fb-card ${fresh ? "is-fresh" : ""}">
            <div class="fb-card-top">
              <span class="fb-id">#${esc(it.id)}</span>
              <span class="fb-status fb-st-${esc(it.status)}">${esc(STATUS[it.status] || it.status)}</span>
            </div>
            <h4>${esc(it.title)}</h4>
            <p class="fb-meta">${esc(TYPES[it.type] || it.type)}${it.area ? ` · ${esc(it.area)}` : ""} · ${esc(date)}${it.votes > 1 ? ` · +${it.votes - 1}` : ""}${it.supported ? " · вы поддержали" : ""}</p>
            ${it.admin_comment ? `<div class="fb-answer"><span>Ответ администратора</span>${nl2br(it.admin_comment)}</div>` : ""}
            <details><summary>Подробнее</summary>
              ${it.problem ? `<p><b>Что не так:</b> ${nl2br(it.problem)}</p>` : ""}
              <p><b>Что изменить:</b> ${nl2br(it.proposal)}</p>
              ${it.benefit ? `<p><b>Польза:</b> ${nl2br(it.benefit)}</p>` : ""}
            </details>
          </article>`;
        })
        .join("")
    );
  }

  // ---------- actions ----------
  function saveConv() {
    writeJson("session", CONV_KEY, state.conv);
  }

  function applyConversation(conv, userText) {
    const prev = state.conv?.id === conv.id ? state.conv.history || [] : [];
    const r = conv.reply || {};
    const aiText = [r.message, ...(r.questions || []).map((q, i) => `${i + 1}. ${q}`)].filter(Boolean).join("\n");
    state.conv = {
      id: conv.id,
      rounds: conv.rounds,
      max_rounds: conv.max_rounds,
      reply: r,
      history: [...prev, { role: "user", text: userText }, { role: "ai", text: aiText }],
    };
    saveConv();
  }

  async function run(fn) {
    if (state.busy) return;
    state.busy = true;
    state.error = "";
    render();
    try {
      await fn();
    } catch (err) {
      state.error = err.needAuth ? "" : err.message || String(err);
    } finally {
      state.busy = false;
      render();
    }
  }

  function bind() {
    const q = (sel) => panel.querySelector(sel);

    q('[data-fb="auth"]')?.addEventListener("submit", (e) => {
      e.preventDefault();
      const pw = String(e.target.elements.namedItem("password")?.value || "");
      run(async () => {
        await auth.fetchFeedbackToken(login(), pw);
        if (!auth.feedbackToken()) throw new Error("Не удалось подтвердить вход");
      });
    });

    q('[data-fb="start"]')?.addEventListener("submit", (e) => {
      e.preventDefault();
      const text = String(e.target.elements.namedItem("message")?.value || "").trim();
      if (!text) return;
      run(async () => {
        const data = await api("/conversations", {
          method: "POST",
          body: { message: text, context: pageContext() },
        });
        state.conv = null;
        applyConversation(data.conversation, text);
      });
    });

    panel.querySelectorAll('[data-fb="reply"]').forEach((form) =>
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        const text = String(e.target.elements.namedItem("message")?.value || "").trim();
        if (!text || !state.conv) return;
        run(async () => {
          const data = await api(`/conversations/${state.conv.id}/messages`, {
            method: "POST",
            body: { message: text },
          });
          applyConversation(data.conversation, text);
        });
      }),
    );

    q('[data-fb="more"]')?.addEventListener("click", () => {
      const f = panel.querySelector('form[data-fb="reply"][hidden]');
      if (f) {
        f.hidden = false;
        f.querySelector("textarea")?.focus();
      }
    });

    q('[data-fb="submit"]')?.addEventListener("submit", (e) => {
      e.preventDefault();
      const v = (name) => String(e.target.elements.namedItem(name)?.value || "");
      const draft = {
        type: v("type"),
        title: v("title").trim(),
        area: v("area").trim(),
        problem: v("problem").trim(),
        proposal: v("proposal").trim(),
        benefit: v("benefit").trim(),
        acceptance: v("acceptance")
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
      };
      run(async () => {
        const data = await api(`/conversations/${state.conv.id}/submit`, { method: "POST", body: { draft } });
        state.submitted = { id: data.id };
        state.conv = null;
        state.mine = null;
        saveConv();
      });
    });

    q('[data-fb="vote"]')?.addEventListener("click", (e) => {
      const id = e.currentTarget.dataset.id;
      run(async () => {
        await api(`/requests/${id}/vote`, {
          method: "POST",
          body: {
            conversation_id: state.conv?.id,
            comment: state.conv?.history?.find((m) => m.role === "user")?.text || "",
          },
        });
        state.submitted = { id, vote: true };
        state.conv = null;
        state.mine = null;
        saveConv();
      });
    });

    q('[data-fb="restart"]')?.addEventListener("click", () => {
      state.conv = null;
      state.submitted = null;
      state.error = "";
      saveConv();
      render();
    });

    q('[data-fb="to-mine"]')?.addEventListener("click", () => {
      state.tab = "mine";
      state.submitted = null;
      render();
      loadMine();
    });
  }

  async function loadMine({ silent = false } = {}) {
    try {
      const data = await api("/requests/mine");
      state.mine = data.items || [];
      if (state.open && state.tab === "mine") {
        render();
        markSeen(state.mine);
        setBadge(0);
      } else {
        setBadge(unseenCount(state.mine));
      }
    } catch (err) {
      if (!silent) {
        state.error = err.needAuth ? "" : err.message || String(err);
        state.mine = state.mine || [];
        if (state.open) render();
      }
    }
  }

  // при загрузке — тихо проверить обновления статусов
  if (auth.feedbackToken()) loadMine({ silent: true });
})();
