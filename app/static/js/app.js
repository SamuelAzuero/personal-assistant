/**
 * Autonomous Personal Assistant - Frontend Application Logic
 */

document.addEventListener("DOMContentLoaded", () => {
  // State cache
  let allTransactions = [];
  let allTasks = [];

  // DOM Elements - Modals & Buttons
  const txDialog = document.getElementById("transaction-dialog");
  const taskDialog = document.getElementById("task-dialog");
  const btnOpenTx = document.getElementById("btn-open-transaction-modal");
  const btnCloseTx = document.getElementById("btn-close-tx-dialog");
  const btnCancelTx = document.getElementById("btn-cancel-tx");
  const txForm = document.getElementById("transaction-form");

  const btnOpenTask = document.getElementById("btn-open-task-modal");
  const btnCloseTask = document.getElementById("btn-close-task-dialog");
  const btnCancelTask = document.getElementById("btn-cancel-task");
  const taskForm = document.getElementById("task-form");

  // M7 Elements - Transfers, Debts, Subscriptions
  const transferDialog = document.getElementById("transfer-dialog");
  const btnOpenTransfer = document.getElementById("btn-open-transfer-modal");
  const btnQuickTransfer = document.getElementById("btn-quick-transfer");
  const btnCloseTransfer = document.getElementById("btn-close-transfer-dialog");
  const btnCancelTransfer = document.getElementById("btn-cancel-transfer");
  const transferForm = document.getElementById("transfer-form");

  const debtDialog = document.getElementById("debt-dialog");
  const btnOpenDebt = document.getElementById("btn-open-debt-modal");
  const btnQuickDebt = document.getElementById("btn-quick-debt");
  const btnCloseDebt = document.getElementById("btn-close-debt-dialog");
  const btnCancelDebt = document.getElementById("btn-cancel-debt");
  const debtForm = document.getElementById("debt-form");

  const settleDialog = document.getElementById("settle-dialog");
  const btnCloseSettle = document.getElementById("btn-close-settle-dialog");
  const btnCancelSettle = document.getElementById("btn-cancel-settle");
  const settleForm = document.getElementById("settle-form");
  const settleSummaryBox = document.getElementById("settle-summary-box");

  const subDialog = document.getElementById("sub-dialog");
  const btnOpenSub = document.getElementById("btn-open-sub-modal");
  const btnQuickSub = document.getElementById("btn-quick-sub");
  const btnCloseSub = document.getElementById("btn-close-sub-dialog");
  const btnCancelSub = document.getElementById("btn-cancel-sub");
  const subForm = document.getElementById("sub-form");

  // M11 Elements - Direct Account Balance Operations (Deposit / Withdraw)
  const accountOpDialog = document.getElementById("account-op-dialog");
  const btnCloseAccountOp = document.getElementById("btn-close-account-op-dialog");
  const btnCancelAccountOp = document.getElementById("btn-cancel-account-op");
  const accountOpForm = document.getElementById("account-op-form");
  const accountOpTypeSelect = document.getElementById("account-op-type");
  const accountOpAmountInput = document.getElementById("account-op-amount");
  const accountOpAmountRaw = document.getElementById("account-op-amount-raw");
  const accountOpTargetName = document.getElementById("account-op-target-name");
  const accountOpCurrentBalance = document.getElementById("account-op-current-balance");
  const accountOpAccountId = document.getElementById("account-op-account-id");
  const accountOpAccountName = document.getElementById("account-op-account-name");
  const accountOpDialogTitle = document.getElementById("account-op-title");
  const accountOpSubmitBtn = document.getElementById("btn-submit-account-op");
  const accountOpConcept = document.getElementById("account-op-concept");
  const accountOpNotes = document.getElementById("account-op-notes");

  // M12 Elements — Debt Modifications & Installments
  const debtEditDialog = document.getElementById("debt-edit-dialog");
  const btnCloseDebtEdit = document.getElementById("btn-close-debt-edit-dialog");
  const btnCancelDebtEdit = document.getElementById("btn-cancel-debt-edit");
  const debtEditForm = document.getElementById("debt-edit-form");

  const installmentPayDialog = document.getElementById("installment-pay-dialog");
  const btnCloseInstallment = document.getElementById("btn-close-installment-dialog");
  const btnCancelInstallment = document.getElementById("btn-cancel-installment");
  const installmentPayForm = document.getElementById("installment-pay-form");

  const btnRefresh = document.getElementById("btn-refresh");
  const txFilterType = document.getElementById("transaction-filter-type");
  const taskFilterStatus = document.getElementById("task-filter-status");

  // Notifications
  const alertBanner = document.getElementById("alert-banner");

  function showAlert(message, type = "success") {
    if (!alertBanner) return;
    alertBanner.textContent = message;
    alertBanner.className = `alert-banner ${type}`;
    alertBanner.classList.remove("hidden");
    setTimeout(() => {
      alertBanner.classList.add("hidden");
    }, 4000);
  }

  // Safe helpers for native dialogs across modern & legacy web platforms
  function showModalSafe(dialog) {
    if (!dialog) return;
    if (dialog.open) return;
    if (typeof dialog.showModal === "function") {
      try {
        dialog.showModal();
      } catch (err) {
        if (!dialog.open) {
          dialog.setAttribute("open", "");
        }
      }
    } else {
      dialog.setAttribute("open", "");
    }
  }

  function closeModalSafe(dialog) {
    if (!dialog) return;
    if (typeof dialog.close === "function") {
      try {
        if (dialog.open) {
          dialog.close();
        }
      } catch (err) {
        dialog.removeAttribute("open");
        try {
          dialog.dispatchEvent(new Event("close"));
        } catch (_) {}
      }
    } else {
      dialog.removeAttribute("open");
      try {
        dialog.dispatchEvent(new Event("close"));
      } catch (_) {}
    }
  }

  // ================= Modal Dialog Controls =================
  if (btnOpenTx && txDialog) {
    btnOpenTx.addEventListener("click", () => {
      txForm.reset();
      txForm.dataset.submitting = "false";
      const submitBtn = document.getElementById("btn-submit-tx");
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Guardar Transacción";
      }
      const dateInput = document.getElementById("tx-date");
      if (dateInput) {
        dateInput.value = new Date().toISOString().split("T")[0];
      }
      showModalSafe(txDialog);
    });
  }
  if (btnCloseTx && txDialog) {
    btnCloseTx.addEventListener("click", () => closeModalSafe(txDialog));
  }
  if (btnCancelTx && txDialog) {
    btnCancelTx.addEventListener("click", () => closeModalSafe(txDialog));
  }

  if (btnOpenTask && taskDialog) {
    btnOpenTask.addEventListener("click", () => {
      taskForm.reset();
      taskForm.dataset.submitting = "false";
      const submitBtn = document.getElementById("btn-submit-task");
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Agregar Tarea";
      }
      showModalSafe(taskDialog);
    });
  }
  if (btnCloseTask && taskDialog) {
    btnCloseTask.addEventListener("click", () => closeModalSafe(taskDialog));
  }
  if (btnCancelTask && taskDialog) {
    btnCancelTask.addEventListener("click", () => closeModalSafe(taskDialog));
  }

  // Transfer Dialog
  const openTransferModal = () => {
    if (transferForm) {
      transferForm.reset();
      transferForm.dataset.submitting = "false";
      const submitBtn = document.getElementById("btn-submit-transfer");
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Ejecutar Transferencia";
      }
    }
    showModalSafe(transferDialog);
  };
  if (btnOpenTransfer) btnOpenTransfer.addEventListener("click", openTransferModal);
  if (btnQuickTransfer) btnQuickTransfer.addEventListener("click", openTransferModal);
  if (btnCloseTransfer && transferDialog) {
    btnCloseTransfer.addEventListener("click", () => closeModalSafe(transferDialog));
  }
  if (btnCancelTransfer && transferDialog) {
    btnCancelTransfer.addEventListener("click", () => closeModalSafe(transferDialog));
  }

  // Debt Dialog
  const openDebtModal = () => {
    if (debtForm) {
      debtForm.reset();
      debtForm.dataset.submitting = "false";
      const submitBtn = document.getElementById("btn-submit-debt");
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Guardar Registro";
      }
      const dateInput = document.getElementById("debt-due-date");
      if (dateInput) {
        // default to 7 days from now
        const d = new Date();
        d.setDate(d.getDate() + 7);
        dateInput.value = d.toISOString().split("T")[0];
      }
      const debtInstGrp = document.getElementById("debt-installment-group");
      if (debtInstGrp) debtInstGrp.classList.add("hidden");
    }
    showModalSafe(debtDialog);
  };
  if (btnOpenDebt) btnOpenDebt.addEventListener("click", openDebtModal);
  if (btnQuickDebt) btnQuickDebt.addEventListener("click", openDebtModal);
  if (btnCloseDebt && debtDialog) {
    btnCloseDebt.addEventListener("click", () => closeModalSafe(debtDialog));
  }
  if (btnCancelDebt && debtDialog) {
    btnCancelDebt.addEventListener("click", () => closeModalSafe(debtDialog));
  }

  // Debt Installment Checkbox Toggle
  const debtIsInstallmentChk = document.getElementById("debt-is-installment");
  const debtInstallmentGroup = document.getElementById("debt-installment-group");
  if (debtIsInstallmentChk && debtInstallmentGroup) {
    debtIsInstallmentChk.addEventListener("change", () => {
      if (debtIsInstallmentChk.checked) {
        debtInstallmentGroup.classList.remove("hidden");
      } else {
        debtInstallmentGroup.classList.add("hidden");
      }
    });
  }

  // Settle Dialog Cancel
  if (btnCloseSettle && settleDialog) {
    btnCloseSettle.addEventListener("click", () => closeModalSafe(settleDialog));
  }
  if (btnCancelSettle && settleDialog) {
    btnCancelSettle.addEventListener("click", () => closeModalSafe(settleDialog));
  }

  // M12 Dialogs: Debt Edit and Installment Pay Cancel & Close
  if (btnCloseDebtEdit && debtEditDialog) {
    btnCloseDebtEdit.addEventListener("click", () => closeModalSafe(debtEditDialog));
  }
  if (btnCancelDebtEdit && debtEditDialog) {
    btnCancelDebtEdit.addEventListener("click", () => closeModalSafe(debtEditDialog));
  }
  if (btnCloseInstallment && installmentPayDialog) {
    btnCloseInstallment.addEventListener("click", () => closeModalSafe(installmentPayDialog));
  }
  if (btnCancelInstallment && installmentPayDialog) {
    btnCancelInstallment.addEventListener("click", () => closeModalSafe(installmentPayDialog));
  }

  // Subscription Dialog
  const openSubModal = () => {
    if (subForm) {
      subForm.reset();
      subForm.dataset.submitting = "false";
      const submitBtn = document.getElementById("btn-submit-sub");
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Guardar Suscripción";
      }
    }
    showModalSafe(subDialog);
  };
  if (btnOpenSub) btnOpenSub.addEventListener("click", openSubModal);
  if (btnQuickSub) btnQuickSub.addEventListener("click", openSubModal);
  if (btnCloseSub && subDialog) {
    btnCloseSub.addEventListener("click", () => closeModalSafe(subDialog));
  }
  if (btnCancelSub && subDialog) {
    btnCancelSub.addEventListener("click", () => closeModalSafe(subDialog));
  }

  // Account Operations Dialog Cancel & Close
  if (btnCloseAccountOp && accountOpDialog) {
    btnCloseAccountOp.addEventListener("click", () => closeModalSafe(accountOpDialog));
  }
  if (btnCancelAccountOp && accountOpDialog) {
    btnCancelAccountOp.addEventListener("click", () => closeModalSafe(accountOpDialog));
  }

  // Close modals on clicking backdrop strictly via event target isolation
  [
    txDialog, taskDialog, transferDialog, debtDialog, settleDialog, subDialog, accountOpDialog,
    debtEditDialog, installmentPayDialog
  ].forEach(dialog => {
    if (!dialog) return;

    let isBackdropTarget = false;
    let touchMoved = false;

    dialog.addEventListener("mousedown", (e) => {
      isBackdropTarget = (e.target === dialog);
    });

    dialog.addEventListener("touchstart", (e) => {
      isBackdropTarget = (e.target === dialog);
      touchMoved = false;
    }, { passive: true });

    dialog.addEventListener("touchmove", () => {
      // User is scrolling / swiping on mobile, cancel backdrop click trigger
      touchMoved = true;
      isBackdropTarget = false;
    }, { passive: true });

    dialog.addEventListener("touchend", () => {
      if (touchMoved) {
        isBackdropTarget = false;
      }
    }, { passive: true });

    dialog.addEventListener("touchcancel", () => {
      isBackdropTarget = false;
      touchMoved = false;
    }, { passive: true });

    dialog.addEventListener("click", (e) => {
      // Close only if click directly targeted the backdrop element itself
      // (either pointerdown occurred on backdrop, or keyboard/programmatic click where e.detail === 0)
      const isDirectBackdrop = (e.target === dialog);
      if (isDirectBackdrop && (isBackdropTarget || e.detail === 0) && !touchMoved) {
        closeModalSafe(dialog);
      }
      isBackdropTarget = false;
      touchMoved = false;
    });

    dialog.addEventListener("close", () => {
      const form = dialog.querySelector("form");
      if (form) {
        form.dataset.submitting = "false";
        const submitBtn = form.querySelector("button[type='submit']");
        if (submitBtn) {
          submitBtn.disabled = false;
          const defaultTexts = {
            "btn-submit-tx": "Guardar Transacción",
            "btn-submit-task": "Agregar Tarea",
            "btn-submit-transfer": "Ejecutar Transferencia",
            "btn-submit-debt": "Guardar Registro",
            "btn-submit-settle": "Confirmar Pago",
            "btn-submit-sub": "Guardar Suscripción",
            "btn-submit-account-op": "Confirmar Operación",
            "btn-submit-debt-edit": "Guardar Cambios",
            "btn-submit-installment": "Confirmar Pago de Cuotas",
          };
          if (defaultTexts[submitBtn.id]) {
            submitBtn.textContent = defaultTexts[submitBtn.id];
          }
        }
      }
    });

    // Isolate modal content from backdrop event bubbling & dragging
    const content = dialog.querySelector(".dialog-content");
    if (content) {
      content.addEventListener("click", (e) => {
        e.stopPropagation();
      });
      content.addEventListener("mousedown", () => {
        isBackdropTarget = false;
      });
      content.addEventListener("touchstart", () => {
        isBackdropTarget = false;
      }, { passive: true });
    }
  });

  function formatCurrency(val) {
    const num = Number(val || 0);
    return "$" + num.toLocaleString("es-CO", { minimumFractionDigits: 0, maximumFractionDigits: 0 }) + " COP";
  }

  // ================= Data Fetching & UI Updates =================

  async function loadFinancialSummary() {
    try {
      const res = await fetch("/api/finance/summary");
      if (!res.ok) throw new Error("Failed to load financial summary");
      const data = await res.json();

      const income = Number(data.total_income || 0);
      const expense = Number(data.total_expenses || 0);
      const net = Number(data.net_balance !== undefined ? data.net_balance : (income - expense));

      // Calculate savings rate
      const savingsRate = income > 0 ? ((net / income) * 100).toFixed(1) : "0.0";

      // Update KPI DOM
      const netEl = document.getElementById("kpi-net-balance");
      if (netEl) {
        netEl.textContent = formatCurrency(net);
        netEl.className = `kpi-value ${net >= 0 ? "text-success" : "text-danger"}`;
      }

      const incEl = document.getElementById("kpi-total-income");
      if (incEl) {
        incEl.textContent = formatCurrency(income);
      }

      const expEl = document.getElementById("kpi-total-expenses");
      if (expEl) {
        expEl.textContent = formatCurrency(expense);
      }

      const savEl = document.getElementById("kpi-savings-rate");
      if (savEl) {
        savEl.textContent = `${savingsRate}%`;
      }

      // Update Trend Chart
      if (typeof window.renderTrendChart === "function") {
        window.renderTrendChart({
          total_income: income,
          total_expenses: expense,
          net_balance: net,
        });
      }
    } catch (err) {
      console.error("Error loading financial summary:", err);
    }
  }

  async function loadCategories() {
    try {
      const res = await fetch("/api/finance/categories");
      if (!res.ok) throw new Error("Failed to load categories");
      const categories = await res.json();

      if (typeof window.renderCategoryChart === "function") {
        window.renderCategoryChart(categories);
      }
    } catch (err) {
      console.error("Error loading categories:", err);
    }
  }

  async function loadTransactions() {
    try {
      const res = await fetch("/api/finance/transactions?limit=100");
      if (!res.ok) throw new Error("Failed to load transactions");
      allTransactions = await res.json();
      renderTransactionsTable();
    } catch (err) {
      console.error("Error loading transactions:", err);
      const tbody = document.getElementById("transactions-tbody");
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-danger">Error al cargar las transacciones.</td></tr>`;
      }
    }
  }

  function renderTransactionsTable() {
    const tbody = document.getElementById("transactions-tbody");
    if (!tbody) return;

    const filter = txFilterType ? txFilterType.value : "all";
    const filtered = allTransactions.filter(tx => {
      const type = (tx.transaction_type || tx.type || "").toLowerCase();
      if (filter === "all") return true;
      return type === filter;
    });

    if (filtered.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="muted-row">No hay transacciones registradas aún. Haz clic en '+ Nueva Transacción' para agregar una.</td></tr>`;
      return;
    }

    tbody.innerHTML = filtered.map(tx => {
      const type = (tx.transaction_type || tx.type || "expense").toLowerCase();
      const isIncome = type === "income";
      const amt = Number(tx.amount || (tx.amount_cents ? tx.amount_cents / 100 : 0));
      const dateDisplay = (tx.timestamp || tx.date || "").split("T")[0] || "Hoy";
      const cat = tx.category || "General";
      const desc = tx.description || "—";
      const id = tx.id || tx.transaction_id;
      const typeLabel = isIncome ? "Ingreso" : "Gasto";

      return `
        <tr>
          <td>${dateDisplay}</td>
          <td><span class="badge badge-info">${cat}</span></td>
          <td>${escapeHtml(desc)}</td>
          <td><span class="badge ${isIncome ? 'badge-success' : 'badge-danger'}">${typeLabel}</span></td>
          <td class="text-right font-weight-bold ${isIncome ? 'text-success' : 'text-danger'}">
            ${isIncome ? '+' : '-'}${formatCurrency(amt)}
          </td>
          <td class="text-center">
            <button class="btn btn-danger-outline btn-void" data-id="${id}" title="Anular Transacción">
              Anular
            </button>
          </td>
        </tr>
      `;
    }).join("");

    // Attach void click listeners
    tbody.querySelectorAll(".btn-void").forEach(btn => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        if (!confirm("¿Estás seguro de que deseas anular esta transacción?")) return;
        try {
          const res = await fetch(`/api/finance/transactions/${id}`, { method: "DELETE" });
          if (res.ok) {
            showAlert("Transacción anulada exitosamente.");
            refreshDashboard();
          } else {
            showAlert("Error al anular la transacción.", "error");
          }
        } catch (err) {
          showAlert("Error de red al anular la transacción.", "error");
        }
      });
    });
  }

  async function loadTasks() {
    try {
      const res = await fetch("/api/tasks");
      if (!res.ok) throw new Error("Failed to load tasks");
      allTasks = await res.json();
      renderTasksList();
    } catch (err) {
      console.error("Error loading tasks:", err);
      const ul = document.getElementById("task-list");
      if (ul) {
        ul.innerHTML = `<li class="muted-row text-danger">Error al cargar las tareas.</li>`;
      }
    }
  }

  function renderTasksList() {
    const ul = document.getElementById("task-list");
    if (!ul) return;

    const filter = taskFilterStatus ? taskFilterStatus.value : "pending";
    const filtered = allTasks.filter(t => {
      const isCompleted = t.is_completed || t.status === "completed";
      if (filter === "all") return true;
      if (filter === "completed") return isCompleted;
      return !isCompleted;
    });

    if (filtered.length === 0) {
      const filterLabel = filter === "completed" ? "completadas" : (filter === "pending" ? "pendientes" : "");
      ul.innerHTML = `<li class="muted-row">No hay tareas ${filterLabel}. ¡Estás al día!</li>`;
      return;
    }

    ul.innerHTML = filtered.map(t => {
      const id = t.task_id || t.id;
      const isCompleted = t.is_completed || t.status === "completed";
      const priority = (t.priority || "medium").toLowerCase();
      const priorityLabel = priority === "urgent" ? "urgente" : (priority === "high" ? "alta" : (priority === "low" ? "baja" : "media"));
      const priorityBadgeClass = 
        priority === "urgent" ? "badge-danger" :
        priority === "high" ? "badge-warning" :
        priority === "low" ? "badge-muted" : "badge-info";

      const due = t.due_date ? `📅 Para: ${t.due_date.replace("T", " ").slice(0, 16)}` : "";

      return `
        <li class="task-item ${isCompleted ? 'completed' : ''}" data-id="${id}">
          <div class="task-left">
            <input type="checkbox" class="task-checkbox" data-id="${id}" ${isCompleted ? 'checked' : ''} title="Cambiar estado">
            <div class="task-info">
              <span class="task-title">${escapeHtml(t.title || "")}</span>
              <div class="task-meta">
                <span class="badge ${priorityBadgeClass}">${priorityLabel}</span>
                ${due ? `<span>${due}</span>` : ''}
              </div>
            </div>
          </div>
          <button class="btn btn-danger-outline btn-task-delete" data-id="${id}" title="Eliminar Tarea">&times;</button>
        </li>
      `;
    }).join("");

    // Toggle status listeners
    ul.querySelectorAll(".task-checkbox").forEach(chk => {
      chk.addEventListener("change", async () => {
        const id = chk.getAttribute("data-id");
        const newStatus = chk.checked ? "completed" : "pending";
        try {
          const res = await fetch(`/api/tasks/${id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: newStatus }),
          });
          if (res.ok) {
            loadTasks();
          } else {
            showAlert("Error al actualizar el estado de la tarea", "error");
          }
        } catch (err) {
          showAlert("Error de red al actualizar la tarea", "error");
        }
      });
    });

    // Delete task listeners
    ul.querySelectorAll(".btn-task-delete").forEach(btn => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        if (!confirm("¿Eliminar esta tarea?")) return;
        try {
          const res = await fetch(`/api/tasks/${id}`, { method: "DELETE" });
          if (res.ok) {
            showAlert("Tarea eliminada.");
            loadTasks();
          } else {
            showAlert("Error al eliminar la tarea.", "error");
          }
        } catch (err) {
          showAlert("Error de red al eliminar la tarea.", "error");
        }
      });
    });
  }

  async function loadEmailDigest() {
    const container = document.getElementById("email-digest-list");
    const badge = document.getElementById("urgent-email-badge");
    if (!container) return;

    try {
      const res = await fetch("/api/email/digest");
      if (!res.ok) throw new Error("Failed to load email digest");
      const data = await res.json();

      const urgentCount = data.urgent_count || 0;
      if (badge) {
        badge.textContent = `${urgentCount} Urgentes`;
        badge.className = `badge ${urgentCount > 0 ? 'badge-danger' : 'badge-success'}`;
      }

      const items = (data.items || []).slice(0, 3);
      if (items.length === 0) {
        container.innerHTML = `<div class="muted-row">Bandeja al día. ¡No hay correos urgentes pendientes!</div>`;
        return;
      }

      container.innerHTML = items.map(item => `
        <div class="widget-item ${item.is_urgent ? 'urgent' : ''}">
          <div class="widget-item-title">${escapeHtml(item.subject || "(Sin Asunto)")}</div>
          <div class="widget-item-snippet">${escapeHtml(item.snippet || "")}</div>
          <div class="widget-item-meta">
            <span>De: ${escapeHtml(item.sender || item.from || "Desconocido")}</span>
            ${item.is_urgent ? '<span class="text-danger font-weight-bold">⚡ Alta Prioridad</span>' : ''}
          </div>
        </div>
      `).join("");
    } catch (err) {
      console.error("Error loading email digest:", err);
      container.innerHTML = `<div class="muted-row text-muted">Servicio de Gmail en modo simulado / sin conexión.</div>`;
    }
  }

  // ================= M13: Outings & Recommendations UI =================

  async function loadOutings(sector = "", query = "") {
    const container = document.getElementById("outings-list");
    const countBadge = document.getElementById("outings-count-badge");
    const sectorSelect = document.getElementById("outings-sector-select");
    const searchInput = document.getElementById("outings-search-input");
    const searchBtn = document.getElementById("btn-search-outings");

    if (!container) return;

    // Use current input values if parameters are not explicitly passed
    const activeSector = sector !== "" ? sector : (sectorSelect ? sectorSelect.value : "Chapinero");
    const activeQuery = query !== "" ? query : (searchInput ? searchInput.value.trim() : "");

    // Display inline loading feedback
    container.innerHTML = `
      <div class="muted-row">
        <span class="spinner-inline">⏳</span> Buscando lugares en <strong>${escapeHtml(activeSector === "all" ? "todos los sectores" : activeSector)}</strong>...
      </div>
    `;

    if (searchBtn) {
      searchBtn.disabled = true;
      searchBtn.innerHTML = `<span>⏳</span> Buscando...`;
    }

    try {
      const params = new URLSearchParams();
      if (activeSector && activeSector !== "all") {
        params.append("sector", activeSector);
        params.append("location", activeSector);
      }
      if (activeQuery) {
        params.append("query", activeQuery);
      }

      const queryString = params.toString();
      const url = queryString ? `/api/research/outings?${queryString}` : "/api/research/outings";

      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}: Error al obtener recomendaciones`);
      const places = await res.json();

      const items = Array.isArray(places) ? places : [];

      if (countBadge) {
        countBadge.textContent = `${items.length} ${items.length === 1 ? 'Lugar' : 'Lugares'}`;
      }

      if (items.length === 0) {
        container.innerHTML = `
          <div class="muted-row">
            No se encontraron lugares en <em>${escapeHtml(activeSector === 'all' ? 'este criterio' : activeSector)}</em> para "${escapeHtml(activeQuery || 'todo')}".<br>
            <span class="text-dim">Prueba seleccionando otro sector o ampliando los términos de búsqueda.</span>
          </div>
        `;
        return;
      }

      container.innerHTML = `
        <div class="venue-cards-list">
          ${items.map(p => {
            const name = escapeHtml(p.name || "Lugar Recomendado");
            const cuisine = escapeHtml(p.cuisine || p.category || "Gastronomía");
            const rating = p.rating ? Number(p.rating).toFixed(1) : "4.8";
            const priceTier = escapeHtml(p.price_tier || "$$");
            const sectorName = escapeHtml(p.sector || p.location || activeSector || "Bogotá");
            const address = escapeHtml(p.address || "");
            const description = escapeHtml(p.description || "");
            const amenities = Array.isArray(p.amenities) ? p.amenities : [];

            // Build fallback universal Google Maps URL if missing
            const mapsUrl = p.maps_url || (
              "https://www.google.com/maps/search/?api=1&query=" +
              encodeURIComponent(`${p.name || ''}, ${p.address || sectorName}`)
            );

            return `
              <article class="venue-card">
                <div class="venue-card-header">
                  <div class="venue-title-group">
                    <h3 class="venue-name">${name}</h3>
                    <div class="venue-badges">
                      <span class="badge badge-info venue-badge">${cuisine}</span>
                      <span class="badge badge-muted venue-badge">📍 ${sectorName}</span>
                    </div>
                  </div>
                  <div class="venue-meta-rating">
                    <span class="venue-rating" title="Calificación promedio">⭐ ${rating}</span>
                    <span class="venue-price" title="Rango de precio">${priceTier}</span>
                  </div>
                </div>

                ${description ? `<p class="venue-description">${description}</p>` : ''}

                <div class="venue-footer">
                  <div class="venue-address-info">
                    ${address ? `<span class="venue-address" title="${address}">📍 ${address}</span>` : ''}
                    ${amenities.length > 0 ? `
                      <div class="venue-amenities">
                        ${amenities.slice(0, 3).map(a => `<span class="amenity-pill">✨ ${escapeHtml(a)}</span>`).join("")}
                      </div>
                    ` : ''}
                  </div>
                  <div class="venue-actions">
                    <a
                      href="${escapeHtml(mapsUrl)}"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="btn btn-secondary btn-sm btn-maps-direct"
                      aria-label="Ver ${name} en Google Maps"
                    >
                      🗺️ Ver en Google Maps
                    </a>
                  </div>
                </div>
              </article>
            `;
          }).join("")}
        </div>
      `;
    } catch (err) {
      console.error("Error loading outings:", err);
      if (countBadge) countBadge.textContent = "Modo Local";
      container.innerHTML = `
        <div class="muted-row text-muted">
          Servicio de búsqueda geolocalizada en modo local / sin conexión.
        </div>
      `;
    } finally {
      if (searchBtn) {
        searchBtn.disabled = false;
        searchBtn.innerHTML = `<span>🔍</span> Buscar Lugares`;
      }
    }
  }

  // Setup Event Listeners for Outings Controls
  const outingsSectorSelect = document.getElementById("outings-sector-select");
  const outingsSearchInput = document.getElementById("outings-search-input");
  const btnSearchOutings = document.getElementById("btn-search-outings");

  if (outingsSectorSelect) {
    outingsSectorSelect.addEventListener("change", () => {
      loadOutings(outingsSectorSelect.value, outingsSearchInput ? outingsSearchInput.value.trim() : "");
    });
  }

  if (btnSearchOutings) {
    btnSearchOutings.addEventListener("click", () => {
      loadOutings(outingsSectorSelect ? outingsSectorSelect.value : "", outingsSearchInput ? outingsSearchInput.value.trim() : "");
    });
  }

  if (outingsSearchInput) {
    outingsSearchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        loadOutings(outingsSectorSelect ? outingsSectorSelect.value : "", outingsSearchInput.value.trim());
      }
    });
  }


  // ================= Form Submissions =================

  if (txForm) {
    txForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (txForm.dataset.submitting === "true") return;
      txForm.dataset.submitting = "true";

      const submitBtn = document.getElementById("btn-submit-tx");
      const originalText = submitBtn ? submitBtn.textContent : "Guardar Transacción";
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Guardando...";
      }

      const amount = parseFloat(document.getElementById("tx-amount").value);
      const type = document.getElementById("tx-type").value;
      const category = document.getElementById("tx-category").value;
      const description = document.getElementById("tx-description").value;
      const dateVal = document.getElementById("tx-date").value;
      const accountEl = document.getElementById("tx-account");
      const account = accountEl ? accountEl.value : undefined;

      try {
        const payload = {
          amount: amount,
          type: type,
          category: category,
          description: description,
          date: dateVal ? `${dateVal}T12:00:00Z` : undefined,
          idempotency_key: "web-tx-" + Date.now() + "-" + Math.random().toString(36).slice(2, 9),
        };
        if (account) {
          payload.account = account;
        }

        const res = await fetch("/api/finance/transactions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        if (res.ok) {
          showAlert("¡Transacción registrada exitosamente!");
          closeModalSafe(txDialog);
          refreshDashboard();
        } else {
          const errData = await res.json();
          showAlert(`Error: ${errData.detail || "Error en la validación"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al registrar transacción", "error");
      } finally {
        txForm.dataset.submitting = "false";
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
      }
    });
  }

  if (taskForm) {
    taskForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (taskForm.dataset.submitting === "true") return;
      taskForm.dataset.submitting = "true";

      const submitBtn = document.getElementById("btn-submit-task");
      const originalText = submitBtn ? submitBtn.textContent : "Agregar Tarea";
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Guardando...";
      }

      const title = document.getElementById("task-title").value;
      const priority = document.getElementById("task-priority").value;
      const category = document.getElementById("task-category").value;
      const dueDateVal = document.getElementById("task-due-date").value;
      const description = document.getElementById("task-description").value;

      try {
        const res = await fetch("/api/tasks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: title,
            priority: priority,
            category: category,
            due_date: dueDateVal ? new Date(dueDateVal).toISOString() : undefined,
            description: description,
          }),
        });

        if (res.ok) {
          showAlert("¡Tarea creada exitosamente!");
          closeModalSafe(taskDialog);
          loadTasks();
        } else {
          const errData = await res.json();
          showAlert(`Error: ${errData.detail || "Error en la validación"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al crear tarea", "error");
      } finally {
        taskForm.dataset.submitting = "false";
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
      }
    });
  }

  // Filters & Refresh
  if (txFilterType) {
    txFilterType.addEventListener("change", renderTransactionsTable);
  }
  if (taskFilterStatus) {
    taskFilterStatus.addEventListener("change", renderTasksList);
  }
  if (btnRefresh) {
    btnRefresh.addEventListener("click", () => {
      refreshDashboard();
      showAlert("Tablero actualizado.");
    });
  }

  // ================= M7: Accounts, Debts, Subscriptions =================

  async function loadAccounts() {
    const grid = document.getElementById("accounts-grid");
    if (!grid) return;
    try {
      const res = await fetch("/api/finance/accounts");
      if (!res.ok) throw new Error("Failed to load accounts");
      const data = await res.json();
      const accounts = Array.isArray(data) ? data : (data.accounts || []);
      const netWorthCents = data.total_net_worth_cents || 0;
      const netWorth = data.total_net_worth || (netWorthCents / 100);

      const iconMap = {
        "efectivo": "💵",
        "nequi": "📱",
        "nu": "🟣",
        "daviplata": "🔴",
        "bancolombia": "🟡"
      };

      let html = `
        <div class="account-card account-card-networth">
          <div class="account-header">
            <span class="account-icon">💎</span>
            <span class="account-badge">Patrimonio Neto Total</span>
          </div>
          <div class="account-balance">${formatCurrency(netWorth)}</div>
          <div class="account-footer">Consolidado en ${accounts.length} cuentas activas</div>
        </div>
      `;

      accounts.forEach(acc => {
        const icon = acc.icon || iconMap[acc.name.toLowerCase()] || "💳";
        const share = acc.percentage_share !== undefined ? acc.percentage_share : 0;
        const color = acc.color || "#4f46e5";
        const accId = acc.id || acc.account_id || acc.name.toLowerCase();
        const accBalance = acc.balance !== undefined ? acc.balance : ((acc.balance_cents || 0) / 100);
        html += `
          <div class="account-card" style="border-top: 4px solid ${escapeHtml(color)}">
            <div class="account-header">
              <span class="account-icon">${icon}</span>
              <span class="account-type-tag">${escapeHtml(acc.name)}</span>
            </div>
            <div class="account-balance">${formatCurrency(accBalance)}</div>
            <div class="account-share-bar">
              <div class="account-share-fill" style="width: ${Math.min(100, Math.max(0, share))}%; background: ${escapeHtml(color)}"></div>
            </div>
            <div class="account-footer">${share}% del patrimonio neto</div>
            <div class="account-actions">
              <button type="button" class="btn btn-sm btn-outline-success btn-account-op"
                data-id="${escapeHtml(accId)}"
                data-name="${escapeHtml(acc.name)}"
                data-balance="${accBalance}"
                data-action="deposit"
                title="Depositar fondos en ${escapeHtml(acc.name)}">
                ➕ Depositar
              </button>
              <button type="button" class="btn btn-sm btn-outline-danger btn-account-op"
                data-id="${escapeHtml(accId)}"
                data-name="${escapeHtml(acc.name)}"
                data-balance="${accBalance}"
                data-action="withdraw"
                title="Retirar fondos de ${escapeHtml(acc.name)}">
                ➖ Retirar
              </button>
            </div>
          </div>
        `;
      });

      grid.innerHTML = html;
    } catch (err) {
      grid.innerHTML = '<div class="muted-row">Error al cargar cuentas</div>';
    }
  }

  async function loadDebts() {
    const recTbody = document.getElementById("receivables-tbody");
    const payTbody = document.getElementById("payables-tbody");
    const recBadge = document.getElementById("receivables-total-badge");
    const payBadge = document.getElementById("payables-total-badge");

    try {
      const res = await fetch("/api/finance/debts");
      if (!res.ok) throw new Error("Failed to load debts");
      const raw = await res.json();
      const debts = Array.isArray(raw) ? raw : (raw.debts || []);

      const receivables = debts.filter(d => (d.debt_type || d.type) === "receivable" && d.status !== "settled" && d.status !== "cancelled");
      const payables = debts.filter(d => (d.debt_type || d.type) === "debt" && d.status !== "settled" && d.status !== "cancelled");

      const totalRec = receivables.reduce((sum, d) => sum + (d.remaining_cents || 0), 0);
      const totalPay = payables.reduce((sum, d) => sum + (d.remaining_cents || 0), 0);

      if (recBadge) recBadge.textContent = formatCurrency(totalRec / 100);
      if (payBadge) payBadge.textContent = formatCurrency(totalPay / 100);

      // Render helper for debt row
      const renderDebtRow = (d, type) => {
        const isRec = type === "receivable";
        const id = d.id || d.debt_id;
        const isInst = Boolean(d.is_installment);
        const totalInst = parseInt(d.total_installments, 10) || 1;
        const remInst = d.remaining_installments != null ? parseInt(d.remaining_installments, 10) : totalInst;
        const paidInst = Math.max(0, totalInst - remInst);
        const currentCuota = Math.min(totalInst, paidInst + 1);
        const progressPct = totalInst > 0 ? Math.round((paidInst / totalInst) * 100) : 0;
        const instAmt = (d.installment_amount_cents || 0) / 100;

        // Due date calculation
        let dueDateDisplay = "Sin fecha";
        let dueSubtext = "";
        if (isInst && d.next_installment_due_date) {
          dueDateDisplay = String(d.next_installment_due_date).substring(0, 10);
          dueSubtext = '<span class="debt-sub-info text-warning">Próx. cuota</span>';
        } else if (d.due_date) {
          dueDateDisplay = String(d.due_date).substring(0, 10);
        }

        // Status / Cuota badge
        let statusHtml = "";
        if (isInst) {
          statusHtml = `
            <div class="debt-installment-status">
              <div class="d-flex justify-between align-center">
                <span class="badge badge-installment" title="${remInst} cuotas restantes">Cuota ${currentCuota}/${totalInst}</span>
                <span class="debt-sub-info">${progressPct}%</span>
              </div>
              <div class="debt-progress-container" title="${paidInst} de ${totalInst} cuotas pagadas">
                <div class="debt-progress-bar ${isRec ? 'bg-success' : 'bg-primary'}" style="width: ${progressPct}%;"></div>
              </div>
            </div>
          `;
        } else {
          const badgeClass = d.status === "partially_paid" ? "badge-warning" : (isRec ? "badge-info" : "badge-danger");
          const statusLabel = d.status === "partially_paid" ? "Abono Parcial" : "Pendiente";
          statusHtml = `<span class="badge ${badgeClass}">${statusLabel}</span>`;
        }

        // Amount display
        const remAmount = d.remaining_amount || (d.remaining_cents / 100);
        let amountHtml = `<strong>${formatCurrency(remAmount)}</strong>`;
        if (isInst && instAmt > 0) {
          amountHtml += `<span class="debt-sub-info">${formatCurrency(instAmt)} / cuota</span>`;
        }

        // Action Buttons
        const editBtn = `
          <button class="btn btn-sm btn-outline-secondary btn-edit-debt"
            data-id="${escapeHtml(id)}"
            data-counterparty="${escapeHtml(d.counterparty)}"
            data-amount="${d.amount || (d.amount_cents / 100)}"
            data-reason="${escapeHtml(d.reason)}"
            data-due-date="${d.due_date ? String(d.due_date).substring(0, 10) : ''}"
            data-status="${escapeHtml(d.status || 'active')}"
            data-is-installment="${isInst ? 'true' : 'false'}"
            title="Editar deuda o fecha">✏️ Editar</button>
        `;

        const payInstBtn = (isInst && remInst > 0) ? `
          <button class="btn btn-sm btn-primary btn-pay-installment"
            data-id="${escapeHtml(id)}"
            data-counterparty="${escapeHtml(d.counterparty)}"
            data-total-installments="${totalInst}"
            data-remaining-installments="${remInst}"
            data-installment-amount="${instAmt}"
            data-remaining-amount="${remAmount}"
            data-remaining-cents="${d.remaining_cents}"
            data-type="${type}"
            title="Pagar una o más cuotas">💳 Pagar Cuota</button>
        ` : '';

        const settleBtn = `
          <button class="btn btn-sm btn-outline-success btn-open-settle"
            data-id="${escapeHtml(id)}"
            data-counterparty="${escapeHtml(d.counterparty)}"
            data-remaining="${remAmount}"
            data-cents="${d.remaining_cents}"
            data-type="${type}"
            title="Abono libre o liquidación total">${isInst ? 'Abono Libre' : (isRec ? 'Abonar / Liquidar' : 'Pagar / Abonar')}</button>
        `;

        return `
          <tr>
            <td>
              <strong>${escapeHtml(d.counterparty)}</strong>
              ${isInst ? '<span class="badge badge-light debt-sub-info">Plan Cuotas</span>' : ''}
            </td>
            <td>
              ${escapeHtml(d.reason)}
              ${isInst && d.payment_frequency ? `<span class="debt-sub-info">Frecuencia: ${escapeHtml(d.payment_frequency)}</span>` : ''}
            </td>
            <td><span class="badge badge-light">${escapeHtml(d.account_name || "Efectivo")}</span></td>
            <td>${amountHtml}</td>
            <td>${dueDateDisplay}${dueSubtext}</td>
            <td>${statusHtml}</td>
            <td class="text-center">
              <div class="debt-action-buttons">
                ${editBtn}
                ${payInstBtn}
                ${settleBtn}
              </div>
            </td>
          </tr>
        `;
      };

      if (recTbody) {
        recTbody.innerHTML = receivables.length === 0
          ? '<tr><td colspan="7" class="text-center muted-row">No tienes cobros pendientes 🎉</td></tr>'
          : receivables.map(d => renderDebtRow(d, "receivable")).join("");
      }

      if (payTbody) {
        payTbody.innerHTML = payables.length === 0
          ? '<tr><td colspan="7" class="text-center muted-row">No tienes deudas pendientes 🎉</td></tr>'
          : payables.map(d => renderDebtRow(d, "debt")).join("");
      }

    } catch (err) {
      if (recTbody) recTbody.innerHTML = '<tr><td colspan="7" class="text-center muted-row">Error al cargar cobros</td></tr>';
      if (payTbody) payTbody.innerHTML = '<tr><td colspan="7" class="text-center muted-row">Error al cargar deudas</td></tr>';
    }
  }

  // Centralized Event Delegation for Debt Actions (Edit, Pay Installment, Settle)
  const debtsGrid = document.querySelector(".debts-grid");
  if (debtsGrid) {
    debtsGrid.addEventListener("click", (e) => {
      // 1. Edit Debt Dialog
      const editBtn = e.target.closest(".btn-edit-debt");
      if (editBtn) {
        const debtId = editBtn.getAttribute("data-id");
        openDebtEditModal(debtId, editBtn.dataset);
        return;
      }

      // 2. Installment Payment Dialog
      const payInstBtn = e.target.closest(".btn-pay-installment");
      if (payInstBtn) {
        const debtId = payInstBtn.getAttribute("data-id");
        openInstallmentModal(debtId, payInstBtn.dataset);
        return;
      }

      // 3. Freeform Settlement Dialog
      const settleBtn = e.target.closest(".btn-open-settle");
      if (settleBtn) {
        const debtId = settleBtn.getAttribute("data-id");
        openSettleModal(debtId, settleBtn.dataset);
        return;
      }
    });
  }

  function openDebtEditModal(debtId, data) {
    if (!debtEditDialog || !debtEditForm) return;
    debtEditForm.reset();
    debtEditForm.dataset.submitting = "false";

    document.getElementById("debt-edit-id").value = debtId;
    document.getElementById("debt-edit-counterparty").value = data.counterparty || "";
    document.getElementById("debt-edit-amount").value = data.amount || "";
    document.getElementById("debt-edit-reason").value = data.reason || "";
    document.getElementById("debt-edit-due-date").value = data.dueDate || "";
    document.getElementById("debt-edit-status").value = data.status || "active";

    const callout = document.getElementById("debt-edit-installment-callout");
    if (callout) {
      if (data.isInstallment === "true") {
        callout.classList.remove("hidden");
        callout.innerHTML = `
          <strong>ℹ️ Préstamo a Cuotas:</strong> Al modificar el monto total de una deuda en cuotas,
          el valor proporcional de las cuotas pendientes se recalculará automáticamente.
        `;
      } else {
        callout.classList.add("hidden");
      }
    }

    const submitBtn = document.getElementById("btn-submit-debt-edit");
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Guardar Cambios";
    }
    showModalSafe(debtEditDialog);
  }

  function openInstallmentModal(debtId, data) {
    if (!installmentPayDialog || !installmentPayForm) return;
    installmentPayForm.reset();
    installmentPayForm.dataset.submitting = "false";

    document.getElementById("inst-debt-id").value = debtId;
    const remInst = parseInt(data.remainingInstallments, 10) || 1;
    const totalInst = parseInt(data.totalInstallments, 10) || 1;
    const instAmt = parseFloat(data.installmentAmount) || 0;
    const remAmt = parseFloat(data.remainingAmount) || 0;
    const isReceivable = (data.type === "receivable");

    document.getElementById("inst-amount-per-cuota").value = instAmt;
    document.getElementById("inst-remaining-count").value = remInst;

    // Populate cuotas select (1..remainingInstallments)
    const cuotasSelect = document.getElementById("inst-cuotas-to-pay");
    if (cuotasSelect) {
      cuotasSelect.innerHTML = "";
      for (let i = 1; i <= remInst; i++) {
        const opt = document.createElement("option");
        opt.value = i;
        opt.textContent = `${i} ${i === 1 ? 'cuota' : 'cuotas'}`;
        cuotasSelect.appendChild(opt);
      }
      cuotasSelect.value = "1";
    }

    // Summary Box
    const summaryBox = document.getElementById("installment-summary-box");
    if (summaryBox) {
      const roleLabel = isReceivable ? "Cobro pendiente de:" : "Obligación pendiente con:";
      const paidInst = Math.max(0, totalInst - remInst);
      summaryBox.innerHTML = `
        <strong>${roleLabel} ${escapeHtml(data.counterparty)}</strong><br>
        Progreso: <strong>${paidInst}/${totalInst} cuotas canceladas</strong> (${remInst} restantes)<br>
        Valor por cuota: <strong>${formatCurrency(instAmt)}</strong> | Saldo restante: <strong>${formatCurrency(remAmt)}</strong>
      `;
    }

    // Dynamic Preview Calculation with exact cent handling on final cuota
    const updatePreview = () => {
      if (!cuotasSelect) return;
      const count = parseInt(cuotasSelect.value, 10) || 1;
      let totalToPay;
      if (count === remInst) {
        totalToPay = remAmt; // Exact remaining balance
      } else {
        totalToPay = Math.min(count * instAmt, remAmt);
      }
      const previewEl = document.getElementById("inst-calc-preview");
      const hintEl = document.getElementById("inst-calc-hint");
      if (previewEl) previewEl.textContent = formatCurrency(totalToPay);
      if (hintEl) {
        const remainingAfter = remInst - count;
        hintEl.textContent = remainingAfter === 0
          ? "🎉 ¡Esta operación liquidará el 100% de la deuda!"
          : `Quedarán ${remainingAfter} ${remainingAfter === 1 ? 'cuota' : 'cuotas'} pendientes tras este pago.`;
      }
    };

    if (cuotasSelect) {
      cuotasSelect.onchange = updatePreview;
      updatePreview();
    }

    const submitBtn = document.getElementById("btn-submit-installment");
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = isReceivable ? "Confirmar Cobro de Cuota" : "Confirmar Pago de Cuotas";
    }

    showModalSafe(installmentPayDialog);
  }

  function openSettleModal(debtId, data) {
    if (!settleDialog || !settleForm) return;
    settleForm.reset();
    settleForm.dataset.submitting = "false";

    const settleIdInput = document.getElementById("settle-debt-id");
    const settleAmtInput = document.getElementById("settle-amount");
    if (settleIdInput) settleIdInput.value = debtId;
    if (settleAmtInput) settleAmtInput.value = "";

    if (settleSummaryBox) {
      const typeLabel = data.type === "receivable" ? "Cobro a favor de:" : "Deuda por pagar a:";
      settleSummaryBox.innerHTML = `
        <strong>${typeLabel} ${escapeHtml(data.counterparty)}</strong><br>
        Saldo restante: <strong>${formatCurrency(data.remaining)}</strong>
      `;
    }

    const submitBtn = document.getElementById("btn-submit-settle");
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Confirmar Pago";
    }

    showModalSafe(settleDialog);
  }

  async function loadSubscriptions() {
    const list = document.getElementById("subscriptions-list");
    const countBadge = document.getElementById("subscriptions-count-badge");
    if (!list) return;

    try {
      const res = await fetch("/api/finance/subscriptions");
      if (!res.ok) throw new Error("Failed to load subscriptions");
      const raw = await res.json();
      const subs = Array.isArray(raw) ? raw : (raw.subscriptions || []);

      if (countBadge) countBadge.textContent = `${subs.length} Activas`;

      if (subs.length === 0) {
        list.innerHTML = '<div class="muted-row">No tienes suscripciones registradas.</div>';
        return;
      }

      list.innerHTML = subs.map(s => `
        <div class="sub-item">
          <div class="sub-item-header">
            <strong>${escapeHtml(s.name)}</strong>
            <span class="sub-item-cost">${formatCurrency(s.amount || (s.amount_cents / 100))}</span>
          </div>
          <div class="sub-item-details">
            <span>Día ${s.renewal_day || 15} de cada mes (${escapeHtml(s.billing_cycle || "mensual")})</span>
            <span class="badge badge-light">${escapeHtml(s.account_name || "Nu")}</span>
          </div>
          <div class="sub-item-footer">
            <small>Próxima renovación: ${s.next_payment_date ? s.next_payment_date.substring(0, 10) : "N/A"}</small>
          </div>
        </div>
      `).join("");
    } catch (err) {
      list.innerHTML = '<div class="muted-row">Error al cargar suscripciones</div>';
    }
  }

  async function loadPaymentCalendar() {
    const list = document.getElementById("payment-calendar-list");
    if (!list) return;

    try {
      const res = await fetch("/api/finance/calendar/payments?days_ahead=30");
      if (!res.ok) throw new Error("Failed to load payment calendar");
      const data = await res.json();
      const payments = Array.isArray(data) ? data : (data.upcoming_payments || []);

      if (payments.length === 0) {
        list.innerHTML = '<div class="muted-row">No tienes pagos programados en los próximos 30 días 🎉</div>';
        return;
      }

      const urgencyIcons = {
        "overdue": "🚨",
        "today": "⚠️",
        "soon": "🔔",
        "upcoming": "🗓️"
      };

      list.innerHTML = payments.map(p => {
        const icon = urgencyIcons[p.urgency] || "🗓️";
        const isIncome = p.direction === "inflow";
        const amtClass = isIncome ? "text-success" : "text-danger";
        const tag = isIncome ? "Cobro" : "Pago";
        const dueDate = p.due_date ? p.due_date.substring(0, 10) : "";

        return `
          <div class="timeline-item urgency-${escapeHtml(p.urgency || 'upcoming')}">
            <div class="timeline-icon">${icon}</div>
            <div class="timeline-info">
              <div class="timeline-title">${escapeHtml(p.title)} <span class="badge badge-light">${tag}</span></div>
              <div class="timeline-date">Fecha: ${dueDate} (${p.days_remaining} días)</div>
            </div>
            <div class="timeline-amount ${amtClass}">${isIncome ? "+" : "-"}${formatCurrency(p.amount)}</div>
          </div>
        `;
      }).join("");
    } catch (err) {
      list.innerHTML = '<div class="muted-row">Error al cargar cronograma de pagos</div>';
    }
  }

  // Forms Submissions
  if (transferForm) {
    transferForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (transferForm.dataset.submitting === "true") return;
      transferForm.dataset.submitting = "true";

      const submitBtn = document.getElementById("btn-submit-transfer");
      const originalText = submitBtn ? submitBtn.textContent : "Ejecutar Transferencia";
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Transfiriendo...";
      }

      const fromAcc = document.getElementById("txf-from-account").value;
      const toAcc = document.getElementById("txf-to-account").value;
      const amount = document.getElementById("txf-amount").value;
      const note = document.getElementById("txf-note").value;

      try {
        const res = await fetch("/api/finance/transfers", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            from_account: fromAcc,
            to_account: toAcc,
            amount: parseFloat(amount),
            note: note,
          }),
        });

        if (res.ok) {
          showAlert("¡Transferencia ejecutada exitosamente!");
          closeModalSafe(transferDialog);
          loadAccounts();
          loadFinancialSummary();
        } else {
          const errData = await res.json();
          showAlert(`Error: ${errData.detail || "Error en la transferencia"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al realizar transferencia", "error");
      } finally {
        transferForm.dataset.submitting = "false";
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
      }
    });
  }

  if (debtForm) {
    debtForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (debtForm.dataset.submitting === "true") return;
      debtForm.dataset.submitting = "true";

      const submitBtn = document.getElementById("btn-submit-debt");
      const originalText = submitBtn ? submitBtn.textContent : "Guardar Registro";
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Guardando...";
      }

      const debtType = document.getElementById("debt-type").value;
      const counterparty = document.getElementById("debt-counterparty").value;
      const amount = document.getElementById("debt-amount").value;
      const account = document.getElementById("debt-account").value;
      const reason = document.getElementById("debt-reason").value;
      const dueDate = document.getElementById("debt-due-date").value;
      const isInstallment = debtIsInstallmentChk ? debtIsInstallmentChk.checked : false;
      const totalInstallments = isInstallment ? (parseInt(document.getElementById("debt-total-installments").value, 10) || 6) : undefined;
      const paymentFrequency = isInstallment ? document.getElementById("debt-payment-frequency").value : undefined;

      try {
        const payload = {
          debt_type: debtType,
          counterparty: counterparty,
          amount: parseFloat(amount),
          account: account,
          reason: reason,
          due_date: dueDate || undefined,
        };
        if (isInstallment) {
          payload.is_installment = true;
          payload.total_installments = totalInstallments;
          payload.payment_frequency = paymentFrequency;
        }

        const res = await fetch("/api/finance/debts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        if (res.ok) {
          showAlert("¡Deuda o préstamo registrado exitosamente!");
          closeModalSafe(debtDialog);
          loadDebts();
          loadAccounts();
          loadPaymentCalendar();
        } else {
          const errData = await res.json();
          showAlert(`Error: ${errData.detail || "Error al registrar deuda"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al registrar deuda", "error");
      } finally {
        debtForm.dataset.submitting = "false";
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
      }
    });
  }

  if (settleForm) {
    settleForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (settleForm.dataset.submitting === "true") return;
      settleForm.dataset.submitting = "true";

      const submitBtn = document.getElementById("btn-submit-settle");
      const originalText = submitBtn ? submitBtn.textContent : "Confirmar Pago";
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Confirmando...";
      }

      const debtId = document.getElementById("settle-debt-id").value;
      const amountVal = document.getElementById("settle-amount").value;
      const account = document.getElementById("settle-account").value;
      const notes = document.getElementById("settle-notes").value;

      try {
        const body = {
          account: account,
          notes: notes,
        };
        if (amountVal && parseFloat(amountVal) > 0) {
          body.amount = parseFloat(amountVal);
        }

        const res = await fetch(`/api/finance/debts/${encodeURIComponent(debtId)}/settle`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });

        if (res.ok) {
          showAlert("¡Pago / liquidación procesada exitosamente!");
          closeModalSafe(settleDialog);
          loadDebts();
          loadAccounts();
          loadPaymentCalendar();
        } else {
          const errData = await res.json();
          showAlert(`Error: ${errData.detail || "Error al procesar pago"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al liquidar deuda", "error");
      } finally {
        settleForm.dataset.submitting = "false";
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
      }
    });
  }

  // Handle Debt Edit Submission (PATCH /api/finance/debts/{id})
  if (debtEditForm) {
    debtEditForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (debtEditForm.dataset.submitting === "true") return;
      debtEditForm.dataset.submitting = "true";

      const submitBtn = document.getElementById("btn-submit-debt-edit");
      const originalText = submitBtn ? submitBtn.textContent : "Guardar Cambios";
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Guardando...";
      }

      const debtId = document.getElementById("debt-edit-id").value;
      const counterparty = document.getElementById("debt-edit-counterparty").value;
      const amountVal = parseFloat(document.getElementById("debt-edit-amount").value);
      const reason = document.getElementById("debt-edit-reason").value;
      const dueDateVal = document.getElementById("debt-edit-due-date").value;
      const statusVal = document.getElementById("debt-edit-status").value;

      try {
        const body = {
          counterparty: counterparty,
          amount: amountVal,
          amount_cents: Math.round(amountVal * 100),
          reason: reason,
          due_date: dueDateVal || null,
          status: statusVal,
        };

        const res = await fetch(`/api/finance/debts/${encodeURIComponent(debtId)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });

        if (res.ok) {
          showAlert("¡Registro de deuda actualizado exitosamente!");
          closeModalSafe(debtEditDialog);
          refreshDashboard();
        } else {
          const errData = await res.json().catch(() => ({}));
          showAlert(`Error: ${errData.detail || "No se pudo actualizar la deuda"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al actualizar la deuda", "error");
      } finally {
        debtEditForm.dataset.submitting = "false";
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
      }
    });
  }

  // Handle Installment Payment Submission (POST /api/finance/debts/{id}/installments/pay)
  if (installmentPayForm) {
    installmentPayForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (installmentPayForm.dataset.submitting === "true") return;
      installmentPayForm.dataset.submitting = "true";

      const submitBtn = document.getElementById("btn-submit-installment");
      const originalText = submitBtn ? submitBtn.textContent : "Confirmar Pago";
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Procesando...";
      }

      const debtId = document.getElementById("inst-debt-id").value;
      const cuotasToPay = parseInt(document.getElementById("inst-cuotas-to-pay").value, 10);
      const accountVal = document.getElementById("inst-account").value;
      const notesVal = document.getElementById("inst-notes").value;

      try {
        const body = {
          installments_to_pay: cuotasToPay,
          account: accountVal,
          notes: notesVal || undefined,
        };

        const res = await fetch(`/api/finance/debts/${encodeURIComponent(debtId)}/installments/pay`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });

        if (res.ok) {
          showAlert(`¡Pago de ${cuotasToPay} cuota(s) registrado exitosamente!`);
          closeModalSafe(installmentPayDialog);
          refreshDashboard();
        } else {
          const errData = await res.json().catch(() => ({}));
          showAlert(`Error: ${errData.detail || "Error al procesar pago de cuotas"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al procesar el pago de cuotas", "error");
      } finally {
        installmentPayForm.dataset.submitting = "false";
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
      }
    });
  }

  if (subForm) {
    subForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (subForm.dataset.submitting === "true") return;
      subForm.dataset.submitting = "true";

      const submitBtn = document.getElementById("btn-submit-sub");
      const originalText = submitBtn ? submitBtn.textContent : "Guardar Suscripción";
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Guardando...";
      }

      const name = document.getElementById("sub-name").value;
      const amount = document.getElementById("sub-amount").value;
      const billingCycle = document.getElementById("sub-billing-cycle").value;
      const billingDay = document.getElementById("sub-billing-day").value;
      const account = document.getElementById("sub-account").value;
      const category = document.getElementById("sub-category").value;

      try {
        const res = await fetch("/api/finance/subscriptions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: name,
            amount: parseFloat(amount),
            billing_cycle: billingCycle,
            billing_day: parseInt(billingDay, 10),
            account: account,
            category: category,
          }),
        });

        if (res.ok) {
          showAlert("¡Suscripción guardada exitosamente!");
          closeModalSafe(subDialog);
          loadSubscriptions();
          loadPaymentCalendar();
        } else {
          const errData = await res.json();
          showAlert(`Error: ${errData.detail || "Error al guardar suscripción"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al guardar suscripción", "error");
      } finally {
        subForm.dataset.submitting = "false";
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
      }
    });
  }

  // ================= M11: Direct Account Balance Operations Logic =================

  // Real-time COP amount formatting with thousand separators (.)
  if (accountOpAmountInput) {
    accountOpAmountInput.addEventListener("input", () => {
      const rawDigits = accountOpAmountInput.value.replace(/\D/g, "");
      if (!rawDigits) {
        accountOpAmountInput.value = "";
        if (accountOpAmountRaw) accountOpAmountRaw.value = "";
        return;
      }
      const num = parseInt(rawDigits, 10);
      if (isNaN(num) || num <= 0) {
        accountOpAmountInput.value = "";
        if (accountOpAmountRaw) accountOpAmountRaw.value = "";
        return;
      }
      const formatted = rawDigits.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
      accountOpAmountInput.value = formatted;
      if (accountOpAmountRaw) accountOpAmountRaw.value = num.toString();
    });
  }

  function updateAccountOpModalUI(action, accountName) {
    const isDeposit = action === "deposit";
    if (accountOpDialogTitle) {
      accountOpDialogTitle.textContent = isDeposit
        ? `➕ Depositar en ${accountName || "Cuenta"}`
        : `➖ Retirar de ${accountName || "Cuenta"}`;
    }
    if (accountOpSubmitBtn) {
      accountOpSubmitBtn.textContent = isDeposit ? "Confirmar Depósito" : "Confirmar Retiro";
    }
    if (accountOpConcept) {
      accountOpConcept.placeholder = isDeposit
        ? "ej. Salario quincenal, Transferencia recibida, Recarga"
        : "ej. Retiro en cajero, Pago en efectivo, Gastos varios";
    }
  }

  if (accountOpTypeSelect) {
    accountOpTypeSelect.addEventListener("change", () => {
      const currentAcc = accountOpAccountName ? accountOpAccountName.value : "";
      updateAccountOpModalUI(accountOpTypeSelect.value, currentAcc);
    });
  }

  function openAccountOpModal(accountId, accountName, balance, action = "deposit") {
    if (!accountOpDialog) return;
    if (accountOpForm) {
      accountOpForm.reset();
      accountOpForm.dataset.submitting = "false";
    }
    if (accountOpAccountId) accountOpAccountId.value = accountId;
    if (accountOpAccountName) accountOpAccountName.value = accountName;
    if (accountOpTargetName) accountOpTargetName.textContent = accountName;
    if (accountOpCurrentBalance) accountOpCurrentBalance.textContent = formatCurrency(balance);
    if (accountOpTypeSelect) accountOpTypeSelect.value = action;
    if (accountOpAmountRaw) accountOpAmountRaw.value = "";
    if (accountOpAmountInput) accountOpAmountInput.value = "";
    if (accountOpNotes) accountOpNotes.value = "";

    updateAccountOpModalUI(action, accountName);

    if (accountOpSubmitBtn) {
      accountOpSubmitBtn.disabled = false;
    }

    showModalSafe(accountOpDialog);
    if (accountOpAmountInput) {
      setTimeout(() => accountOpAmountInput.focus(), 100);
    }
  }

  // Event delegation on accounts-grid for all card action buttons
  const accountsGrid = document.getElementById("accounts-grid");
  if (accountsGrid) {
    accountsGrid.addEventListener("click", (e) => {
      const btn = e.target.closest(".btn-account-op");
      if (!btn) return;
      const id = btn.getAttribute("data-id");
      const name = btn.getAttribute("data-name");
      const balance = parseFloat(btn.getAttribute("data-balance") || "0");
      const action = btn.getAttribute("data-action") || "deposit";
      openAccountOpModal(id, name, balance, action);
    });
  }

  if (accountOpForm) {
    accountOpForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (accountOpForm.dataset.submitting === "true") return;
      accountOpForm.dataset.submitting = "true";

      const submitBtn = document.getElementById("btn-submit-account-op");
      const originalText = submitBtn ? submitBtn.textContent : "Confirmar Operación";
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Procesando...";
      }

      const accountId = (accountOpAccountId ? accountOpAccountId.value : "").trim();
      const accountName = (accountOpAccountName ? accountOpAccountName.value : "").trim();
      const operation = accountOpTypeSelect ? accountOpTypeSelect.value : "deposit";
      const rawDigits = (accountOpAmountInput ? accountOpAmountInput.value : "").replace(/\D/g, "");
      const amount = parseInt(rawDigits, 10);
      const concept = (accountOpConcept ? accountOpConcept.value : "").trim();
      const notes = (accountOpNotes ? accountOpNotes.value : "").trim();

      if (isNaN(amount) || amount <= 0) {
        showAlert("Por favor ingresa un monto válido mayor a 0 COP.", "error");
        accountOpForm.dataset.submitting = "false";
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
        return;
      }

      try {
        const payload = {
          action: operation,
          operation: operation,
          amount: amount,
          amount_cents: Math.round(amount * 100),
          concept: concept || (operation === "deposit" ? "Depósito" : "Retiro"),
          notes: notes || undefined,
        };

        const res = await fetch(`/api/finance/accounts/${encodeURIComponent(accountId)}/operations`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        if (res.ok) {
          const opLabel = operation === "deposit" ? "Depósito" : "Retiro";
          showAlert(`¡${opLabel} de ${formatCurrency(amount)} en ${accountName} realizado exitosamente!`);
          closeModalSafe(accountOpDialog);
          refreshDashboard();
        } else {
          const errData = await res.json().catch(() => ({}));
          showAlert(`Error: ${errData.detail || "Error al procesar la operación de cuenta"}`, "error");
        }
      } catch (err) {
        console.error("Network error during account operation:", err);
        showAlert("Error de red al procesar la operación de cuenta.", "error");
      } finally {
        accountOpForm.dataset.submitting = "false";
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
      }
    });
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function refreshDashboard() {
    loadFinancialSummary();
    loadCategories();
    loadTransactions();
    loadTasks();
    loadEmailDigest();
    loadOutings();
    loadAccounts();
    loadDebts();
    loadSubscriptions();
    loadPaymentCalendar();
  }

  // Initial load
  refreshDashboard();
});
