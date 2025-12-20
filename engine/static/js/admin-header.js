(function () {
    const DJANGO_THEME_KEY = "theme";

    function getHeaderRoot() {
        return document.querySelector(".sb-admin-header-wrapper");
    }

    function updateThemeIcon(isDark) {
        const btn = document.querySelector(".sb-theme-btn");
        if (!btn) return;
        btn.textContent = isDark ? "☀️" : "🌙";
    }

    function resolveThemePreference() {
        const stored = (() => {
            try {
                return localStorage.getItem(DJANGO_THEME_KEY);
            } catch (e) {
                return null;
            }
        })();
        const datasetMode = document.documentElement.dataset.theme || stored || "auto";
        if (datasetMode === "dark" || datasetMode === "light") {
            return datasetMode;
        }
        const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        return prefersDark ? "dark" : "light";
    }

    window.sbToggleTheme = function () {
        const current = resolveThemePreference();
        const next = current === "dark" ? "light" : "dark";
        document.documentElement.dataset.theme = next;
        const root = getHeaderRoot();
        try {
            localStorage.setItem(DJANGO_THEME_KEY, next);
        } catch (e) {}
        if (root) {
            root.classList.remove("sb-dark", "sb-light");
            root.classList.add(next === "dark" ? "sb-dark" : "sb-light");
        }
        updateThemeIcon(next === "dark");
    };

    function syncHeaderTheme() {
        const mode = resolveThemePreference();
        const root = getHeaderRoot();
        if (root) {
            root.classList.remove("sb-dark", "sb-light");
            root.classList.add(mode === "dark" ? "sb-dark" : "sb-light");
        }
        updateThemeIcon(mode === "dark");
    }

    function updateEndCountdown() {
        const el = document.querySelector(".sb-countdown");
        if (!el) return;
        const endStr = el.dataset.end;
        if (!endStr) return;
        const parts = endStr.split(":");
        if (parts.length < 2) return;
        const hh = parseInt(parts[0], 10);
        const mm = parseInt(parts[1], 10);
        if (Number.isNaN(hh) || Number.isNaN(mm)) return;

        const fmt = new Intl.DateTimeFormat("en-GB", {
            timeZone: "Asia/Kuwait",
            hour12: false,
            hour: "2-digit",
            minute: "2-digit",
        });
        const nowParts = fmt.formatToParts(new Date());
        const curH = parseInt(nowParts.find(p => p.type === "hour")?.value || "0", 10);
        const curM = parseInt(nowParts.find(p => p.type === "minute")?.value || "0", 10);
        const nowMinutes = curH * 60 + curM;
        const endMinutes = hh * 60 + mm;
        let diffMinutes = endMinutes - nowMinutes;
        if (diffMinutes < 0) diffMinutes += 24 * 60;
        const hours = Math.floor(diffMinutes / 60);
        const minutes = diffMinutes % 60;
        el.textContent = `${hours}:${minutes.toString().padStart(2, "0")}`;
    }

    document.addEventListener("DOMContentLoaded", () => {
        syncHeaderTheme();
        updateEndCountdown();
        setInterval(updateEndCountdown, 30000);
        const btn = document.getElementById("sb-mobile-menu-btn");
        const menu = document.getElementById("sb-mobile-menu");
        const closeBtn = document.getElementById("sb-mobile-menu-close");
        if (btn && menu) {
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                menu.classList.add("is-open");
                menu.setAttribute("aria-hidden", "false");
            });
            if (closeBtn) {
                closeBtn.addEventListener("click", (e) => {
                    e.preventDefault();
                    menu.classList.remove("is-open");
                    menu.setAttribute("aria-hidden", "true");
                });
            }
            menu.addEventListener("click", (e) => {
                if (e.target === menu) {
                    menu.classList.remove("is-open");
                    menu.setAttribute("aria-hidden", "true");
                }
            });
            document.addEventListener("keydown", (e) => {
                if (e.key === "Escape") {
                    menu.classList.remove("is-open");
                    menu.setAttribute("aria-hidden", "true");
                }
            });
        }
    });

    window.addEventListener("storage", () => {
        syncHeaderTheme();
    });

    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
        syncHeaderTheme();
    });
})();
