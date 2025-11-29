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
        if (document.documentElement.classList.contains("sb-dark"))
            document.body.classList.add("sb-dark");
        else
            document.body.classList.remove("sb-dark");
    }

    /* ================================================
       LOLLYPOP DETECTION FOR MULTILINE FIELDS
    ================================================= */
    function markClampedCells() {
        // clear previous
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
       (NEW)
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
       (NEW)
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
                        // optional: rollback checkbox state
                        // checkbox.checked = !checkbox.checked;
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
                    // optional: rollback
                    // checkbox.checked = !checkbox.checked;
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
                                // po zmianie można ponownie sprawdzić clamp
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
       QUILL MODAL (DESCRIPTION EDIT)
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
            currentCell: null,
            modal,
        };

        function hideModal() {
            modal.style.display = "none";
            state.currentItemId = null;
            state.currentCell = null;
        }

        function openModal(itemId, html, cell) {
            state.currentItemId = itemId;
            state.currentCell = cell;

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
                if (!state.currentItemId || !state.currentCell) {
                    hideModal();
                    return;
                }

                const html = quill.root.innerHTML.trim();

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
                            console.error("Quill save failed:", data.error);
                        } else {
                            const preview = state.currentCell.querySelector(".sb-desc-preview");
                            if (preview) {
                                preview.innerHTML = html;
                            }
                            markClampedCells();
                        }
                        hideModal();
                    })
                    .catch(err => {
                        console.error("Quill save error:", err);
                        hideModal();
                    });
            });
        }
    }

    // podpinanie „lupki” w komórkach description
    function sbInitQuillTriggers() {
        const btns = document.querySelectorAll(".sb-desc-edit-btn");
        if (!btns.length || !window.sbOpenQuillEditor) return;

        btns.forEach(btn => {
            btn.addEventListener("click", function () {
                const itemId = btn.dataset.id;
                const cell = btn.closest("td");
                const preview = cell ? cell.querySelector(".sb-desc-preview") : null;
                const html = preview ? preview.innerHTML : "";
                window.sbOpenQuillEditor(itemId, html, cell);
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

                // Re-init on new content
                markClampedCells();
                sbInitUnitDropdowns();
                sbInitGroupDropdowns();
                sbInitConditionDropdowns();
                sbInitRevDiscCheckboxes();
                sbInitInlineEditing();
                sbInitPagination();
                sbInitQuillTriggers();
            })
            .catch(err => {
                console.error("Pagination AJAX error:", err);
                window.location.href = url;
            });
    }

    function sbInitPagination() {
        // PAGE SIZE DROPDOWN
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

        // PAGER LINKS
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
        sbInitInlineEditing();
        sbInitPagination();
        sbInitQuillModal();
        sbInitQuillTriggers();
    });
})();
