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
                return (
                    localStorage.getItem(DJANGO_THEME_KEY) ||
                    localStorage.getItem("stockbrain_theme")
                );
            } catch (e) {
                return null;
            }
        })();
        const datasetMode = document.documentElement.dataset.theme || "";
        if (datasetMode === "dark" || datasetMode === "light") {
            return datasetMode;
        }
        if (stored === "dark" || stored === "light") {
            return stored;
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

    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(";").shift();
    }

    function applyThemePreference(preferDark) {
        const mode = preferDark ? "dark" : "light";
        document.documentElement.dataset.theme = mode;
        const root = getHeaderRoot();
        if (root) {
            root.classList.remove("sb-dark", "sb-light");
            root.classList.add(mode === "dark" ? "sb-dark" : "sb-light");
        }
        updateThemeIcon(mode === "dark");
        try {
            localStorage.setItem(DJANGO_THEME_KEY, mode);
            localStorage.setItem("stockbrain_theme", mode);
        } catch (e) {}
    }

    function getGtfoOverrideEnabled() {
        try {
            const raw = localStorage.getItem("sb_gtfo_override_enabled");
            if (raw === null) return true;
            return ["1", "true", "on", "yes"].includes(String(raw).toLowerCase());
        } catch (e) {
            return true;
        }
    }

    function applyGtfoOverrideEnabled(enabled) {
        if (enabled) return;
        try {
            localStorage.removeItem("sb_gtfo_override");
        } catch (e) {}
    }

    function sbInitUserProfileModal() {
        const trigger = document.getElementById("sb-user-edit-trigger");
        const modal = document.getElementById("sb-user-modal");
        if (!trigger || !modal) return;
        if (trigger.dataset.sbBound === "1") return;
        trigger.dataset.sbBound = "1";

        const dialog = modal.querySelector(".sb-modal-dialog");
        const closeBtn = modal.querySelector("#sb-user-close");
        const cancelBtn = modal.querySelector("#sb-user-cancel");
        const form = modal.querySelector("#sb-user-form");
        const errBox = modal.querySelector("#sb-user-error");

        const firstEl = modal.querySelector("#sb-user-first");
        const lastEl = modal.querySelector("#sb-user-last");
        const groupsEl = modal.querySelector("#sb-user-groups");
        const emailEl = modal.querySelector("#sb-user-email");
        const prefEl = modal.querySelector("#sb-user-preferred");
        const oldPwEl = modal.querySelector("#sb-user-oldpw");
        const newPwEl = modal.querySelector("#sb-user-newpw");
        const newPw2El = modal.querySelector("#sb-user-newpw2");
        const lastLoginEl = modal.querySelector("#sb-user-last-login");
        const currentLoginEl = modal.querySelector("#sb-user-current-login");

        let initialEmail = "";
        let isOpen = false;

        function showError(msg) {
            if (!errBox) return;
            errBox.textContent = msg || "";
            errBox.style.display = msg ? "block" : "none";
        }

        function formatLoginValue(value, displayValue) {
            if (displayValue) return displayValue;
            if (!value) return "None";
            const parsed = new Date(value);
            if (!Number.isNaN(parsed.getTime())) {
                return parsed.toLocaleString();
            }
            return value;
        }

        function fillUser(data) {
            const u = (data && data.user) || {};
            if (firstEl) firstEl.value = u.first_name || "";
            if (lastEl) lastEl.value = u.last_name || "";
            if (emailEl) emailEl.value = u.email || "";
            if (prefEl) prefEl.value = u.preferred_name || "";
            if (groupsEl) {
                const groups = Array.isArray(u.groups) ? u.groups : [];
                groupsEl.value = groups.length ? groups.join(", ") : "None";
            }
            if (lastLoginEl) {
                lastLoginEl.value = formatLoginValue(u.previous_login, u.previous_login_display);
            }
            if (currentLoginEl) {
                currentLoginEl.value = formatLoginValue(null, u.current_login_display);
            }
            initialEmail = emailEl ? (emailEl.value || "") : "";
            if (emailEl) emailEl.focus();
        }

        function openModal() {
            showError("");
            modal.style.display = "flex";
            isOpen = true;
            fetch("/api/user/profile/")
                .then(r => r.json())
                .then(data => {
                    if (!data.ok) {
                        showError(data.error || "Failed to load profile.");
                        return;
                    }
                    fillUser(data);
                })
                .catch(err => {
                    console.error("Profile load error", err);
                    showError("Failed to load profile.");
                });
        }

        function closeModal() {
            modal.style.display = "none";
            isOpen = false;
        }

        function handleOutside(e) {
            if (!isOpen || !dialog) return;
            if (!dialog.contains(e.target)) {
                closeModal();
            }
        }

        function handleKey(e) {
            if (!isOpen) return;
            if (e.key === "Escape") {
                e.preventDefault();
                closeModal();
            }
        }

        trigger.addEventListener("click", function (e) {
            e.preventDefault();
            openModal();
        });

        if (closeBtn) closeBtn.addEventListener("click", closeModal);
        if (cancelBtn) {
            cancelBtn.addEventListener("click", function (e) {
                e.preventDefault();
                closeModal();
            });
        }

        modal.addEventListener("mousedown", handleOutside);
        document.addEventListener("keydown", handleKey);

        if (form) {
            form.addEventListener("submit", function (e) {
                e.preventDefault();
                showError("");
                const fd = new URLSearchParams();
                const nextEmail = emailEl ? (emailEl.value || "").trim() : "";
                if (emailEl && nextEmail !== (initialEmail || "")) {
                    showError("Email changes require confirmation and are currently disabled.");
                    return;
                }
                fd.append("email", nextEmail);
                fd.append("preferred_name", prefEl ? (prefEl.value || "").trim() : "");
                const newPw = newPwEl ? (newPwEl.value || "").trim() : "";
                const oldPw = oldPwEl ? (oldPwEl.value || "").trim() : "";
                const newPw2 = newPw2El ? (newPw2El.value || "").trim() : "";
                if (newPw || newPw2) {
                    if (!newPw || !newPw2) {
                        showError("Please enter new password twice.");
                        return;
                    }
                    if (newPw !== newPw2) {
                        showError("New password entries do not match.");
                        return;
                    }
                    if (newPw.length < 6) {
                        showError("New password must be at least 6 characters.");
                        return;
                    }
                }
                if (newPw) {
                    fd.append("new_password", newPw);
                    fd.append("old_password", oldPw);
                    fd.append("new_password_confirm", newPw2);
                }

                fetch("/api/user/profile/", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-CSRFToken": getCookie("csrftoken") || "",
                    },
                    body: fd.toString(),
                })
                    .then(r => r.json())
                    .then(data => {
                        if (!data.ok) {
                            showError(data.error || "Save failed.");
                            return;
                        }
                        if (newPwEl) newPwEl.value = "";
                        if (newPw2El) newPw2El.value = "";
                        if (oldPwEl) oldPwEl.value = "";
                        closeModal();
                    })
                    .catch(err => {
                        console.error("Profile save error", err);
                        showError("Save failed.");
                    });
            });
        }
    }

    function sbInitUserSettingsModal() {
        const trigger = document.getElementById("sb-user-settings-trigger");
        const modal = document.getElementById("sb-settings-modal");
        if (!trigger || !modal) return;
        if (trigger.dataset.sbBound === "1") return;
        trigger.dataset.sbBound = "1";

        const dialog = modal.querySelector(".sb-modal-dialog");
        const closeBtn = modal.querySelector("#sb-settings-close");
        const cancelBtn = modal.querySelector("#sb-settings-cancel");
        const form = modal.querySelector("#sb-settings-form");
        const errBox = modal.querySelector("#sb-settings-error");
        const wlToggle = modal.querySelector("#sb-setting-wl");
        const darkToggle = modal.querySelector("#sb-setting-dark");
        const gtfoToggle = modal.querySelector("#sb-setting-gtfo-override");

        let isOpen = false;

        function showError(msg) {
            if (!errBox) return;
            errBox.textContent = msg || "";
            errBox.style.display = msg ? "block" : "none";
        }

        function fillSettings(data) {
            const u = (data && data.user) || {};
            if (wlToggle) wlToggle.checked = u.after_login_go_to_wl !== false;
            if (darkToggle) darkToggle.checked = u.prefer_dark_theme !== false;
            if (gtfoToggle) gtfoToggle.checked = getGtfoOverrideEnabled();
        }

        function openModal() {
            showError("");
            modal.style.display = "flex";
            isOpen = true;
            fetch("/api/user/profile/")
                .then(r => r.json())
                .then(data => {
                    if (!data.ok) {
                        showError(data.error || "Failed to load settings.");
                        return;
                    }
                    fillSettings(data);
                })
                .catch(err => {
                    console.error("Settings load error", err);
                    showError("Failed to load settings.");
                });
        }

        function closeModal() {
            modal.style.display = "none";
            isOpen = false;
        }

        function handleOutside(e) {
            if (!isOpen || !dialog) return;
            if (!dialog.contains(e.target)) {
                closeModal();
            }
        }

        function handleKey(e) {
            if (!isOpen) return;
            if (e.key === "Escape") {
                e.preventDefault();
                closeModal();
            }
        }

        trigger.addEventListener("click", function (e) {
            e.preventDefault();
            openModal();
        });

        if (closeBtn) closeBtn.addEventListener("click", closeModal);
        if (cancelBtn) {
            cancelBtn.addEventListener("click", function (e) {
                e.preventDefault();
                closeModal();
            });
        }

        modal.addEventListener("mousedown", handleOutside);
        document.addEventListener("keydown", handleKey);

        if (form) {
            form.addEventListener("submit", function (e) {
                e.preventDefault();
                showError("");
                const preferDark = !!(darkToggle && darkToggle.checked);
                const afterLoginWl = !!(wlToggle && wlToggle.checked);
                const gtfoOverrideEnabled = !!(gtfoToggle && gtfoToggle.checked);
                const fd = new URLSearchParams();
                fd.append("prefer_dark_theme", preferDark ? "true" : "false");
                fd.append("after_login_go_to_wl", afterLoginWl ? "true" : "false");

                fetch("/api/user/profile/", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-CSRFToken": getCookie("csrftoken") || "",
                    },
                    body: fd.toString(),
                })
                    .then(r => r.json())
                    .then(data => {
                        if (!data.ok) {
                            showError(data.error || "Save failed.");
                            return;
                        }
                        applyThemePreference(preferDark);
                        if (gtfoToggle) {
                            try {
                                localStorage.setItem(
                                    "sb_gtfo_override_enabled",
                                    gtfoOverrideEnabled ? "1" : "0"
                                );
                            } catch (e) {}
                            applyGtfoOverrideEnabled(gtfoOverrideEnabled);
                        }
                        closeModal();
                    })
                    .catch(err => {
                        console.error("Settings save error", err);
                        showError("Save failed.");
                    });
            });
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        syncHeaderTheme();
        updateEndCountdown();
        setInterval(updateEndCountdown, 30000);
        sbInitUserProfileModal();
        sbInitUserSettingsModal();
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
