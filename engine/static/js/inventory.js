(function () {
    const KEY = "stockbrain_theme";

    /* ================================================
       APPLY DARK MODE EARLY (no white flash)
    ================================================= */
    try {
        if (localStorage.getItem(KEY) === "dark") {
            document.documentElement.classList.add("sb-dark");
        }
    } catch (e) {}

    function syncBodyDarkClass() {
        if (document.documentElement.classList.contains("sb-dark")) {
            document.body.classList.add("sb-dark");
        } else {
            document.body.classList.remove("sb-dark");
        }
    }

    /* ================================================
       MULTILINE CLAMP INDICATOR (LOLLYPOP)
    ================================================= */
    function markClampedCells() {
        document.querySelectorAll("td.sb-clamped").forEach(td => {
            td.classList.remove("sb-clamped");
        });

        const cells = document.querySelectorAll(
            "td.col-name .sb-multiline," +
            "td.col-partdesc .sb-multiline," +
            "td.col-partnum .sb-multiline," +
            "td.col-dcm .sb-multiline," +
            "td.col-oemname .sb-multiline," +
            "td.col-oemnum .sb-multiline," +
            "td.col-vendor .sb-multiline," +
            "td.col-sourceloc .sb-multiline"
        );

        cells.forEach(el => {
            if (el.scrollHeight > el.clientHeight + 1) {
                const td = el.closest("td");
                if (td) td.classList.add("sb-clamped");
            }
        });
    }

    /* ================================================
       DJANGO CSRF TOKEN
    ================================================= */
    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(";").shift();
    }

    const csrftoken = getCookie("csrftoken") || "";

    /* ================================================
       AJAX: UPDATE UNIT (FK)
    ================================================= */
    function sbInitUnitDropdowns() {
        const selects = document.querySelectorAll(".unit-select");
        if (!selects.length) return;

        selects.forEach(select => {
            select.addEventListener("change", e => {
                const sel = e.target;
                const itemId = sel.dataset.itemId;
                const unitId = sel.value;

                if (!itemId || !unitId) return;

                const fd = new FormData();
                fd.append("item_id", itemId);
                fd.append("unit_id", unitId);

                fetch("/api/update-unit/", {
                    method: "POST",
                    headers: { "X-CSRFToken": csrftoken },
                    body: fd,
                })
                    .then(r => r.json())
                    .then(data => {
                        if (!data.ok) {
                            console.error("Unit update failed", data.error);
                        }
                    })
                    .catch(err => {
                        console.error("Unit update error", err);
                    });
            });
        });
    }

    /* ================================================
       AJAX: UPDATE GROUP (FK)
    ================================================= */
    function sbInitGroupDropdowns() {
        const selects = document.querySelectorAll(".group-select");
        if (!selects.length) return;

        selects.forEach(select => {
            select.addEventListener("change", e => {
                const sel = e.target;
                const itemId = sel.dataset.itemId;
                const groupId = sel.value;

                if (!itemId || !groupId) return;

                const fd = new FormData();
                fd.append("item_id", itemId);
                fd.append("group_id", groupId);

                fetch("/api/update-group/", {
                    method: "POST",
                    headers: { "X-CSRFToken": csrftoken },
                    body: fd,
                })
                    .then(r => r.json())
                    .then(data => {
                        if (!data.ok) {
                            console.error("Group update failed", data.error);
                        }
                    })
                    .catch(err => {
                        console.error("Group update error", err);
                    });
            });
        });
    }

    /* ================================================
       AJAX: CONDITION STATUS DROPDOWN
    ================================================= */
    function sbInitConditionDropdowns() {
        const selects = document.querySelectorAll(".condition-select");
        if (!selects.length) return;

        selects.forEach(select => {
            select.addEventListener("change", e => {
                const sel = e.target;
                const itemId = sel.dataset.itemId;
                const value = sel.value || "";

                if (!itemId) return;

                const fd = new FormData();
                fd.append("item_id", itemId);
                fd.append("field", "condition_status");
                fd.append("value", value);

                fetch("/api/update-field/", {
                    method: "POST",
                    headers: { "X-CSRFToken": csrftoken },
                    body: fd,
                })
                    .then(r => r.json())
                    .then(data => {
                        if (!data.ok) {
                            console.error("Condition update failed", data.error);
                        }
                    })
                    .catch(err => {
                        console.error("Condition update error", err);
                    });
            });
        });
    }

    /* ================================================
       AJAX: REV. + DISC CHECKBOXES
    ================================================= */
    function sbInitRevDiscCheckboxes() {
        const revCheckboxes = document.querySelectorAll(".rev-checkbox");
        const discCheckboxes = document.querySelectorAll(".disc-checkbox");

        function updateBooleanField(checkbox, fieldName) {
            const itemId = checkbox.dataset.itemId;
            if (!itemId) return;

            const fd = new FormData();
            fd.append("item_id", itemId);
            fd.append("field", fieldName);
            fd.append("value", checkbox.checked ? "1" : "0");

            const row = checkbox.closest("tr");

            fetch("/api/update-field/", {
                method: "POST",
                headers: { "X-CSRFToken": csrftoken },
                body: fd,
            })
                .then(r => r.json())
                .then(data => {
                    if (!data.ok) {
                        console.error(`Update ${fieldName} failed`, data.error);
                        return;
                    }

                    if (!row) return;

                    if (fieldName === "verify") {
                        if (checkbox.checked) {
                            row.classList.add("sb-row-verify");
                        } else {
                            row.classList.remove("sb-row-verify");
                        }
                    }

                    if (fieldName === "discontinued") {
                        if (checkbox.checked) {
                            row.classList.add("sb-row-disc");
                        } else {
                            row.classList.remove("sb-row-disc");
                        }
                    }
                })
                .catch(err => {
                    console.error(`Update ${fieldName} error`, err);
                });
        }

        revCheckboxes.forEach(cb => {
            cb.addEventListener("change", () => updateBooleanField(cb, "verify"));
        });

        discCheckboxes.forEach(cb => {
            cb.addEventListener("change", () => updateBooleanField(cb, "discontinued"));
        });
    }

    /* ================================================
       AJAX: PER-USER FAVORITE STAR
    ================================================= */
    function sbInitFavorites() {
        const stars = document.querySelectorAll(".sb-favorite");
        if (!stars.length) return;

        const cycle = ["NONE", "RED", "GREEN", "YELLOW", "BLUE"];

        function setStarAppearance(el, color) {
            el.dataset.color = color;

            el.classList.remove(
                "sb-fav-red",
                "sb-fav-green",
                "sb-fav-yellow",
                "sb-fav-blue",
                "sb-fav-none"
            );

            let symbol = "☆";
            let cls = "sb-fav-none";

            if (color === "RED") {
                symbol = "★";
                cls = "sb-fav-red";
            } else if (color === "GREEN") {
                symbol = "★";
                cls = "sb-fav-green";
            } else if (color === "YELLOW") {
                symbol = "★";
                cls = "sb-fav-yellow";
            } else if (color === "BLUE") {
                symbol = "★";
                cls = "sb-fav-blue";
            }

            el.textContent = symbol;
            el.classList.add(cls);
        }

        stars.forEach(star => {
            const initialColor = (star.dataset.color || "NONE").toUpperCase();
            setStarAppearance(star, initialColor);

            star.addEventListener("click", () => {
                const itemId = star.dataset.itemId;
                if (!itemId) return;

                const current = (star.dataset.color || "NONE").toUpperCase();
                const idx = cycle.indexOf(current);
                const nextColor = cycle[(idx + 1) % cycle.length];

                setStarAppearance(star, nextColor);

                const fd = new FormData();
                fd.append("item_id", itemId);
                fd.append("color", nextColor);

                fetch("/api/update-favorite/", {
                    method: "POST",
                    headers: { "X-CSRFToken": csrftoken },
                    body: fd,
                })
                    .then(r => r.json())
                    .then(data => {
                        if (!data.ok) {
                            console.error("Favorite update failed:", data.error);
                        }
                    })
                    .catch(err => {
                        console.error("Favorite update error:", err);
                    });
            });
        });
    }

    /* ================================================
       AJAX: PER-USER NOTE (Quill modal)
    ================================================= */
    function decodeHtmlEntities(str) {
        if (!str) return "";
        const textarea = document.createElement("textarea");
        textarea.innerHTML = str;
        return textarea.value;
    }

    function sbInitNoteButtons() {
        const buttons = document.querySelectorAll(".sb-note-btn");
        if (!buttons.length) return;

        buttons.forEach(btn => {
            // 1) ustaw stan wizualny na starcie na podstawie data-has-note
            const hasNoteAttr = btn.dataset.hasNote;
            if (hasNoteAttr === "1") {
                btn.classList.add("sb-note-has-content");
            } else {
                btn.classList.remove("sb-note-has-content");
            }

            // 2) klik — otwarcie modala
            btn.addEventListener("click", () => {
                if (typeof window.sbOpenQuillEditor !== "function") {
                    console.error("Quill editor not ready yet");
                    return;
                }

                const itemId = btn.dataset.itemId;
                const raw = btn.dataset.note || "";
                const html = decodeHtmlEntities(raw);

                window.sbOpenQuillEditor("note", itemId, html, btn);
            });
        });
    }

    /* ================================================
       INLINE TEXT EDITING
    ================================================= */
    function sbInitInlineEditing() {
        const cells = document.querySelectorAll("td.inline");
        if (!cells.length) return;

        cells.forEach(td => {
            td.addEventListener("dblclick", function () {
                const field = td.dataset.field;
                const itemId = td.dataset.id;

                if (!field || !itemId) return;

                if (td.querySelector("input.sb-inline-input")) {
                    return;
                }

                const originalText = td.innerText.trim();

                const input = document.createElement("input");
                input.type = "text";
                input.className = "sb-inline-input";
                input.value = originalText;

                td.innerHTML = "";
                td.appendChild(input);
                input.focus();
                input.select();

                const finish = (save) => {
                    const newValue = input.value.trim();

                    if (!save || newValue === originalText) {
                        td.innerText = originalText;
                        return;
                    }

                    const fd = new FormData();
                    fd.append("item_id", itemId);
                    fd.append("field", field);
                    fd.append("value", newValue);

                    fetch("/api/update-field/", {
                        method: "POST",
                        headers: { "X-CSRFToken": csrftoken },
                        body: fd,
                    })
                        .then(r => r.json())
                        .then(data => {
                            if (!data.ok) {
                                console.error("Inline update failed:", data.error);
                                td.innerText = originalText;
                            } else {
                                td.innerText = newValue;
                                markClampedCells();
                            }
                        })
                        .catch(err => {
                            console.error("Inline update error:", err);
                            td.innerText = originalText;
                        });
                };

                input.addEventListener("keydown", function (e) {
                    if (e.key === "Enter") {
                        finish(true);
                    } else if (e.key === "Escape") {
                        finish(false);
                    }
                });

                input.addEventListener("blur", function () {
                    finish(true);
                });
            });
        });
    }

    /* ================================================
       QUILL MODAL (DESCRIPTION + USER NOTE)
    ================================================= */
    function sbInitQuillModal() {
        const modal = document.getElementById("sb-quill-modal");
        if (!modal || !window.Quill) return;

        const dialog = modal.querySelector(".sb-modal-dialog");
        const closeBtn = modal.querySelector(".sb-modal-close");
        const cancelBtn = modal.querySelector(".sb-modal-cancel");
        const saveBtn = modal.querySelector(".sb-modal-save");
        const editorNode = document.getElementById("sb-quill-editor");

        if (!dialog || !editorNode) return;

        const quill = new Quill(editorNode, {
            theme: "snow",
            modules: {
                toolbar: [
                    [{ header: [1, 2, false] }],
                    ["bold", "italic", "underline"],
                    [{ list: "ordered" }, { list: "bullet" }],
                    ["link"],
                    ["clean"],
                ],
            },
        });

        const state = {
            currentItemId: null,
            mode: "description",
            currentCell: null,
            noteButton: null,
            modal,
        };

        function hideModal() {
            modal.style.display = "none";
            state.currentItemId = null;
            state.currentCell = null;
            state.noteButton = null;
            state.mode = "description";
        }

        function openModal(mode, itemId, html, targetElement) {
            state.mode = mode || "description";
            state.currentItemId = itemId || null;
            state.currentCell = null;
            state.noteButton = null;

            if (state.mode === "description") {
                state.currentCell = targetElement;
            } else if (state.mode === "note") {
                state.noteButton = targetElement;
            }

            quill.root.innerHTML = html || "";
            modal.style.display = "flex";
        }

        window.sbOpenQuillEditor = openModal;

        if (closeBtn) closeBtn.addEventListener("click", hideModal);
        if (cancelBtn) cancelBtn.addEventListener("click", hideModal);

        modal.addEventListener("click", function (e) {
            if (e.target === modal) {
                hideModal();
            }
        });

        if (saveBtn) {
            saveBtn.addEventListener("click", function () {
                if (!state.currentItemId) {
                    hideModal();
                    return;
                }

                const html = quill.root.innerHTML.trim();

                // DESCRIPTION MODE
                if (state.mode === "description") {
                    const cell = state.currentCell;
                    const fd = new FormData();
                    fd.append("item_id", state.currentItemId);
                    fd.append("field", "part_description");
                    fd.append("value", html);

                    fetch("/api/update-field/", {
                        method: "POST",
                        headers: { "X-CSRFToken": csrftoken },
                        body: fd,
                    })
                        .then(r => r.json())
                        .then(data => {
                            if (!data.ok) {
                                console.error("Quill save (description) failed:", data.error);
                            } else if (cell) {
                                const preview = cell.querySelector(".sb-desc-preview");
                                if (preview) {
                                    preview.innerHTML = html;
                                }
                                markClampedCells();
                            }
                            hideModal();
                        })
                        .catch(err => {
                            console.error("Quill save (description) error:", err);
                            hideModal();
                        });
                }

                // NOTE MODE
                else if (state.mode === "note") {
                    const btn = state.noteButton;
                    const fd = new FormData();
                    fd.append("item_id", state.currentItemId);
                    fd.append("note", html);

                    fetch("/api/update-note/", {
                        method: "POST",
                        headers: { "X-CSRFToken": csrftoken },
                        body: fd,
                    })
                        .then(r => r.json())
                        .then(data => {
                            if (!data.ok) {
                                console.error("Quill save (note) failed:", data.error);
                            } else if (btn) {
                                btn.dataset.note = html;

                                const plain = html.replace(/<[^>]*>/g, "").trim();
                                btn.dataset.hasNote = plain.length > 0 ? "1" : "0";

                                if (plain.length > 0) {
                                    btn.classList.add("sb-note-has-content");
                                } else {
                                    btn.classList.remove("sb-note-has-content");
                                }
                            }
                            hideModal();
                        })
                        .catch(err => {
                            console.error("Quill save (note) error:", err);
                            hideModal();
                        });
                }
            });
        }
    }

    // DESCRIPTION triggers (🔍)
    function sbInitQuillTriggers() {
        const btns = document.querySelectorAll(".sb-desc-edit-btn");
        if (!btns.length || typeof window.sbOpenQuillEditor !== "function") return;

        btns.forEach(btn => {
            btn.addEventListener("click", function () {
                const itemId = btn.dataset.id;
                const cell = btn.closest("td");
                const preview = cell ? cell.querySelector(".sb-desc-preview") : null;
                const html = preview ? preview.innerHTML : "";

                window.sbOpenQuillEditor("description", itemId, html, cell);
            });
        });
    }

    /* ================================================
       AJAX PAGINATION + PAGE SIZE
    ================================================= */
    function sbLoadInventory(url) {
        const card = document.querySelector(".sb-card");
        if (!card) {
            window.location.href = url;
            return;
        }

        const oldWrapper = document.querySelector(".sb-table-wrapper");
        const scrollState = oldWrapper
            ? { left: oldWrapper.scrollLeft, top: oldWrapper.scrollTop }
            : { left: 0, top: 0 };

        fetch(url, {
            method: "GET",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
        })
            .then(resp => resp.text())
            .then(html => {
                const parser = new DOMParser();
                const doc = parser.parseFromString(html, "text/html");
                const newCard = doc.querySelector(".sb-card");

                if (!newCard) {
                    window.location.href = url;
                    return;
                }

                card.replaceWith(newCard);

                const newWrapper = document.querySelector(".sb-table-wrapper");
                if (newWrapper) {
                    newWrapper.scrollLeft = scrollState.left;
                    newWrapper.scrollTop = scrollState.top;
                }

                markClampedCells();
                sbInitUnitDropdowns();
                sbInitGroupDropdowns();
                sbInitConditionDropdowns();
                sbInitRevDiscCheckboxes();
                sbInitFavorites();
                sbInitInlineEditing();
                sbInitPagination();
                sbInitQuillModal();
                sbInitQuillTriggers();
                sbInitNoteButtons();
            })
            .catch(err => {
                console.error("Pagination AJAX error:", err);
                window.location.href = url;
            });
    }

    function sbInitPagination() {
        const sizeSelect = document.getElementById("page-size-select");
        if (sizeSelect) {
            sizeSelect.addEventListener("change", function () {
                const pageSize = this.value;
                const url = new URL(window.location.href);

                url.searchParams.set("page", 1);
                url.searchParams.set("page_size", pageSize);

                sbLoadInventory(url.toString());
            });
        }

        const pagerLinks = document.querySelectorAll(".sb-pagination .sb-page-link[data-page]");
        pagerLinks.forEach(link => {
            link.addEventListener("click", function (e) {
                e.preventDefault();
                const targetPage = this.dataset.page;
                if (!targetPage) return;

                const url = new URL(window.location.href);
                url.searchParams.set("page", targetPage);

                const ps = document.getElementById("page-size-select");
                if (ps) {
                    url.searchParams.set("page_size", ps.value);
                }

                sbLoadInventory(url.toString());
            });
        });
    }

    /* ================================================
       THEME TOGGLE
    ================================================= */
    window.sbToggleTheme = function () {
        const root = document.documentElement;
        const nowDark = root.classList.toggle("sb-dark");
        syncBodyDarkClass();
        try {
            localStorage.setItem(KEY, nowDark ? "dark" : "light");
        } catch (e) {}
    };

    /* ================================================
       INIT
    ================================================= */
    document.addEventListener("DOMContentLoaded", function () {
        syncBodyDarkClass();
        markClampedCells();
        sbInitUnitDropdowns();
        sbInitGroupDropdowns();
        sbInitConditionDropdowns();
        sbInitRevDiscCheckboxes();
        sbInitFavorites();
        sbInitInlineEditing();
        sbInitPagination();
        sbInitQuillModal();
        sbInitQuillTriggers();
        sbInitNoteButtons();
    });
})();
