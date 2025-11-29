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
                if (parts.length === 2)
                    return parts.pop().split(";").shift();
            }

            /* ================================================
               AJAX: UPDATE UNIT (FK)
            ================================================= */
            function sbInitUnitDropdowns() {
                const selects = document.querySelectorAll(".unit-select");
                if (!selects.length) return;

                const csrftoken = getCookie("csrftoken");

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
                            headers: { "X-CSRFToken": csrftoken || "" },
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

                const csrftoken = getCookie("csrftoken");

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
                            headers: { "X-CSRFToken": csrftoken || "" },
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
               INLINE EDITING — (dla pól innych niż description)
            ================================================= */

            function sbInitInlineEditing() {
                const csrftoken = getCookie("csrftoken");
                const cells = document.querySelectorAll("td.inline");
                if (!cells.length) return;

                cells.forEach(td => {
                    td.addEventListener("click", function () {
                        if (td.classList.contains("editing")) return;

                        const field = td.dataset.field;
                        const itemId = td.dataset.id;

                        // description będziemy edytować w Quillu, więc jeśli kiedyś
                        // przypadkiem dostałaby klasę inline – omijamy
                        if (field === "part_description") return;

                        td.classList.add("editing");

                        const oldHTML = td.innerHTML;
                        const oldText = td.innerText.trim();

                        const wasMultiline = td.querySelector(".sb-multiline") !== null;

                        let input;
                        if (wasMultiline) {
                            input = document.createElement("textarea");
                            input.rows = 4;
                        } else {
                            input = document.createElement("input");
                            input.type = "text";
                        }

                        input.className = "sb-inline-input";
                        input.value = oldText;

                        td.innerHTML = "";
                        td.appendChild(input);
                        input.focus();
                        input.select();

                        function restoreOld() {
                            td.innerHTML = oldHTML;
                            td.classList.remove("editing");
                            markClampedCells();
                        }

                        function save() {
                            const newValue = input.value.trim();

                            const fd = new FormData();
                            fd.append("item_id", itemId);
                            fd.append("field", field);
                            fd.append("value", newValue);

                            fetch("/api/update-field/", {
                                method: "POST",
                                headers: { "X-CSRFToken": csrftoken || "" },
                                body: fd,
                            })
                                .then(r => r.json())
                                .then(data => {
                                    if (!data.ok) {
                                        console.error("Inline update failed:", data.error);
                                        restoreOld();
                                    } else {
                                        if (wasMultiline) {
                                            td.innerHTML = "";
                                            const span = document.createElement("span");
                                            span.className = "sb-multiline";
                                            span.textContent = newValue;
                                            td.appendChild(span);
                                        } else {
                                            td.textContent = newValue;
                                        }
                                        td.classList.remove("editing");
                                        markClampedCells();
                                    }
                                })
                                .catch(err => {
                                    console.error("Inline update error:", err);
                                    restoreOld();
                                });
                        }

                        function cancel() {
                            restoreOld();
                        }

                        input.addEventListener("keydown", e => {
                            if (e.key === "Enter") {
                                e.preventDefault();
                                save();
                            } else if (e.key === "Escape") {
                                e.preventDefault();
                                cancel();
                            }
                        });

                        input.addEventListener("blur", () => {
                            save();
                        });
                    });
                });
            }

            /* ================================================
               QUILL MODAL (WYSIWYG for description)
            ================================================= */

            function sbInitQuillModal() {
                const modal = document.getElementById("sb-quill-modal");
                if (!modal || typeof Quill === "undefined") return;

                const editorContainer = modal.querySelector("#sb-quill-editor");
                if (!editorContainer) return;

                const closeBtn = modal.querySelector(".sb-modal-close");
                const cancelBtn = modal.querySelector(".sb-modal-cancel");
                const saveBtn = modal.querySelector(".sb-modal-save");

                const csrftoken = getCookie("csrftoken");

                // Quill instance (single)
                const quill = new Quill(editorContainer, {
                    theme: "snow"
                });

                const state = {
                    modal: modal,
                    quill: quill,
                    currentItemId: null,
                    currentCell: null
                };

                window.sbQuillState = state;

                function hideModal() {
                    state.modal.style.display = "none";
                    state.currentItemId = null;
                    state.currentCell = null;
                }

                function openModal(itemId, initialHTML, cell) {
                    state.currentItemId = itemId;
                    state.currentCell = cell || null;

                    // Ustawiamy treść w Quillu
                    quill.setContents(quill.clipboard.convert(initialHTML || ""));

                    state.modal.style.display = "flex";
                }

                window.sbOpenQuillEditor = openModal;

                if (closeBtn) {
                    closeBtn.addEventListener("click", hideModal);
                }
                if (cancelBtn) {
                    cancelBtn.addEventListener("click", hideModal);
                }

                // prosty klik w tło (poza dialogiem) – zamyka
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
                            headers: { "X-CSRFToken": csrftoken || "" },
                            body: fd,
                        })
                            .then(r => r.json())
                            .then(data => {
                                if (!data.ok) {
                                    console.error("Quill save failed:", data.error);
                                } else {
                                    // podmiana preview w komórce
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
                        "X-Requested-With": "XMLHttpRequest"
                    }
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
                sbInitInlineEditing();
                sbInitPagination();
                sbInitQuillModal();
                sbInitQuillTriggers();
            });
        })();