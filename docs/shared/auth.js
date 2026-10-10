/* Вход на витрину Pages: PBKDF2 по docs/auth/users.json */
(function () {
  const SESSION_KEY = "jarvis.vitrine.session";
  // Зафиксировать базу при загрузке скрипта: currentScript пуст в DOMContentLoaded.
  const scriptBase = (() => {
    try {
      const script = document.currentScript;
      if (script?.src) return script.src;
    } catch {
      /* ignore */
    }
    const el = document.querySelector('script[src*="shared/auth.js"]');
    return el?.src || "";
  })();
  // auth.js лежит в shared/ → users.json в auth/, login.html рядом с docs/
  const usersUrlFromHere = scriptBase
    ? new URL("../auth/users.json", scriptBase).href
    : "./auth/users.json";
  const loginUrlFromHere = scriptBase
    ? new URL("../login.html", scriptBase).href
    : "./login.html";

  function session() {
    try {
      const raw = sessionStorage.getItem(SESSION_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  function setSession(data) {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(data));
  }

  function clearSession() {
    sessionStorage.removeItem(SESSION_KEY);
  }

  function hasAccess(accessList, need) {
    if (!need) return true;
    const list = accessList || [];
    if (list.includes(need)) return true;
    // родительский блок, если есть любой подблок
    if (need === "processes") {
      return list.some((a) => a === "processes" || String(a).startsWith("processes."));
    }
    return false;
  }

  function canSeeNav(accessList, id) {
    if (id === "quality") return hasAccess(accessList, "quality");
    if (id === "processes") return hasAccess(accessList, "processes");
    if (id === "processes.upsell") return hasAccess(accessList, "processes.upsell");
    if (id === "processes.debt") return hasAccess(accessList, "processes.debt");
    if (id === "finance") return hasAccess(accessList, "finance");
    return false;
  }

  async function pbkdf2Hex(password, saltHex, iters) {
    const enc = new TextEncoder();
    const keyMaterial = await crypto.subtle.importKey(
      "raw",
      enc.encode(password),
      "PBKDF2",
      false,
      ["deriveBits"],
    );
    const salt = new Uint8Array(saltHex.match(/.{1,2}/g).map((b) => parseInt(b, 16)));
    const bits = await crypto.subtle.deriveBits(
      { name: "PBKDF2", salt, iterations: iters || 200000, hash: "SHA-256" },
      keyMaterial,
      256,
    );
    return [...new Uint8Array(bits)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  async function loadUsers() {
    const url = `${usersUrlFromHere}${usersUrlFromHere.includes("?") ? "&" : "?"}t=${Date.now()}`;
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`users.json: ${res.status}`);
    return res.json();
  }

  async function login(loginName, password) {
    const data = await loadUsers();
    const users = data.users || [];
    if (!users.length) {
      throw new Error("Пользователи витрины не настроены. Создайте их в Jarvis → Пользователи витрины.");
    }
    const user = users.find(
      (u) => String(u.login || "").toLowerCase() === String(loginName || "").trim().toLowerCase(),
    );
    if (!user) throw new Error("Неверный логин или пароль");
    const hash = await pbkdf2Hex(password, user.salt, user.iters || data.pbkdf2_iterations || 200000);
    if (hash !== user.hash) throw new Error("Неверный логин или пароль");
    const sess = {
      login: user.login,
      access: user.access || [],
      at: Date.now(),
    };
    setSession(sess);
    return sess;
  }

  function loginPath() {
    return loginUrlFromHere;
  }

  function requireAuth(need) {
    const s = session();
    if (!s?.login) {
      const next = encodeURIComponent(location.pathname + location.search + location.hash);
      const sep = loginPath().includes("?") ? "&" : "?";
      location.href = `${loginPath()}${sep}next=${next}`;
      return null;
    }
    if (need && !hasAccess(s.access, need)) {
      const sep = loginPath().includes("?") ? "&" : "?";
      location.href = `${loginPath()}${sep}denied=1`;
      return null;
    }
    return s;
  }

  function applyShellNav(active) {
    const s = session();
    const mods = document.querySelector(".shell-mods");
    if (!mods || !s) return;
    const access = s.access || [];
    const items = [
      { id: "quality", href: "../quality/", label: "Качество" },
      {
        id: "processes",
        href: "../vyrobotka/",
        label: "Процессы",
        children: [
          { id: "processes.upsell", href: "../vyrobotka/?tab=upsell", label: "Досогласования" },
          { id: "processes.debt", href: "../vyrobotka/?tab=debt", label: "Дебиторка" },
        ],
      },
      { id: "finance", href: "../finance/", label: "Финансы" },
    ];
    // resolve relative to current page depth
    const base = document.querySelector(".shell-brand")?.getAttribute("href") || "../";
    const root = base.endsWith("/") ? base : `${base}/`;

    const html = items
      .filter((it) => canSeeNav(access, it.id))
      .map((it) => {
        const href = it.href.replace("../", root);
        const isActive =
          active === it.id ||
          (it.id === "processes" && String(active || "").startsWith("processes"));
        if (it.children) {
          const kids = it.children
            .filter((c) => canSeeNav(access, c.id))
            .map((c) => {
              const ch = c.href.replace("../", root);
              const on = active === c.id;
              return `<a class="shell-submod ${on ? "is-active" : ""}" href="${ch}">${c.label}</a>`;
            })
            .join("");
          return `<div class="shell-mod-group">
            <a class="shell-mod ${isActive ? "is-active" : ""}" href="${href}">${it.label}</a>
            <div class="shell-submods">${kids}</div>
          </div>`;
        }
        return `<a class="shell-mod ${isActive ? "is-active" : ""}" href="${href}">${it.label}</a>`;
      })
      .join("");

    mods.innerHTML =
      html +
      `<div class="shell-user">
        <span class="shell-user-name">${escapeHtml(s.login)}</span>
        <button type="button" class="shell-logout" id="jarvis-vitrine-logout">Выйти</button>
      </div>`;

    document.getElementById("jarvis-vitrine-logout")?.addEventListener("click", () => {
      clearSession();
      location.href = loginPath();
    });
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function filterProcessesTabs(access) {
    document.querySelectorAll(".mod-tab[data-tab]").forEach((btn) => {
      const tab = btn.getAttribute("data-tab");
      const need = tab === "debt" ? "processes.debt" : "processes.upsell";
      const ok = hasAccess(access, need);
      btn.hidden = !ok;
      if (!ok && btn.classList.contains("is-active")) btn.classList.remove("is-active");
    });
    const visible = [...document.querySelectorAll(".mod-tab[data-tab]:not([hidden])")];
    if (visible.length && !visible.some((b) => b.classList.contains("is-active"))) {
      visible[0].click();
    }
  }

  window.JarvisVitrineAuth = {
    session,
    login,
    logout: clearSession,
    requireAuth,
    applyShellNav,
    hasAccess,
    canSeeNav,
    filterProcessesTabs,
    loadUsers,
  };
})();
