// STORAGE KEY
const SB_THEME_KEY = "stockbrain_theme";

// Load saved theme
document.addEventListener("DOMContentLoaded", () => {
    const saved = localStorage.getItem(SB_THEME_KEY);
    if (saved === "dark") {
        document.body.classList.add("sb-dark");
    }
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
}
