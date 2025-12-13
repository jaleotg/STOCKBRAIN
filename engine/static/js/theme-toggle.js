// STORAGE KEY
const SB_THEME_KEY = "stockbrain_theme";

// Load saved theme
document.addEventListener("DOMContentLoaded", () => {
    const saved = localStorage.getItem(SB_THEME_KEY);
    if (saved === "dark") {
        document.body.classList.add("sb-dark");
    }
    updateThemeIcon();
});

// Toggle function
function sbToggleTheme() {
    const body = document.body;
    const nowDark = body.classList.toggle("sb-dark");

    if (nowDark) {
        localStorage.setItem(SB_THEME_KEY, "dark");
    } else {
        localStorage.setItem(SB_THEME_KEY, "light");
    }
    updateThemeIcon();
}

// Update theme icon based on current state
function updateThemeIcon() {
    const btn = document.querySelector(".sb-theme-btn");
    if (!btn) return;
    const isDark = document.body.classList.contains("sb-dark");
    btn.textContent = isDark ? "☀️" : "🌙";
}
