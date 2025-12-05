(function () {
    const KEY = "stockbrain_theme";
    let quillInstance = null;  // single global Quill instance for modal

    // Global flag from Django context: can user edit inventory fields?
    const CAN_EDIT = !!(window && window.CAN_EDIT);
    const HIGHLIGHT_KEY = "sb_new_item_highlight";

    const CELL_STATE_CLASSES = {
        focus: "sb-cell-focus",
        edited: "sb-cell-edited",
        saved: "sb-cell-saved",
    };

    let activeCellState = { cell: null, type: null };

    function clearActiveCellState() {
        if (activeCellState.cell) {
            activeCellState.cell.classList.remove(
                CELL_STATE_CLASSES.focus,
                CELL_STATE_CLASSES.edited,
                CELL_STATE_CLASSES.saved
            );
        }
        activeCellState = { cell: null, type: null };
    }

    function setActiveCellState(type, element) {
        const cell = element ? element.closest("td") : null;
        if (!cell || !CELL_STATE_CLASSES[type]) return;

        clearActiveCellState();
        cell.classList.add(CELL_STATE_CLASSES[type]);
        activeCellState = { cell, type };
    }

    /* ================================================
       APPLY THEME EARLY (no flash)
       Default: sb-light; when stored: sb-dark
    ================================================= */
    (function applyInitialTheme() {
        const root = document.documentElement;
        const body = document.body;
        root.classList.add("sb-light");
        if (body) body.classList.add("sb-light");
        try {
            if (localStorage.getItem(KEY) === "dark") {
                root.classList.remove("sb-light");
                root.classList.add("sb-dark");
                if (body) {
                    body.classList.remove("sb-light");
                    body.classList.add("sb-dark");
                }
            }
        } catch (e) {}
    })();

    function syncBodyDarkClass() {
        const root = document.documentElement;
        const body = document.body;
        const isDark = root.classList.contains("sb-dark");
        if (isDark) {
            document.body.classList.add("sb-dark");
            root.classList.remove("sb-light");
            body && body.classList.remove("sb-light");
        } else {
            document.body.classList.remove("sb-dark");
            root.classList.add("sb-light");
            body && body.classList.add("sb-light");
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
            "td.col-sourceloc .sb-multiline," +
            "td.col-note .sb-multiline"
        );

        cells.forEach(el => {
            if (el.scrollHeight > el.clientHeight + 1) {
                const td = el.closest("td");
                if (td) td.classList.add("sb-clamped");
            }
        });
    }

    /* ================================================
       REORDER FLAG (frontend mirror of model.for_reorder)
       quantity_in_stock <= reorder_level AND not discontinued
    ================================================= */
    function sbUpdateReorderFlag(itemId) {
        if (!itemId) return;
        const row = document.querySelector(`tr[data-item-id="${itemId}"]`);
        if (!row) return;

        const instockCell = row.querySelector(".col-instock");
        const levelCell = row.querySelector(".col-reorderlevel");
        const reorderCell = row.querySelector(".col-reorder");
        const discCheckbox = row.querySelector(".disc-checkbox");

        if (!instockCell || !levelCell || !reorderCell) return;

        const q = parseInt(instockCell.textContent.trim(), 10);
        const rl = parseInt(levelCell.textContent.trim(), 10);
        const discontinued = !!(discCheckbox && discCheckbox.checked);

        const validQ = !Number.isNaN(q);
        const validRL = !Number.isNaN(rl);

        const shouldReorder = validQ && validRL && q <= rl && !discontinued;

        reorderCell.innerHTML = "";
        if (shouldReorder) {
            const span = document.createElement("span");
            span.className = "sb-tag sb-tag-warning";
            span.textContent = "YES";
            reorderCell.appendChild(span);
        }
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
       AJAX: UPDATE UNIT (FK) - only if CAN_EDIT
    ================================================= */
    function sbInitUnitDropdowns() {
        if (!CAN_EDIT) {
            // disable change for readonly users
            const selects = document.querySelectorAll(".unit-select");
            selects.forEach(sel => sel.setAttribute("disabled", "disabled"));
            return;
        }

        const selects = document.querySelectorAll(".unit-select");
        if (!selects.length) return;

        selects.forEach(select => {
            select.addEventListener("focus", () => setActiveCellState("edited", select));
            select.addEventListener("blur", () => {
                const td = select.closest("td");
                if (td && td.classList.contains(CELL_STATE_CLASSES.edited)) {
                    setActiveCellState("focus", select);
                }
            });
            select.addEventListener("keydown", e => {
                if (e.key === "Escape") {
                    setActiveCellState("focus", select);
                    select.blur();
                }
            });
            select.addEventListener("keyup", e => {
                if (e.key === "Escape") {
                    setActiveCellState("focus", select);
                }
            });

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
                        } else {
                            setActiveCellState("saved", select);
                        }
                    })
                    .catch(err => {
                        console.error("Unit update error", err);
                    });
            });
        });
    }

    function sbInitRackFilter() {
        const select = document.querySelector(".sb-filter-rack");
        const table = document.querySelector(".sb-table");
        if (!select || !table) return;

        const currentSort = table.dataset.currentSort || "rack";
        const currentDir = table.dataset.currentDir || "asc";

        select.addEventListener("change", function () {
            const url = new URL(window.location.href);
            if (this.value) {
                url.searchParams.set("rack_filter", this.value);
                url.searchParams.set("page_size", "all");
            } else {
                url.searchParams.delete("rack_filter");
                // wracamy do ustawionego page size
                const ps = document.getElementById("page-size-select");
                if (ps) {
                    url.searchParams.set("page_size", ps.value);
                }
            }
            url.searchParams.set("page", 1);
            url.searchParams.set("sort", currentSort);
            url.searchParams.set("dir", currentDir);

            sbLoadInventory(url.toString());
        });
    }

    function sbInitGroupFilter() {
        const select = document.querySelector(".sb-filter-group");
        const table = document.querySelector(".sb-table");
        if (!select || !table) return;

        const currentSort = table.dataset.currentSort || "rack";
        const currentDir = table.dataset.currentDir || "asc";

        select.addEventListener("change", function () {
            const url = new URL(window.location.href);
            if (this.value) {
                url.searchParams.set("group_filter", this.value);
                url.searchParams.set("page_size", "all");
            } else {
                url.searchParams.delete("group_filter");
                const ps = document.getElementById("page-size-select");
                if (ps) {
                    url.searchParams.set("page_size", ps.value);
                }
            }
            url.searchParams.set("page", 1);
            url.searchParams.set("sort", currentSort);
            url.searchParams.set("dir", currentDir);

            sbLoadInventory(url.toString());
        });
    }

    /* ================================================
       AJAX: UPDATE GROUP (FK) - only if CAN_EDIT
    ================================================= */
    function sbInitGroupDropdowns() {
        if (!CAN_EDIT) {
            const selects = document.querySelectorAll(".group-select");
            selects.forEach(sel => sel.setAttribute("disabled", "disabled"));
            return;
        }

        const selects = document.querySelectorAll(".group-select");
        if (!selects.length) return;

        selects.forEach(select => {
            select.addEventListener("focus", () => setActiveCellState("edited", select));
            select.addEventListener("blur", () => {
                const td = select.closest("td");
                if (td && td.classList.contains(CELL_STATE_CLASSES.edited)) {
                    setActiveCellState("focus", select);
                }
            });
            select.addEventListener("keydown", e => {
                if (e.key === "Escape") {
                    setActiveCellState("focus", select);
                    select.blur();
                }
            });
            select.addEventListener("keyup", e => {
                if (e.key === "Escape") {
                    setActiveCellState("focus", select);
                }
            });

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
                        } else {
                            setActiveCellState("saved", select);
                        }
                    })
                    .catch(err => {
                        console.error("Group update error", err);
                    });
            });
        });
    }

    /* ================================================
       AJAX: CONDITION STATUS DROPDOWN - only if CAN_EDIT
    ================================================= */
    function sbInitConditionDropdowns() {
        const selects = document.querySelectorAll(".condition-select");
        if (!selects.length) return;

        if (!CAN_EDIT) {
            selects.forEach(sel => sel.setAttribute("disabled", "disabled"));
            return;
        }

        selects.forEach(select => {
            select.addEventListener("focus", () => setActiveCellState("edited", select));
            select.addEventListener("blur", () => {
                const td = select.closest("td");
                if (td && td.classList.contains(CELL_STATE_CLASSES.edited)) {
                    setActiveCellState("focus", select);
                }
            });
            select.addEventListener("keydown", e => {
                if (e.key === "Escape") {
                    setActiveCellState("focus", select);
                    select.blur();
                }
            });
            select.addEventListener("keyup", e => {
                if (e.key === "Escape") {
                    setActiveCellState("focus", select);
                }
            });

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
                        } else {
                            setActiveCellState("saved", select);
                        }
                    })
                    .catch(err => {
                        console.error("Condition update error", err);
                    });
            });
        });
    }

    /* ================================================
       AJAX: REV. + DISC CHECKBOXES - only if CAN_EDIT
    ================================================= */
    function sbInitRevDiscCheckboxes() {
        const revCheckboxes = document.querySelectorAll(".rev-checkbox");
        const discCheckboxes = document.querySelectorAll(".disc-checkbox");

        if (!CAN_EDIT) {
            // blokada dla zwyklych uzytkownikow - wizualnie disabled
            revCheckboxes.forEach(cb => cb.setAttribute("disabled", "disabled"));
            discCheckboxes.forEach(cb => cb.setAttribute("disabled", "disabled"));
            return;
        }

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
                        // discontinued wplywa na for_reorder
                        sbUpdateReorderFlag(itemId);
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
       AJAX: PER-USER FAVORITE STAR (zawsze dozwolone)
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

            let cls = "sb-fav-none";
            if (color === "RED") {
                cls = "sb-fav-red";
            } else if (color === "GREEN") {
                cls = "sb-fav-green";
            } else if (color === "YELLOW") {
                cls = "sb-fav-yellow";
            } else if (color === "BLUE") {
                cls = "sb-fav-blue";
            }

            const filled = color !== "NONE";
            const svg = filled
                ? '<svg class="sb-fav-icon" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2l2.9 5.88 6.49.94-4.7 4.58 1.11 6.47L12 16.9 6.2 19.87l1.11-6.47-4.7-4.58 6.49-.94z"/></svg>'
                : '<svg class="sb-fav-icon" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" d="M12 2l2.9 5.88 6.49.94-4.7 4.58 1.11 6.47L12 16.9 6.2 19.87l1.11-6.47-4.7-4.58 6.49-.94z"/></svg>';

            el.innerHTML = svg;
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

                // Optymistyczna aktualizacja UI
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
       UTILS: decode HTML entities (for note/desc text)
    ================================================= */
    function decodeHtmlEntities(str) {
        if (!str) return "";
        const textarea = document.createElement("textarea");
        textarea.innerHTML = str;
        return textarea.value;
    }

    function setInlineTextareaSize(td, textarea, baseHeight = 0) {
        if (!td || !textarea) return;

        const cs = window.getComputedStyle(textarea);
        const lineHeight = parseFloat(cs.lineHeight) || 16;
        const maxHeight = lineHeight * 5;

        const targetHeight = Math.min(
            Math.max(baseHeight, td.clientHeight, textarea.scrollHeight, 40),
            maxHeight
        );

        textarea.style.height = `${targetHeight}px`;
        textarea.style.minHeight = `${targetHeight}px`;
        textarea.style.maxHeight = `${maxHeight}px`;
        textarea.style.width = "100%";
    }

    function rememberHighlight(id) {
        try {
            localStorage.setItem(HIGHLIGHT_KEY, String(id));
        } catch (e) {}
    }

    function updateHeaderCountFromCard() {
        const card = document.querySelector(".sb-card");
        const counterEl = document.querySelector(".sb-header-count");
        if (!card || !counterEl) return;
        const val = card.dataset.totalCount;
        if (val !== undefined) {
            counterEl.textContent = `${val} items in base`;
        }
    }

    function adjustHeaderCount(delta) {
        const card = document.querySelector(".sb-card");
        const counterEl = document.querySelector(".sb-header-count");
        if (!counterEl) return;
        let current = card && card.dataset.totalCount ? parseInt(card.dataset.totalCount, 10) : null;
        if (Number.isNaN(current)) current = null;
        if (current === null) {
            const match = counterEl.textContent.match(/^\s*(\d+)/);
            if (match) current = parseInt(match[1], 10);
        }
        if (current === null) return;
        const next = current + delta;
        if (card) card.dataset.totalCount = String(next);
        counterEl.textContent = `${next} items in base`;
    }

    function applyPendingHighlight() {
        let id = null;
        try {
            id = localStorage.getItem(HIGHLIGHT_KEY);
        } catch (e) {}
        if (!id) return;

        const row = document.querySelector(`tr[data-item-id="${id}"]`);
        if (row) {
            const nameCell = row.querySelector(".col-name") || row.querySelector("td");
            if (nameCell) {
                setActiveCellState("saved", nameCell);
                nameCell.scrollIntoView({ behavior: "smooth", block: "center" });
            }
        }

        try {
            localStorage.removeItem(HIGHLIGHT_KEY);
        } catch (e) {}
    }

    function sbEnsureNewItemVisible(itemId, targetPage) {
        if (!itemId) return;

        const pageSizeSel = document.getElementById("page-size-select");
        const table = document.querySelector(".sb-table");
        const url = new URL(window.location.href);

        // force requested page
        if (targetPage) {
            url.searchParams.set("page", String(targetPage));
        }
        // keep current sort/dir from table dataset (fallback to existing params)
        if (table) {
            const curSort = table.dataset.currentSort;
            const curDir = table.dataset.currentDir;
            if (curSort) url.searchParams.set("sort", curSort);
            if (curDir) url.searchParams.set("dir", curDir);
        }
        // keep page size from UI dropdown if present
        if (pageSizeSel && pageSizeSel.value) {
            url.searchParams.set("page_size", pageSizeSel.value);
        }

        // kontrolny komunikat dokad nastapi przekierowanie
        rememberHighlight(itemId);
        window.location.href = url.toString();
    }

    /* ================================================
       CELL STATE (focus / edited / saved)
       - single active cell at a time
    ================================================= */
    function sbInitCellFocusTracking() {
        const table = document.querySelector(".sb-table");
        if (!table) return;

        table.addEventListener("click", function (e) {
            const cell = e.target.closest("td");
            if (!cell || !table.contains(cell)) return;

            // If we just marked this cell as edited, do not downgrade to focus.
            if (cell.classList.contains(CELL_STATE_CLASSES.edited)) return;

            setActiveCellState("focus", cell);
        });
    }

    /* ================================================
       NOTE BUTTONS (CLICK -> QUILL dla edytorow)
    ================================================= */
    function sbInitNoteButtons() {
        const buttons = document.querySelectorAll(".sb-note-btn");
        if (!buttons.length) return;

        buttons.forEach(btn => {
            const hasNoteAttr = btn.dataset.hasNote;
            if (hasNoteAttr === "1") {
                btn.classList.add("sb-note-has-content");
            } else {
                btn.classList.remove("sb-note-has-content");
            }

            // Zwykly user NIE otwiera Quilla - edytuje notatk? przez dblclick (inline)
            if (!CAN_EDIT) {
                return;
            }

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
       DELETE ITEM MODAL
    ================================================= */
    function sbInitDeleteModal() {
        const modal = document.getElementById("sb-delete-modal");
        const successModal = document.getElementById("sb-delete-success");
        if (!modal) return;

        const dialog = modal.querySelector(".sb-modal-dialog");
        const closeBtn = modal.querySelector(".sb-modal-close");
        const cancelBtn = modal.querySelector(".sb-delete-cancel");
        const confirmBtn = modal.querySelector(".sb-delete-confirm");
        const passwordInput = modal.querySelector("#sb-delete-password");
        const locEl = modal.querySelector("#sb-del-loc");
        const nameEl = modal.querySelector("#sb-del-name");
        const qtyEl = modal.querySelector("#sb-del-qty");
        const okBtn = successModal ? successModal.querySelector(".sb-delete-ok") : null;

        let isOpen = false;
        let currentItemId = null;

        function closeModal() {
            modal.style.display = "none";
            isOpen = false;
            currentItemId = null;
            if (passwordInput) passwordInput.value = "";
        }

        function openModal(itemId, loc, name, qty) {
            currentItemId = itemId;
            if (locEl) locEl.textContent = loc || "";
            if (nameEl) nameEl.textContent = name || "";
            if (qtyEl) qtyEl.textContent = qty || "";
            modal.style.display = "flex";
            isOpen = true;
            if (passwordInput) passwordInput.focus();
        }

        function closeSuccess() {
            if (successModal) successModal.style.display = "none";
        }

        function showSuccess() {
            if (successModal) {
                successModal.style.display = "flex";
            }
        }

        function handleOutsideClick(e) {
            if (!isOpen) return;
            if (dialog && !dialog.contains(e.target)) {
                closeModal();
            }
        }

        function handleKeydown(e) {
            if (!isOpen) return;
            if (e.key === "Escape") {
                e.preventDefault();
                closeModal();
            }
        }

        document.addEventListener("mousedown", handleOutsideClick);
        document.addEventListener("keydown", handleKeydown);

        if (closeBtn) closeBtn.addEventListener("click", closeModal);
        if (cancelBtn) cancelBtn.addEventListener("click", closeModal);

        if (okBtn) {
            okBtn.addEventListener("click", () => {
                closeSuccess();
                const url = new URL(window.location.href);
                adjustHeaderCount(-1);
                sbLoadInventory(url.toString());
            });
        }

        if (confirmBtn) {
            confirmBtn.addEventListener("click", () => {
                if (!currentItemId) return;
                const pwd = passwordInput ? passwordInput.value : "";
                const fd = new URLSearchParams();
                fd.append("item_id", currentItemId);
                fd.append("password", pwd);

                fetch("/api/delete-item/", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-CSRFToken": csrftoken || "",
                    },
                    body: fd.toString(),
                })
                    .then(r => r.json())
                    .then(data => {
                        if (!data.ok) {
                            alert(data.error || "Delete failed");
                            return;
                        }
                        closeModal();
                        showSuccess();
                    })
                    .catch(err => {
                        console.error("Delete error", err);
                        alert("Delete failed");
                    });
            });
        }

        const buttons = document.querySelectorAll(".sb-trash-btn");
        buttons.forEach(btn => {
            btn.addEventListener("click", () => {
                const row = btn.closest("tr");
                const itemId = btn.dataset.itemId;

                // Prefer explicit data attributes; fall back to DOM text.
                const loc =
                    btn.dataset.loc ||
                    (row ? (row.querySelector(".col-location")?.textContent.trim() || "") : "");
                const name =
                    btn.dataset.name ||
                    (row ? (row.querySelector(".col-name")?.textContent.trim() || "") : "");
                const qty =
                    btn.dataset.qty ||
                    (row ? (row.querySelector(".col-instock")?.textContent.trim() || "") : "");
                openModal(itemId, loc, name, qty);
            });
        });
    }

    /* ================================================
       ADD ITEM MODAL (Editor / Purchase Manager)
    ================================================= */
    function sbInitAddItemModal() {
        const btn = document.getElementById("sb-add-item-btn");
        const modal = document.getElementById("sb-add-item-modal");
        if (!btn || !modal) return;

        const dialog = modal.querySelector(".sb-modal-dialog");
        const closeBtn = modal.querySelector(".sb-modal-close");
        const cancelBtn = modal.querySelector(".sb-modal-cancel");
        const saveBtns = modal.querySelectorAll(".sb-modal-save");
        const form = modal.querySelector("#sb-add-item-form");

        let isOpen = false;

        function openModal() {
            if (!modal) return;
            modal.style.display = "flex";
            isOpen = true;
            const firstInput = form ? form.querySelector("input, select, textarea") : null;
            if (firstInput) firstInput.focus();
        }

        function resetForm() {
            if (form) form.reset();
        }

        function closeModal(clear) {
            if (!modal) return;
            modal.style.display = "none";
            isOpen = false;
            if (clear) resetForm();
        }

        function handleKeydown(e) {
            if (!isOpen) return;
            if (e.key === "Escape") {
                e.preventDefault();
                closeModal(true);
            }
        }

        if (!document._sbAddItemKeydownBound) {
            document.addEventListener("keydown", handleKeydown);
            document._sbAddItemKeydownBound = true;
        }

        function serializeForm() {
            if (!form) return null;
            const fd = new FormData();
            const required = ["rack", "shelf", "box", "unit_id", "quantity_in_stock"];
            let missing = [];

            const elements = form.querySelectorAll("input, select, textarea");
            elements.forEach(el => {
                const name = el.name;
                if (!name) return;

                if (el.type === "checkbox") {
                    fd.append(name, el.checked ? "1" : "0");
                } else {
                    fd.append(name, el.value);
                }

                if (required.includes(name) && !el.value.trim()) {
                    missing.push(name);
                }
            });

            if (missing.length) {
                alert("Please fill required fields: " + missing.join(", "));
                return null;
            }
            return fd;
        }

        function postNewItem(mode) {
            const fd = serializeForm();
            if (!fd) return;

            fd.append("save_mode", mode);

            const table = document.querySelector(".sb-table");
            const currentSort = table ? (table.dataset.currentSort || "rack") : "rack";
            const currentDir = table ? (table.dataset.currentDir || "asc") : "asc";
            const pageSizeSel = document.getElementById("page-size-select");
            const pageSizeVal = pageSizeSel ? pageSizeSel.value : "50";

            fd.append("sort", currentSort);
            fd.append("dir", currentDir);
            fd.append("page_size", pageSizeVal);

            fetch("/api/create-item/", {
                method: "POST",
                headers: { "X-CSRFToken": csrftoken || "" },
                body: fd,
            })
                .then(r => r.json())
                .then(data => {
                    if (!data.ok) {
                        console.error("Create item failed:", data.error);
                        alert("Create item failed: " + (data.error || "Unknown error"));
                        return;
                    }

                    const newId = data.id;
                    const targetPage = data.page;

                    if (mode === "save-next") {
                        resetForm();
                        const firstInput = form ? form.querySelector("input, select, textarea") : null;
                        if (firstInput) firstInput.focus();
                        alert("Item saved. You can add the next one.");
                        adjustHeaderCount(1);
                        return; // stay in modal, do not navigate
                    } else {
                        closeModal(true);
                    }

                    sbEnsureNewItemVisible(newId, targetPage);
                    adjustHeaderCount(1);
                })
                .catch(err => {
                    console.error("Create item error:", err);
                    alert("Create item error. See console for details.");
                });
        }

        if (!btn.dataset.sbBound) {
            btn.addEventListener("click", openModal);
            btn.dataset.sbBound = "1";
        }

        if (!closeBtn?.dataset?.sbBound) {
            closeBtn.addEventListener("click", () => closeModal(true));
            closeBtn.dataset.sbBound = "1";
        }
        if (!cancelBtn?.dataset?.sbBound) {
            cancelBtn.addEventListener("click", () => closeModal(true));
            cancelBtn.dataset.sbBound = "1";
        }

        if (!modal.dataset.sbOverlayBound) {
            modal.addEventListener("click", function (e) {
                if (e.target === modal) {
                    closeModal(true);
                }
            });
            modal.dataset.sbOverlayBound = "1";
        }

        saveBtns.forEach(sbtn => {
            if (sbtn.dataset.sbBound) return;
            sbtn.addEventListener("click", function () {
                const mode = this.dataset.mode === "save-next" ? "save-next" : "save";
                postNewItem(mode);
            });
            sbtn.dataset.sbBound = "1";
        });
    }

    /* ================================================
       INLINE TEXT EDITING (dla td.inline) - tylko CAN_EDIT
    ================================================= */
    function sbInitInlineEditing() {
        if (!CAN_EDIT) return;

        const cells = document.querySelectorAll("td.inline");
        if (!cells.length) return;

        cells.forEach(td => {
            td.addEventListener("dblclick", function () {
                const field = td.dataset.field;
                const itemId = td.dataset.id;

                if (!field || !itemId) return;

                if (td.querySelector(".sb-inline-textarea")) {
                    return;
                }

                setActiveCellState("edited", td);
                td.classList.add("sb-inline-editing");

                const baseHeight = td.clientHeight;
                const originalHTML = td.innerHTML;
                const originalText = td.innerText.trim();

                const textarea = document.createElement("textarea");
                textarea.className = "sb-inline-textarea sb-inline-textarea-generic";
                textarea.value = originalText;
                textarea.rows = Math.max(1, (originalText.match(/\n/g) || []).length + 1);

                td.innerHTML = "";
                td.appendChild(textarea);
                setInlineTextareaSize(td, textarea, baseHeight);
                textarea.focus();
                textarea.select();

                // flaga - zabezpiecza przed wielokrotnym wywolaniem (ESC + blur itd.)
                let finished = false;

                const finish = (save) => {
                    if (finished) return;
                    finished = true;

                    const newValue = textarea.value.trim();

                    if (!save || newValue === originalText) {
                        td.innerHTML = originalHTML;
                        td.classList.remove("sb-inline-editing");
                        setActiveCellState("focus", td);
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
                                td.innerHTML = originalHTML;
                                td.classList.remove("sb-inline-editing");
                            } else {
                                const span = document.createElement("span");
                                span.className = "sb-multiline";
                                span.setAttribute("title", newValue);
                                span.innerHTML = newValue
                                    .split("\n")
                                    .map(line => line
                                        .replace(/&/g, "&amp;")
                                        .replace(/</g, "&lt;")
                                        .replace(/>/g, "&gt;"))
                                    .join("<br>");
                                td.innerHTML = "";
                                td.appendChild(span);

                                // jesli zmienilismy stock albo reorder level -> przelicz Reorder
                                if (field === "quantity_in_stock" || field === "reorder_level") {
                                    sbUpdateReorderFlag(itemId);
                                }
                                markClampedCells();
                                td.classList.remove("sb-inline-editing");
                                setActiveCellState("saved", td);
                            }
                        })
                        .catch(err => {
                            console.error("Inline update error:", err);
                            td.innerHTML = originalHTML;
                            td.classList.remove("sb-inline-editing");
                        });
                };

                textarea.addEventListener("keydown", function (e) {
                    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                        const pos = textarea.selectionStart;
                        const val = textarea.value;
                        textarea.value = val.slice(0, pos) + "\n" + val.slice(pos);
                        textarea.selectionStart = textarea.selectionEnd = pos + 1;
                        e.preventDefault();
                    } else if (e.key === "Enter") {
                        e.preventDefault();
                        finish(true);    // ZAPIS
                    } else if (e.key === "Escape") {
                        e.preventDefault();
                        finish(false);   // ANULUJ
                    }
                });

                textarea.addEventListener("blur", function () {
                    // blur dalej zapisuje, ALE tylko jesli
                    // finish nie byl wczesniej wywolany (np. ESC)
                    finish(true);
                });

            });
        });
    }

    /* ================================================
       INLINE EDITING: DESCRIPTION + USER NOTE
       - DESCRIPTION: tylko CAN_EDIT
       - NOTE: zawsze (prywatne pole usera)
    ================================================= */
    function sbInitInlineDescNoteEditing() {
        /* --------- DESCRIPTION (col-partdesc) ---------- */
        const descCells = document.querySelectorAll("td.col-partdesc");

        if (CAN_EDIT) {
            descCells.forEach(td => {
                td.addEventListener("dblclick", function (e) {
                    // jesli klik na przycisk ?, nie wlaczaj inline
                    if (e.target.closest(".sb-desc-edit-btn")) {
                        return;
                    }

                    const itemId = td.dataset.id;
                    const field = td.dataset.field || "part_description";
                    if (!itemId) return;

                    if (td.querySelector("textarea.sb-inline-textarea-desc")) {
                        return;
                    }

                    const container = td.querySelector(".sb-desc-container");
                    const preview = container ? container.querySelector(".sb-desc-preview") : null;
                    if (!container || !preview) return;

                    const baseHeight = td.clientHeight;

                    setActiveCellState("edited", td);
                    td.classList.add("sb-inline-editing");

                    // HTML -> plain text
                    const tmp = document.createElement("div");
                    tmp.innerHTML = preview.innerHTML;
                    const originalText = tmp.textContent.trim();

                const textarea = document.createElement("textarea");
                    textarea.className = "sb-inline-textarea sb-inline-textarea-desc";
                    textarea.value = originalText;
                    textarea.rows = Math.max(3, (originalText.match(/\n/g) || []).length + 1);

                    container.style.display = "none";
                    td.appendChild(textarea);
                    setInlineTextareaSize(td, textarea, baseHeight);
                    textarea.focus();
                    textarea.select();

                    const finish = (save) => {
                        const newText = textarea.value.trim();

                        if (!save || newText === originalText) {
                            td.removeChild(textarea);
                            container.style.display = "";
                            td.classList.remove("sb-inline-editing");
                            setActiveCellState("focus", td);
                            return;
                        }

                        const fd = new FormData();
                        fd.append("item_id", itemId);
                        fd.append("field", field);
                        fd.append("value", newText);

                        fetch("/api/update-field/", {
                            method: "POST",
                            headers: { "X-CSRFToken": csrftoken },
                            body: fd,
                        })
                            .then(r => r.json())
                            .then(data => {
                                if (!data.ok) {
                                    console.error("Inline description update failed:", data.error);
                                    td.removeChild(textarea);
                                    container.style.display = "";
                                    td.classList.remove("sb-inline-editing");
                                } else {
                                    const htmlNew = newText.replace(/\n/g, "<br>");
                                    preview.innerHTML = htmlNew;
                                    preview.setAttribute("title", newText);
                                    td.removeChild(textarea);
                                    container.style.display = "";
                                    markClampedCells();
                                    td.classList.remove("sb-inline-editing");
                                    setActiveCellState("saved", td);
                                }
                            })
                            .catch(err => {
                                console.error("Inline description update error:", err);
                                td.removeChild(textarea);
                                container.style.display = "";
                                td.classList.remove("sb-inline-editing");
                            });
                    };

                    textarea.addEventListener("keydown", function (e2) {
                        if (e2.key === "Enter" && (e2.ctrlKey || e2.metaKey)) {
                            // Ctrl+Enter = nowa linia
                            const pos = textarea.selectionStart;
                            const val = textarea.value;
                            textarea.value = val.slice(0, pos) + "\n" + val.slice(pos);
                            textarea.selectionStart = textarea.selectionEnd = pos + 1;
                            e2.preventDefault();
                        } else if (e2.key === "Enter") {
                            e2.preventDefault();
                            finish(true);
                        } else if (e2.key === "Escape") {
                            e2.preventDefault();
                            finish(false);
                        }
                    });

                    textarea.addEventListener("blur", function () {
                        finish(true);
                    });
                });
            });
        }

        /* ------------- USER NOTE (col-note) ------------- */
        const noteCells = document.querySelectorAll("td.col-note");
        noteCells.forEach(td => {
            td.addEventListener("dblclick", function (e) {
                // jesli klik na przycisk ?, nie wlaczaj inline - to (dla edytorow) otwiera Quilla
                if (e.target.closest(".sb-note-btn")) {
                    return;
                }

                const itemId = td.dataset.itemId;
                if (!itemId) return;

                if (td.querySelector("textarea.sb-inline-textarea-note")) {
                    return;
                }

                const btn = td.querySelector(".sb-note-btn");
                const preview = td.querySelector(".sb-note-preview");
                const container = td.querySelector(".sb-note-container");
                if (!btn || !preview || !container) return;

                setActiveCellState("edited", td);
                td.classList.add("sb-inline-editing");
                const baseHeight = td.clientHeight;

                const raw = btn.dataset.note || "";
                const html = decodeHtmlEntities(raw);
                const tmp = document.createElement("div");
                tmp.innerHTML = html;
                const originalText = tmp.textContent.trim();

                const textarea = document.createElement("textarea");
                textarea.className = "sb-inline-textarea sb-inline-textarea-note";
                textarea.value = originalText;
                textarea.rows = Math.max(3, (originalText.match(/\n/g) || []).length + 1);

                container.style.display = "none";
                td.appendChild(textarea);
                setInlineTextareaSize(td, textarea, baseHeight);
                textarea.focus();
                textarea.select();

                const finishNote = (save) => {
                    const newText = textarea.value.trim();

                    if (!save || newText === originalText) {
                        td.removeChild(textarea);
                        container.style.display = "";
                        td.classList.remove("sb-inline-editing");
                        setActiveCellState("focus", td);
                        return;
                    }

                    const fd = new FormData();
                    fd.append("item_id", itemId);
                    fd.append("note", newText);

                    fetch("/api/update-note/", {
                        method: "POST",
                        headers: { "X-CSRFToken": csrftoken },
                        body: fd,
                    })
                        .then(r => r.json())
                        .then(data => {
                            if (!data.ok) {
                                console.error("Inline note update failed:", data.error);
                                td.removeChild(textarea);
                                container.style.display = "";
                                td.classList.remove("sb-inline-editing");
                            } else {
                                btn.dataset.note = newText;

                                const plain = newText.trim();
                                btn.dataset.hasNote = plain.length > 0 ? "1" : "0";
                                if (plain.length > 0) {
                                    btn.classList.add("sb-note-has-content");
                                } else {
                                    btn.classList.remove("sb-note-has-content");
                                }

                                if (preview) {
                                    const htmlNew = newText.replace(/\n/g, "<br>");
                                    preview.innerHTML = htmlNew;
                                    preview.setAttribute("title", plain);
                                }

                                markClampedCells();
                                td.removeChild(textarea);
                                container.style.display = "";
                                td.classList.remove("sb-inline-editing");
                                setActiveCellState("saved", td);
                            }
                        })
                        .catch(err => {
                            console.error("Inline note update error:", err);
                            td.removeChild(textarea);
                            container.style.display = "";
                            td.classList.remove("sb-inline-editing");
                        });
                };

                textarea.addEventListener("keydown", function (e2) {
                    if (e2.key === "Enter" && (e2.ctrlKey || e2.metaKey)) {
                        const pos = textarea.selectionStart;
                        const val = textarea.value;
                        textarea.value = val.slice(0, pos) + "\n" + val.slice(pos);
                        textarea.selectionStart = textarea.selectionEnd = pos + 1;
                        e2.preventDefault();
                    } else if (e2.key === "Enter") {
                        e2.preventDefault();
                        finishNote(true);
                    } else if (e2.key === "Escape") {
                        e2.preventDefault();
                        finishNote(false);
                    }
                });

                textarea.addEventListener("blur", function () {
                    finishNote(true);
                });
            });
        });
    }


    /* ================================================
       QUILL MODAL (DESCRIPTION + USER NOTE)
       - tylko dla CAN_EDIT
       (Tylko z przyciskow ? i ?)
    ================================================= */
    function sbInitQuillModal() {
        // tylko edytor / purchase_manager maja Quill
        if (!window.CAN_EDIT) return;

        const modal = document.getElementById("sb-quill-modal");
        if (!modal || !window.Quill) return;

        const dialog = modal.querySelector(".sb-modal-dialog");
        const closeBtn = modal.querySelector(".sb-modal-close");
        const cancelBtn = modal.querySelector(".sb-modal-cancel");
        const saveBtn = modal.querySelector(".sb-modal-save");
        const editorNode = document.getElementById("sb-quill-editor");

        if (!dialog || !editorNode) return;

        const titleDesc = document.getElementById("sb-modal-title-description");
        const titleNote = document.getElementById("sb-modal-title-note");

        const csrftoken = getCookie("csrftoken");

        // Quill inicjalizujemy tylko raz, zeby nie doklejal kolejnych toolbarow
        if (!quillInstance) {
            quillInstance = new Quill(editorNode, {
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
        }

        const state = {
            currentItemId: null,
            mode: "description", // "description" | "note"
            currentCell: null,
            noteButton: null,
            modal: modal,
        };

        function updateModalTitle(mode) {
            if (!titleDesc || !titleNote) return;

            if (mode === "note") {
                titleDesc.style.display = "none";
                titleNote.style.display = "";
            } else {
                titleDesc.style.display = "";
                titleNote.style.display = "none";
            }
        }

        function hideModal(clearState = false) {
            if (clearState) {
                clearActiveCellState();
            }

            state.modal.style.display = "none";
            state.currentItemId = null;
            state.currentCell = null;
            state.noteButton = null;
            state.mode = "description";
            updateModalTitle("description");
        }

        /**
         * Otwiera modal:
         *  mode: "description" | "note"
         *  itemId: ID rekordu
         *  html: tresc HTML do zaladowania do Quilla
         *  targetElement: komorka <td> (dla description) albo przycisk ? (dla note)
         */
        function openModal(mode, itemId, html, targetElement) {
            state.mode = mode || "description";
            state.currentItemId = itemId || null;
            state.currentCell = null;
            state.noteButton = null;

            if (state.mode === "description") {
                state.currentCell = targetElement || null;
            } else if (state.mode === "note") {
                state.noteButton = targetElement || null;
            }

            const targetCell = state.mode === "description"
                ? state.currentCell
                : (state.noteButton ? state.noteButton.closest("td") : null);

            if (targetCell) {
                setActiveCellState("edited", targetCell);
            }

            updateModalTitle(state.mode);

            quillInstance.root.innerHTML = html || "";
            state.modal.style.display = "flex";
        }

        // globalny ?otwieracz" uzywany przez przyciski ? i ?
        window.sbOpenQuillEditor = openModal;

        if (closeBtn) closeBtn.addEventListener("click", () => hideModal(true));
        if (cancelBtn) cancelBtn.addEventListener("click", () => hideModal(true));

        modal.addEventListener("click", function (e) {
            if (e.target === modal) {
                hideModal(true);
            }
        });

        if (saveBtn) {
            saveBtn.addEventListener("click", function () {
                if (!state.currentItemId) {
                    hideModal();
                    return;
                }

                const html = quillInstance.root.innerHTML.trim();

                // --- DESCRIPTION MODE ---
                if (state.mode === "description") {
                    const cell = state.currentCell;

                    const fd = new FormData();
                    fd.append("item_id", state.currentItemId);
                    fd.append("field", "part_description");
                    fd.append("value", html);

                    fetch("/api/update-field/", {
                        method: "POST",
                        headers: { "X-CSRFToken": csrftoken || "" },
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
                                    const tmp = document.createElement("div");
                                    tmp.innerHTML = html;
                                    preview.setAttribute("title", tmp.textContent.trim());
                                }
                                // po zmianie opisu odswiezamy clamp
                                if (typeof markClampedCells === "function") {
                                    markClampedCells();
                                }
                                setActiveCellState("saved", cell);
                            }
                            hideModal();
                        })
                        .catch(err => {
                            console.error("Quill save (description) error:", err);
                            hideModal();
                        });
                }

                // --- NOTE MODE ---
                else if (state.mode === "note") {
                    const btn = state.noteButton;

                    const fd = new FormData();
                    fd.append("item_id", state.currentItemId);
                    fd.append("note", html);

                    fetch("/api/update-note/", {
                        method: "POST",
                        headers: { "X-CSRFToken": csrftoken || "" },
                        body: fd,
                    })
                        .then(r => r.json())
                        .then(data => {
                            if (!data.ok) {
                                console.error("Quill save (note) failed:", data.error);
                            } else if (btn) {
                                btn.dataset.note = html;

                                const tmp = document.createElement("div");
                                tmp.innerHTML = html;
                                const plain = tmp.textContent.trim();

                                btn.dataset.hasNote = plain.length > 0 ? "1" : "0";
                                if (plain.length > 0) {
                                    btn.classList.add("sb-note-has-content");
                                } else {
                                    btn.classList.remove("sb-note-has-content");
                                }

                                const targetCell = btn.closest("td");
                                const preview = targetCell ? targetCell.querySelector(".sb-note-preview") : null;
                                if (preview) {
                                    preview.innerHTML = html;
                                    preview.setAttribute("title", plain);
                                }
                                markClampedCells();

                                if (targetCell) {
                                    setActiveCellState("saved", targetCell);
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



    /* ================================================
       QUILL TRIGGERS (tylko przyciski ?, tylko CAN_EDIT)
    ================================================= */
    function sbInitQuillTriggers() {
        if (!CAN_EDIT) return;

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
               SORTING (R, S, NAME, GROUP) + LOADING SPINNER
            ================================================= */

            function sbInitSorting() {
                const table = document.querySelector(".sb-table");
                if (!table) return;

                const currentSort = table.dataset.currentSort || "rack";
                const currentDir = table.dataset.currentDir || "asc";

                const headers = table.querySelectorAll("thead .sb-sortable-header");
                if (!headers.length) return;

                headers.forEach(th => {
                    const field = th.dataset.sortField;
                    if (!field) return;

                    th.addEventListener("click", function (e) {
                        e.preventDefault();

                        const rackSelect = document.querySelector(".sb-filter-rack");
                        const activeRack = rackSelect ? rackSelect.value : currentRackFilter;

                        // Dodajemy klas? "loading" do tabeli i klikni?tego naglowka
                        table.classList.add("sb-table-sorting");
                        headers.forEach(h => h.classList.remove("sb-sort-loading"));
                        th.classList.add("sb-sort-loading");

                        let nextDir = "asc";
                        if (field === currentSort) {
                            nextDir = currentDir === "asc" ? "desc" : "asc";
                        }

                        const url = new URL(window.location.href);
                        url.searchParams.set("sort", field);
                        url.searchParams.set("dir", nextDir);

                        // Przy zmianie sortowania wracamy na stron? 1
                        url.searchParams.set("page", 1);

                        if (activeRack) {
                            url.searchParams.set("rack_filter", activeRack);
                            url.searchParams.set("page_size", "all");
                        }

                        const ps = document.getElementById("page-size-select");
                        if (ps) {
                            if (!activeRack) {
                                url.searchParams.set("page_size", ps.value);
                            }
                        }

                        sbLoadInventory(url.toString());
                    });
                });
            }


    /* ================================================
       AJAX PAGINATION + PAGE SIZE
    ================================================= */
    function sbLoadInventory(url, opts = {}) {
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
                clearActiveCellState();

                const newWrapper = document.querySelector(".sb-table-wrapper");
                if (newWrapper) {
                    newWrapper.scrollLeft = scrollState.left;
                    newWrapper.scrollTop = scrollState.top;
                }

                // re-init features
                syncBodyDarkClass();
                markClampedCells();
                sbInitCellFocusTracking();
                sbInitUnitDropdowns();
                sbInitGroupDropdowns();
                sbInitConditionDropdowns();
                sbInitRevDiscCheckboxes();
                sbInitFavorites();
                sbInitInlineEditing();
                sbInitSorting();
                sbInitRackFilter();
                sbInitGroupFilter();
                sbInitInlineDescNoteEditing();
                sbInitPagination();
                sbInitQuillModal();
                sbInitQuillTriggers();
                sbInitNoteButtons();
                sbInitAddItemModal();
                sbInitDeleteModal();
                applyPendingHighlight();
                updateHeaderCountFromCard();
                if (typeof opts.onLoaded === "function") {
                    opts.onLoaded();
                }
            })
            .catch(err => {
                console.error("Pagination AJAX error:", err);
                if (typeof opts.onError === "function") {
                    opts.onError(err);
                }
                window.location.href = url;
            });
    }

    /* ================================================
       AJAX PAGINATION + PAGE SIZE
       (trzyma sort + dir)
    ================================================= */
    function sbInitPagination() {
        const table = document.querySelector(".sb-table");
        let currentSort = table ? (table.dataset.currentSort || "rack") : "rack";
        let currentDir = table ? (table.dataset.currentDir || "asc") : "asc";
        const rackSelect = document.querySelector(".sb-filter-rack");
        const currentRackFilter = rackSelect ? rackSelect.value : (table ? (table.dataset.rackFilter || "") : "");

        if (table) {
            currentSort = table.dataset.currentSort || "rack";
            currentDir = table.dataset.currentDir || "asc";
        }

        // --- dropdown Rows per page ---
        const sizeSelect = document.getElementById("page-size-select");
        if (sizeSelect) {
            sizeSelect.addEventListener("change", function () {
                const pageSize = this.value;
                const url = new URL(window.location.href);

                url.searchParams.set("page", 1);
                url.searchParams.set("page_size", pageSize);
                url.searchParams.set("sort", currentSort);
                url.searchParams.set("dir", currentDir);

                sbLoadInventory(url.toString());
            });
        }

        // --- linki paginacji 1,2,3,<<,>> ---
        const pagerLinks = document.querySelectorAll(".sb-pagination .sb-page-link[data-page]");
        pagerLinks.forEach(link => {
            link.addEventListener("click", function (e) {
                e.preventDefault();
                const targetPage = this.dataset.page;
                if (!targetPage) return;

                const rackSelect = document.querySelector(".sb-filter-rack");
                const activeRack = rackSelect ? rackSelect.value : currentRackFilter;

                const url = new URL(window.location.href);
                url.searchParams.set("page", targetPage);
                url.searchParams.set("sort", currentSort);
                url.searchParams.set("dir", currentDir);
                if (activeRack) {
                    url.searchParams.set("rack_filter", activeRack);
                    url.searchParams.set("page_size", "all");
                }

                const ps = document.getElementById("page-size-select");
                if (ps) {
                    if (!activeRack) {
                        url.searchParams.set("page_size", ps.value);
                    }
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
        const body = document.body;
        const willDark = !root.classList.contains("sb-dark");

        if (willDark) {
            root.classList.add("sb-dark");
            root.classList.remove("sb-light");
            if (body) {
                body.classList.add("sb-dark");
                body.classList.remove("sb-light");
            }
        } else {
            root.classList.remove("sb-dark");
            root.classList.add("sb-light");
            if (body) {
                body.classList.remove("sb-dark");
                body.classList.add("sb-light");
            }
        }

        try {
            localStorage.setItem(KEY, willDark ? "dark" : "light");
        } catch (e) {}
    };

    /* ================================================
       INIT
    ================================================= */
    document.addEventListener("DOMContentLoaded", function () {
        syncBodyDarkClass();
        markClampedCells();
        sbInitCellFocusTracking();
        sbInitUnitDropdowns();
        sbInitGroupDropdowns();
        sbInitConditionDropdowns();
        sbInitRevDiscCheckboxes();
        sbInitFavorites();
        sbInitInlineEditing();
        sbInitSorting();
        sbInitRackFilter();
        sbInitGroupFilter();
        sbInitInlineDescNoteEditing();
        sbInitPagination();
        sbInitQuillModal();
        sbInitQuillTriggers();
        sbInitNoteButtons();
        sbInitAddItemModal();
        sbInitDeleteModal();
        applyPendingHighlight();
    });
})();
