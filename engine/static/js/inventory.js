(function () {
    const KEY = "stockbrain_theme";
    let quillInstance = null;  // single global Quill instance for modal

    // Global flag from Django context: can user edit inventory fields?
    const CAN_EDIT = !!(window && window.CAN_EDIT);
    const HIGHLIGHT_KEY = "sb_new_item_highlight";
    const UPPERCASE_KEY = "sb_uppercase_mode";
    let progressTimer = null;
    let progressStartedAt = 0;

    const CELL_STATE_CLASSES = {
        focus: "sb-cell-focus",
        edited: "sb-cell-edited",
        saved: "sb-cell-saved",
    };
    let focusModeEnabled = true;
    let lastCrossColClass = null;
    let lastCrossRow = null;

    let activeCellState = { cell: null, type: null };

    const ROW_CROSS_CLASS = {
        focus: "sb-row-focus",
        edited: "sb-row-edited",
        saved: "sb-row-saved",
    };
    const COL_CROSS_CLASS = {
        focus: "sb-col-focus",
        edited: "sb-col-edited",
        saved: "sb-col-saved",
    };

    function getPrimaryColClass(cell) {
        if (!cell) return null;
        const cls = Array.from(cell.classList || []).find(c => c.startsWith("col-"));
        return cls || null;
    }

    function clearFocusCross() {
        if (lastCrossRow) {
            lastCrossRow.classList.remove("sb-row-focus", "sb-row-edited", "sb-row-saved");
            lastCrossRow = null;
        }
        if (lastCrossColClass) {
            document.querySelectorAll("." + lastCrossColClass).forEach(el => {
                el.classList.remove("sb-col-focus", "sb-col-edited", "sb-col-saved");
            });
            lastCrossColClass = null;
        }
    }

    function applyFocusCross(cell, stateKey) {
        if (!focusModeEnabled || !cell) return;
        clearFocusCross();
        const row = cell.closest("tr");
        const colCls = getPrimaryColClass(cell);
        if (row && ROW_CROSS_CLASS[stateKey]) {
            row.classList.add(ROW_CROSS_CLASS[stateKey]);
            lastCrossRow = row;
        }
        if (colCls && COL_CROSS_CLASS[stateKey]) {
            document.querySelectorAll("." + colCls).forEach(el => {
                el.classList.add(COL_CROSS_CLASS[stateKey]);
            });
            lastCrossColClass = colCls;
        }
    }

    function clearActiveCellState() {
        clearFocusCross();
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

        applyFocusCross(cell, type);
    }

    /* ================================================
       APPLY THEME EARLY (no flash)
       Default: sb-light; when stored: sb-dark
    ================================================= */
    (function applyInitialTheme() {
        const root = document.documentElement;
        const body = document.body;
        // Default to dark
        root.classList.add("sb-dark");
        if (body) body.classList.add("sb-dark");
        try {
            if (localStorage.getItem(KEY) === "light") {
                root.classList.remove("sb-dark");
                root.classList.add("sb-light");
                if (body) {
                    body.classList.remove("sb-dark");
                    body.classList.add("sb-light");
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
       FILTER HELPERS
    ================================================= */
    function getTableFilters() {
        const table = document.querySelector(".sb-table");
        if (!table) return {};
        return {
            rack: table.dataset.rackFilter || "",
            group: table.dataset.groupFilter || "",
            condition: table.dataset.conditionFilter || "",
            unit: table.dataset.unitFilter || "",
            instock: table.dataset.instockFilter || "",
            price: table.dataset.priceFilter || "",
            disc: table.dataset.discFilter || "",
            rev: table.dataset.revFilter || "",
            fav: table.dataset.favFilter || "",
            reorder: table.dataset.reorderFilter || "",
            search: table.dataset.search || "",
            searchFields: table.dataset.searchFields || "",
            sort: table.dataset.currentSort || "rack",
            dir: table.dataset.currentDir || "asc",
        };
    }

    function readSelectValue(selector, fallback) {
        if (selector && selector.value) return selector.value;
        return fallback || "";
    }

    function getActiveSearchFields(clearAll = false) {
        if (clearAll) return [];
        const icons = document.querySelectorAll(".sb-filter-icon[data-search-field]");
        const active = Array.from(icons)
            .filter(icon => !icon.classList.contains("is-muted"))
            .map(icon => icon.dataset.searchField)
            .filter(Boolean);
        return active;
    }

    function collectActiveFilters({ clearAll = false, clearSearch = false, forceAll = false } = {}) {
        const defaults = getTableFilters();
        const rackSelect = document.querySelector(".sb-filter-rack");
        const groupSelect = document.querySelector(".sb-filter-group");
        const conditionSelect = document.querySelector(".sb-filter-condition");
        const unitSelect = document.querySelector(".sb-filter-unit");
        const instockSelect = document.querySelector(".sb-filter-instock");
        const priceSelect = document.querySelector(".sb-filter-price");
        const discSelect = document.querySelector(".sb-filter-disc");
        const revSelect = document.querySelector(".sb-filter-rev");
        const favSelect = document.querySelector(".sb-filter-fav");
        const reorderSelect = document.querySelector(".sb-filter-reorder");
        const searchInput = document.getElementById("sb-search-input");

        const filters = {
            rack: clearAll ? "" : readSelectValue(rackSelect, defaults.rack),
            group: clearAll ? "" : readSelectValue(groupSelect, defaults.group),
            condition: clearAll ? "" : readSelectValue(conditionSelect, defaults.condition),
            unit: clearAll ? "" : readSelectValue(unitSelect, defaults.unit),
            instock: clearAll ? "" : readSelectValue(instockSelect, defaults.instock),
            price: clearAll ? "" : readSelectValue(priceSelect, defaults.price),
            disc: clearAll ? "" : readSelectValue(discSelect, defaults.disc),
            rev: clearAll ? "" : readSelectValue(revSelect, defaults.rev),
            fav: clearAll ? "" : readSelectValue(favSelect, defaults.fav),
            reorder: clearAll ? "" : readSelectValue(reorderSelect, defaults.reorder),
            search: clearAll || clearSearch ? "" : (searchInput ? searchInput.value.trim() : defaults.search),
            searchFields: forceAll ? ["__all__"] : getActiveSearchFields(clearAll),
            sort: defaults.sort,
            dir: defaults.dir,
        };
        return filters;
    }

    function applyFiltersToUrl(url, filters) {
        url.searchParams.set("sort", filters.sort || "rack");
        url.searchParams.set("dir", filters.dir || "asc");
        url.searchParams.set("page", 1);

        const entries = [
            ["rack_filter", filters.rack],
            ["group_filter", filters.group],
            ["condition_filter", filters.condition],
            ["unit_filter", filters.unit],
            ["instock_filter", filters.instock],
            ["price_filter", filters.price],
            ["disc_filter", filters.disc],
            ["rev_filter", filters.rev],
            ["fav_filter", filters.fav],
            ["reorder_filter", filters.reorder],
            ["search", filters.search],
        ];
        entries.forEach(([key, val]) => {
            if (val) url.searchParams.set(key, val);
            else url.searchParams.delete(key);
        });

        if (filters.searchFields && filters.searchFields.length) {
            url.searchParams.set("search_fields", filters.searchFields.join(","));
        } else {
            url.searchParams.delete("search_fields");
        }

        const anyFilter = Object.keys(filters).some(key => {
            if (["searchFields", "sort", "dir"].includes(key)) return false;
            return !!filters[key];
        });

        const pageSizeSel = document.getElementById("page-size-select");
        if (anyFilter) {
            url.searchParams.set("page_size", "all");
        } else if (pageSizeSel && pageSizeSel.value) {
            url.searchParams.set("page_size", pageSizeSel.value);
        } else {
            url.searchParams.delete("page_size");
        }
    }

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

        select.addEventListener("change", function () {
            const url = new URL(window.location.href);
            const filters = collectActiveFilters();
            filters.rack = this.value || "";
            applyFiltersToUrl(url, filters);
            sbLoadInventory(url.toString());
        });
    }

    function sbInitConditionFilter() {
        const select = document.querySelector(".sb-filter-condition");
        const table = document.querySelector(".sb-table");
        if (!select || !table) return;

        select.addEventListener("change", function () {
            const url = new URL(window.location.href);
            const filters = collectActiveFilters();
            filters.condition = this.value || "";
            applyFiltersToUrl(url, filters);
            sbLoadInventory(url.toString());
        });
    }

    function sbInitSimpleFilter(selector, key) {
        const select = document.querySelector(selector);
        const table = document.querySelector(".sb-table");
        if (!select || !table) return;

        select.addEventListener("change", function () {
            const url = new URL(window.location.href);
            const filters = collectActiveFilters();
            filters[key] = this.value || "";
            applyFiltersToUrl(url, filters);
            sbLoadInventory(url.toString());
        });
    }

    function sbInitFilterIcons(context) {
        const scope = context || document;
        const icons = scope.querySelectorAll(".sb-filter-icon");
        if (!icons.length) return;

        icons.forEach(icon => {
            icon.addEventListener("click", () => {
                icon.classList.toggle("is-muted");
            });
        });
    }

    function sbInitGroupFilter() {
        const select = document.querySelector(".sb-filter-group");
        const table = document.querySelector(".sb-table");
        if (!select || !table) return;

        select.addEventListener("change", function () {
            const url = new URL(window.location.href);
            const filters = collectActiveFilters();
            filters.group = this.value || "";
            applyFiltersToUrl(url, filters);
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
            const row = el.closest(".sb-row");

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

            // Kolor wiersza = kolor gwiazdki (tylko gdy aktywna)
            if (row) {
                row.classList.remove("sb-row-fav-red", "sb-row-fav-green", "sb-row-fav-yellow", "sb-row-fav-blue");
                row.style.color = ""; // reset
                if (color === "RED") {
                    row.classList.add("sb-row-fav-red");
                } else if (color === "GREEN") {
                    row.classList.add("sb-row-fav-green");
                } else if (color === "YELLOW") {
                    row.classList.add("sb-row-fav-yellow");
                } else if (color === "BLUE") {
                    row.classList.add("sb-row-fav-blue");
                }
            }
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

    /* ================================================
       UPPERCASE VIEW TOGGLE
    ================================================= */
    function applyUppercaseMode(isOn) {
        const tables = document.querySelectorAll(".sb-table-inventory");
        tables.forEach(t => t.classList.toggle("uppercase-mode", isOn));
        const btn = document.getElementById("sb-uppercase-toggle");
        if (btn) {
            btn.classList.toggle("is-active", isOn);
            btn.setAttribute("aria-pressed", isOn ? "true" : "false");
        }
    }

    function sbInitUppercaseToggle() {
        const btn = document.getElementById("sb-uppercase-toggle");
        let stored = false;
        try {
            stored = localStorage.getItem(UPPERCASE_KEY) === "1";
        } catch (e) {}
        applyUppercaseMode(stored);

        if (!btn) return;
        btn.addEventListener("click", () => {
            stored = !stored;
            applyUppercaseMode(stored);
            try {
                localStorage.setItem(UPPERCASE_KEY, stored ? "1" : "0");
            } catch (e) {}
        });
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
       PROGRESS BAR (AJAX LOADING)
    ================================================= */
    function getProgressEls() {
        const container = document.querySelector(".sb-progress");
        const bar = container ? container.querySelector(".sb-progress-bar") : null;
        return { container, bar };
    }

    function sbProgressStart() {
        const { container, bar } = getProgressEls();
        if (!container || !bar) return;
        if (progressTimer) {
            clearInterval(progressTimer);
            progressTimer = null;
        }
        container.style.display = "block";
        progressStartedAt = Date.now();
        // reset transition to allow immediate paint
        bar.style.transition = "none";
        bar.style.width = "0%";
        // force reflow
        void bar.offsetWidth;
        // restore transition
        bar.style.transition = "width 0.15s ease";
        // show a visible chunk immediately
        requestAnimationFrame(() => {
            bar.style.width = "30%";
            let current = 30;
            progressTimer = setInterval(() => {
                current = Math.min(current + Math.random() * 12, 90);
                bar.style.width = `${current}%`;
            }, 120);
        });
    }

    function sbProgressFinish() {
        const { container, bar } = getProgressEls();
        if (!container || !bar) return;
        if (progressTimer) {
            clearInterval(progressTimer);
            progressTimer = null;
        }
        const finalize = () => {
            bar.style.width = "100%";
            setTimeout(() => {
                bar.style.width = "0%";
                container.style.display = "none";
            }, 400);
        };

        const elapsed = Date.now() - progressStartedAt;
        if (elapsed < 250) {
            setTimeout(finalize, 250 - elapsed);
        } else {
            finalize();
        }
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
       USER PROFILE MODAL (edit e-mail / preferred name)
    ================================================= */
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

        const usernameEl = modal.querySelector("#sb-user-username");
        const firstEl = modal.querySelector("#sb-user-first");
        const lastEl = modal.querySelector("#sb-user-last");
        const emailEl = modal.querySelector("#sb-user-email");
        const prefEl = modal.querySelector("#sb-user-preferred");
        const oldPwEl = modal.querySelector("#sb-user-oldpw");
        const newPwEl = modal.querySelector("#sb-user-newpw");
        const newPw2El = modal.querySelector("#sb-user-newpw2");

        let isOpen = false;

        function showError(msg) {
            if (!errBox) return;
            errBox.textContent = msg || "";
            errBox.style.display = msg ? "block" : "none";
        }

        function fillUser(data) {
            const u = (data && data.user) || {};
            if (usernameEl) usernameEl.value = u.username || "";
            if (firstEl) firstEl.value = u.first_name || "";
            if (lastEl) lastEl.value = u.last_name || "";
            if (emailEl) emailEl.value = u.email || "";
            if (prefEl) prefEl.value = u.preferred_name || "";
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
        if (cancelBtn) cancelBtn.addEventListener("click", function (e) {
            e.preventDefault();
            closeModal();
        });

        modal.addEventListener("mousedown", handleOutside);
        document.addEventListener("keydown", handleKey);

        if (form) {
            form.addEventListener("submit", function (e) {
                e.preventDefault();
                showError("");
                const fd = new URLSearchParams();
                fd.append("email", emailEl ? (emailEl.value || "").trim() : "");
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

        // Do not close modal when clicking outside dialog

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
                textarea.addEventListener("keyup", function (e) {
                    if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) {
                        e.preventDefault();
                        finish(true);
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
                textarea.addEventListener("keyup", function (e2) {
                    if (e2.key === "Enter" && !e2.ctrlKey && !e2.metaKey) {
                        e2.preventDefault();
                        finish(true);
                    }
                });
                    textarea.addEventListener("keyup", function (e2) {
                        if (e2.key === "Enter" && !e2.ctrlKey && !e2.metaKey) {
                            e2.preventDefault();
                            finish(true);
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
       SORTING (HEADERS) + LOADING SPINNER
    ================================================= */
    function sbInitSorting() {
        const table = document.querySelector(".sb-table");
        if (!table) return;

        const headers = table.querySelectorAll("thead .sb-sortable-header");
        if (!headers.length) return;

        headers.forEach(th => {
            const field = th.dataset.sortField;
            if (!field) return;

            th.addEventListener("click", function (e) {
                e.preventDefault();

                const baseFilters = getTableFilters();

                // Dodajemy klasę "loading" do tabeli i klikniętego nagłówka
                table.classList.add("sb-table-sorting");
                headers.forEach(h => h.classList.remove("sb-sort-loading"));
                th.classList.add("sb-sort-loading");

                let nextDir = "asc";
                if (field === baseFilters.sort) {
                    nextDir = baseFilters.dir === "asc" ? "desc" : "asc";
                }

                const url = new URL(window.location.href);
                const filters = collectActiveFilters();
                filters.sort = field;
                filters.dir = nextDir;
                applyFiltersToUrl(url, filters);

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

        sbProgressStart();

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
                sbInitConditionFilter();
                sbInitSimpleFilter(".sb-filter-unit", "unit");
                sbInitSimpleFilter(".sb-filter-instock", "instock");
                sbInitSimpleFilter(".sb-filter-price", "price");
                sbInitSimpleFilter(".sb-filter-disc", "disc");
                sbInitSimpleFilter(".sb-filter-rev", "rev");
                sbInitSimpleFilter(".sb-filter-fav", "fav");
                sbInitSimpleFilter(".sb-filter-reorder", "reorder");
                sbInitFilterIcons(newCard);
                sbInitSearch();
                sbInitInlineDescNoteEditing();
                sbInitPagination();
                sbInitQuillModal();
                sbInitQuillTriggers();
                sbInitNoteButtons();
                sbInitAddItemModal();
                sbInitDeleteModal();
                sbInitUppercaseToggle();
                applyPendingHighlight();
                updateHeaderCountFromCard();
                sbSyncUrlWithState();
                sbProgressFinish();
                if (typeof opts.onLoaded === "function") {
                    opts.onLoaded();
                }
            })
            .catch(err => {
                console.error("Pagination AJAX error:", err);
                sbProgressFinish();
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
        const defaults = getTableFilters();

        // --- dropdown Rows per page ---
        const sizeSelect = document.getElementById("page-size-select");
        if (sizeSelect) {
            sizeSelect.addEventListener("change", function () {
                const pageSize = this.value;
                const url = new URL(window.location.href);
                const filters = collectActiveFilters();
                filters.sort = defaults.sort;
                filters.dir = defaults.dir;
                applyFiltersToUrl(url, filters);
                url.searchParams.set("page_size", pageSize);
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

                const url = new URL(window.location.href);
                const filters = collectActiveFilters();
                filters.sort = defaults.sort;
                filters.dir = defaults.dir;
                applyFiltersToUrl(url, filters);
                url.searchParams.set("page", targetPage);

                sbLoadInventory(url.toString());
            });
        });
    }

    /* ================================================
       SEARCH BAR
    ================================================= */
    function sbInitSearch() {
        const input = document.getElementById("sb-search-input");
        if (!input) return;

        const table = document.querySelector(".sb-table");
        const currentSort = table ? (table.dataset.currentSort || "rack") : "rack";
        const currentDir = table ? (table.dataset.currentDir || "asc") : "asc";
        const currentRackFilter = table ? (table.dataset.rackFilter || "") : "";
        const currentGroupFilter = table ? (table.dataset.groupFilter || "") : "";
        const currentSearch = table ? (table.dataset.search || "") : "";
        const currentConditionFilter = table ? (table.dataset.conditionFilter || "") : "";

        const searchBtn = document.getElementById("sb-search-btn");
        const advBtn = document.getElementById("sb-advanced-search-btn");
        const clearBtn = document.getElementById("sb-search-clear-btn");
        const clearAllBtn = document.getElementById("sb-search-clear-all-btn");
        const pageSizeSel = document.getElementById("page-size-select");
        const focusToggle = document.getElementById("sb-focus-toggle-btn");

        function buildUrl({ clearSearch = false, clearAll = false, forceAll = false } = {}) {
            const url = new URL(window.location.href);
            const filters = collectActiveFilters({ clearAll, clearSearch, forceAll });
            filters.search = clearAll || clearSearch ? "" : (input.value || "").trim();
            filters.sort = currentSort;
            filters.dir = currentDir;
            applyFiltersToUrl(url, filters);
            if (clearAll) {
                url.searchParams.set("page_size", "100");
            }
            return url;
        }

        function runSearch(forceAll = false) {
            const url = buildUrl({ clearSearch: false, clearAll: false, forceAll });
            sbLoadInventory(url.toString());
        }

        function clearSearch() {
            input.value = "";
            const url = buildUrl({ clearSearch: true, clearAll: false });
            sbLoadInventory(url.toString());
        }

        function clearAll() {
            input.value = "";
            // reset dropdowns UI
            const selects = document.querySelectorAll(".sb-header-filter-row select");
            selects.forEach(sel => { sel.value = ""; });
            // reset search field toggles to active
            document.querySelectorAll(".sb-filter-icon[data-search-field]").forEach(icon => {
                icon.classList.remove("is-muted");
            });
            // reset page size to 100 in UI
            if (pageSizeSel) pageSizeSel.value = "100";

            const url = buildUrl({ clearSearch: true, clearAll: true });
            sbLoadInventory(url.toString());
        }

        input.addEventListener("keydown", e => {
            if (e.key === "Enter") {
                e.preventDefault();
                runSearch();
            }
        });

        if (searchBtn) searchBtn.addEventListener("click", () => runSearch(false));
        if (advBtn) advBtn.addEventListener("click", () => runSearch(true));
        if (clearBtn) clearBtn.addEventListener("click", clearSearch);
        if (clearAllBtn) clearAllBtn.addEventListener("click", clearAll);
        if (focusToggle) {
            focusToggle.addEventListener("click", () => {
                const isInactive = focusToggle.classList.toggle("is-inactive");
                focusToggle.setAttribute("aria-pressed", (!isInactive).toString());
                focusModeEnabled = !isInactive;
                if (!focusModeEnabled) {
                    clearFocusCross();
                } else if (activeCellState.cell && activeCellState.type) {
                    applyFocusCross(activeCellState.cell, activeCellState.type);
                }
            });
        }

        // ustaw wartość startową
        if (currentSearch && !input.value) {
            input.value = currentSearch;
        }
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
        updateThemeIcon();
    };

    function updateThemeIcon() {
        const btn = document.querySelector(".sb-theme-btn");
        if (!btn) return;
        const isDark = document.documentElement.classList.contains("sb-dark");
        btn.textContent = isDark ? "☀️" : "🌙";
    }

    document.addEventListener("DOMContentLoaded", updateThemeIcon);

    /* ================================================
       COUNTDOWN TO STANDARD END TIME (header)
    ================================================= */
    function updateEndCountdown() {
        const el = document.querySelector(".sb-countdown");
        if (!el) return;
        const endStr = el.dataset.end;
        if (!endStr) return;
        const [hh, mm] = endStr.split(":").map(Number);
        if (Number.isNaN(hh) || Number.isNaN(mm)) return;

        // Current time in Kuwait using Intl (avoid parsing issues)
        const fmt = new Intl.DateTimeFormat("en-GB", {
            timeZone: "Asia/Kuwait",
            hour12: false,
            hour: "2-digit",
            minute: "2-digit",
        });
        const parts = fmt.formatToParts(new Date());
        const curH = parseInt(parts.find(p => p.type === "hour")?.value || "0", 10);
        const curM = parseInt(parts.find(p => p.type === "minute")?.value || "0", 10);

        const nowMinutes = curH * 60 + curM;
        const endMinutes = hh * 60 + mm;
        let diffMinutes = endMinutes - nowMinutes;
        // if already past, count to next day's end time instead of showing 0
        if (diffMinutes < 0) diffMinutes += 24 * 60;

        const hours = Math.floor(diffMinutes / 60);
        const minutes = diffMinutes % 60;
        el.textContent = `${hours}:${minutes.toString().padStart(2, "0")}`;
    }

    document.addEventListener("DOMContentLoaded", () => {
        updateEndCountdown();
        setInterval(updateEndCountdown, 30000);
    });

    // =================================================
    // SYNC URL Z AKTUALNYM STANEM (filtry, page_size, szukanie)
    // =================================================
    function sbSyncUrlWithState() {
        const table = document.querySelector(".sb-table");
        if (!table) return;

        const url = new URL(window.location.href);
        const rackFilter = table.dataset.rackFilter || "";
        const groupFilter = table.dataset.groupFilter || "";
        const conditionFilter = table.dataset.conditionFilter || "";
        const unitFilter = table.dataset.unitFilter || "";
        const instockFilter = table.dataset.instockFilter || "";
        const priceFilter = table.dataset.priceFilter || "";
        const discFilter = table.dataset.discFilter || "";
        const revFilter = table.dataset.revFilter || "";
        const favFilter = table.dataset.favFilter || "";
        const reorderFilter = table.dataset.reorderFilter || "";
        const searchVal = table.dataset.search || "";
        const searchFields = table.dataset.searchFields || "";
        const sortField = table.dataset.currentSort || "rack";
        const sortDir = table.dataset.currentDir || "asc";
        const pageParam = url.searchParams.get("page");
        const pageSizeSel = document.getElementById("page-size-select");
        const pageSizeVal = pageSizeSel ? pageSizeSel.value : "";

        url.searchParams.set("sort", sortField);
        url.searchParams.set("dir", sortDir);
        if (!pageParam) {
            url.searchParams.set("page", 1);
        }
        if (rackFilter) url.searchParams.set("rack_filter", rackFilter);
        else url.searchParams.delete("rack_filter");
        if (groupFilter) url.searchParams.set("group_filter", groupFilter);
        else url.searchParams.delete("group_filter");
        if (conditionFilter) url.searchParams.set("condition_filter", conditionFilter);
        else url.searchParams.delete("condition_filter");
        if (unitFilter) url.searchParams.set("unit_filter", unitFilter);
        else url.searchParams.delete("unit_filter");
        if (instockFilter) url.searchParams.set("instock_filter", instockFilter);
        else url.searchParams.delete("instock_filter");
        if (priceFilter) url.searchParams.set("price_filter", priceFilter);
        else url.searchParams.delete("price_filter");
        if (discFilter) url.searchParams.set("disc_filter", discFilter);
        else url.searchParams.delete("disc_filter");
        if (revFilter) url.searchParams.set("rev_filter", revFilter);
        else url.searchParams.delete("rev_filter");
        if (favFilter) url.searchParams.set("fav_filter", favFilter);
        else url.searchParams.delete("fav_filter");
        if (reorderFilter) url.searchParams.set("reorder_filter", reorderFilter);
        else url.searchParams.delete("reorder_filter");
        if (searchVal) url.searchParams.set("search", searchVal);
        else url.searchParams.delete("search");
        if (searchFields) url.searchParams.set("search_fields", searchFields);
        else url.searchParams.delete("search_fields");
        if (pageSizeVal) url.searchParams.set("page_size", pageSizeVal);

        if (url.toString() !== window.location.href) {
            window.history.replaceState({}, "", url.toString());
        }
    }

    /* ================================================
       INIT
    ================================================= */
    document.addEventListener("DOMContentLoaded", function () {
        sbProgressStart();
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
        sbInitConditionFilter();
        sbInitSimpleFilter(".sb-filter-unit", "unit");
        sbInitSimpleFilter(".sb-filter-instock", "instock");
        sbInitSimpleFilter(".sb-filter-price", "price");
        sbInitSimpleFilter(".sb-filter-disc", "disc");
        sbInitSimpleFilter(".sb-filter-rev", "rev");
        sbInitSimpleFilter(".sb-filter-fav", "fav");
        sbInitSimpleFilter(".sb-filter-reorder", "reorder");
        sbInitFilterIcons();
        sbInitInlineDescNoteEditing();
        sbInitPagination();
        sbInitSearch();
        sbInitQuillModal();
        sbInitQuillTriggers();
        sbInitNoteButtons();
        sbInitAddItemModal();
        sbInitDeleteModal();
        sbInitUserProfileModal();
        sbInitUppercaseToggle();
        applyPendingHighlight();
        sbSyncUrlWithState();
    });

    window.addEventListener("load", function () {
        // domknij pasek po pełnym załadowaniu
        setTimeout(() => {
            sbProgressFinish();
        }, 120);
    });
})();
