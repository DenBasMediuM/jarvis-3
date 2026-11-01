/* Справка витрины: кнопка рядом с «Предложить улучшение», статьи по доступным разделам,
   «Показать на странице» — переключает вкладку и подсвечивает нужный блок. */
(function () {
  const auth = window.JarvisVitrineAuth;
  const ARTICLES = window.JarvisHelpContent || [];
  if (!auth || window.__jarvisHelp || !ARTICLES.length) return;
  window.__jarvisHelp = true;

  const scriptSrc = document.currentScript?.src || "";
  const ROOT = scriptSrc ? new URL("../", scriptSrc).href : new URL("./", location.href).href;
  const TAB_TO_ARTICLE = {
    upsell: "upsell",
    debt: "debt",
    branch_kpi: "branch_kpi",
    reviews: "reviews",
    reviews_stats: "reviews_stats",
    buffer_quality: "buffer",
  };

  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  function currentPage() {
    const rel = location.href.startsWith(ROOT) ? location.href.slice(ROOT.length) : "";
    return rel.split(/[/?#]/)[0].replace(/\.html$/, "").replace(/^index$/, "");
  }
  function activeTab() {
    return document.querySelector(".mod-tab.is-active, .tab.is-active")?.dataset.tab || "";
  }
  function available() {
    const access = auth.session()?.access || [];
    return ARTICLES.filter((a) => !a.need || auth.hasAccess(access, a.need));
  }
  function defaultArticle(list) {
    const page = currentPage();
    const byTab = page === "vyrobotka" ? TAB_TO_ARTICLE[activeTab()] : null;
    const byPage = { quality: "quality", reviews: "reviews" }[page];
    const want = byTab || byPage || "start";
    return list.find((a) => a.id === want) || list[0];
  }

  // ---------- кнопка в общем доке справа внизу ----------
  function dock() {
    let d = document.querySelector(".jv-dock");
    if (!d) {
      d = document.createElement("div");
      d.className = "jv-dock";
      document.body.appendChild(d);
    }
    return d;
  }
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "hp-fab";
  btn.title = "Справка: как пользоваться витриной";
  btn.innerHTML = `<span class="hp-q" aria-hidden="true">?</span><span class="hp-fab-label">Справка</span>`;
  dock().prepend(btn);

  const overlay = document.createElement("div");
  overlay.className = "hp-overlay";
  overlay.hidden = true;
  const modal = document.createElement("div");
  modal.className = "hp-modal";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-label", "Справка");
  modal.hidden = true;
  document.body.append(overlay, modal);

  const state = { open: false, id: null, q: "" };

  btn.addEventListener("click", () => open());
  overlay.addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.open) close();
  });

  function open(id) {
    const list = available();
    state.id = id || state.id || defaultArticle(list)?.id;
    if (!list.some((a) => a.id === state.id)) state.id = defaultArticle(list)?.id;
    state.open = true;
    overlay.hidden = false;
    modal.hidden = false;
    document.body.classList.add("hp-lock");
    render();
  }
  function close() {
    state.open = false;
    overlay.hidden = true;
    modal.hidden = true;
    document.body.classList.remove("hp-lock");
  }

  function matches(a, q) {
    if (!q) return true;
    const text = `${a.title} ${a.summary} ${a.html}`.replace(/<[^>]+>/g, " ").toLowerCase();
    return q
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean)
      .every((w) => text.includes(w));
  }

  function render() {
    const list = available();
    const shown = list.filter((a) => matches(a, state.q));
    const art = list.find((a) => a.id === state.id) || shown[0] || list[0];
    const groups = [];
    shown.forEach((a) => {
      let g = groups.find((x) => x.name === a.group);
      if (!g) groups.push((g = { name: a.group, items: [] }));
      g.items.push(a);
    });
    const nav = groups
      .map(
        (g) => `<div class="hp-group"><span>${esc(g.name)}</span>${g.items
          .map(
            (a) =>
              `<button type="button" data-hp-go="${a.id}" class="${a.id === art?.id ? "is-active" : ""}">${esc(a.title)}</button>`,
          )
          .join("")}</div>`,
      )
      .join("");
    const shows = (art?.show || [])
      .map(
        (s, i) =>
          `<button type="button" class="hp-show" data-hp-show="${i}"><span aria-hidden="true">◎</span> ${esc(s.label)}</button>`,
      )
      .join("");
    modal.innerHTML = `
      <header class="hp-head">
        <div><span class="hp-kicker">Справка</span><h2>Как пользоваться витриной</h2></div>
        <button type="button" class="hp-close" aria-label="Закрыть">×</button>
      </header>
      <div class="hp-body">
        <nav class="hp-nav">
          <input type="search" class="hp-search" placeholder="Поиск по справке…" value="${esc(state.q)}">
          ${nav || '<p class="hp-empty">Ничего не найдено</p>'}
        </nav>
        <article class="hp-article">
          ${
            art
              ? `<h3>${esc(art.title)}</h3><p class="hp-summary">${esc(art.summary)}</p>
                 ${shows ? `<div class="hp-shows"><span>Показать на странице:</span>${shows}</div>` : ""}
                 <div class="hp-content">${art.html}</div>`
              : ""
          }
        </article>
      </div>`;
    modal.querySelector(".hp-close").addEventListener("click", close);
    const search = modal.querySelector(".hp-search");
    search.addEventListener("input", () => {
      state.q = search.value;
      const pos = search.selectionStart;
      const first = available().find((a) => matches(a, state.q));
      if (first && !matches(available().find((a) => a.id === state.id) || {}, state.q)) state.id = first.id;
      render();
      const s2 = modal.querySelector(".hp-search");
      s2.focus();
      s2.setSelectionRange(pos, pos);
    });
    modal.querySelectorAll("[data-hp-go]").forEach((b) =>
      b.addEventListener("click", () => {
        state.id = b.dataset.hpGo;
        render();
        modal.querySelector(".hp-article").scrollTop = 0;
      }),
    );
    modal.querySelectorAll("[data-hp-show]").forEach((b) =>
      b.addEventListener("click", () => showOnPage(art, Number(b.dataset.hpShow))),
    );
  }

  // ---------- «Показать на странице» ----------
  function showOnPage(art, idx) {
    const target = art?.show?.[idx];
    if (!target) return;
    const page = target.page ?? currentPage();
    if (page !== currentPage()) {
      location.href = `${ROOT}${page ? `${page}/` : ""}#help-show=${encodeURIComponent(art.id)}:${idx}`;
      return;
    }
    close();
    spotlight(target);
  }

  function spotlight(target) {
    if (target.tab) {
      const tabBtn = document.querySelector(`.mod-tab[data-tab="${target.tab}"], .tab[data-tab="${target.tab}"]`);
      if (tabBtn && !tabBtn.classList.contains("is-active")) tabBtn.click();
    }
    setTimeout(() => {
      const el = document.querySelector(target.selector);
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.remove("hp-spot");
      void el.offsetWidth;
      el.classList.add("hp-spot");
      setTimeout(() => el.classList.remove("hp-spot"), 3600);
    }, target.tab ? 450 : 50);
  }

  // переход с другой страницы: #help-show=<id>:<idx>
  const m = location.hash.match(/^#help-show=([^:]+):(\d+)$/);
  if (m) {
    history.replaceState(null, "", location.pathname + location.search);
    const art = ARTICLES.find((a) => a.id === decodeURIComponent(m[1]));
    const target = art?.show?.[Number(m[2])];
    if (target) setTimeout(() => spotlight(target), 900); // дать странице отрисовать данные
  }
})();
