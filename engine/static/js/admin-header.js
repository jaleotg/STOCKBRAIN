(function () {
    const THEME_KEY = "stockbrain_theme";

    function setThemeClasses(isDark) {
        const root = document.documentElement;
        const body = document.body;
        if (!root) return;
        root.classList.remove(isDark ? "sb-light" : "sb-dark");
        root.classList.add(isDark ? "sb-dark" : "sb-light");
        if (body) {
            body.classList.remove(isDark ? "sb-light" : "sb-dark");
            body.classList.add(isDark ? "sb-dark" : "sb-light");
        }
    }

    function updateThemeIcon() {
        const btn = document.querySelector(".sb-theme-btn");
        if (!btn) return;
        const isDark = document.documentElement.classList.contains("sb-dark");
        btn.textContent = isDark ? "☀️" : "🌙";
    }

    window.sbToggleTheme = function () {
        const root = document.documentElement;
        if (!root) return;
        const nowDark = !root.classList.contains("sb-dark");
        setThemeClasses(nowDark);
        try {
            localStorage.setItem(THEME_KEY, nowDark ? "dark" : "light");
        } catch (e) {}
        updateThemeIcon();
    };

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
        updateThemeIcon();
        updateEndCountdown();
        setInterval(updateEndCountdown, 30000);
    });
})();
