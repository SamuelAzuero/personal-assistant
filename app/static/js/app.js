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

  // ================= Modal Dialog Controls =================
  if (btnOpenTx && txDialog) {
    btnOpenTx.addEventListener("click", () => {
      txForm.reset();
      const dateInput = document.getElementById("tx-date");
      if (dateInput) {
        dateInput.value = new Date().toISOString().split("T")[0];
      }
      txDialog.showModal();
    });
  }
  if (btnCloseTx && txDialog) {
    btnCloseTx.addEventListener("click", () => txDialog.close());
  }
  if (btnCancelTx && txDialog) {
    btnCancelTx.addEventListener("click", () => txDialog.close());
  }

  if (btnOpenTask && taskDialog) {
    btnOpenTask.addEventListener("click", () => {
      taskForm.reset();
      taskDialog.showModal();
    });
  }
  if (btnCloseTask && taskDialog) {
    btnCloseTask.addEventListener("click", () => taskDialog.close());
  }
  if (btnCancelTask && taskDialog) {
    btnCancelTask.addEventListener("click", () => taskDialog.close());
  }

  // Transfer Dialog
  const openTransferModal = () => {
    if (transferForm) transferForm.reset();
    if (transferDialog) transferDialog.showModal();
  };
  if (btnOpenTransfer) btnOpenTransfer.addEventListener("click", openTransferModal);
  if (btnQuickTransfer) btnQuickTransfer.addEventListener("click", openTransferModal);
  if (btnCloseTransfer && transferDialog) {
    btnCloseTransfer.addEventListener("click", () => transferDialog.close());
  }
  if (btnCancelTransfer && transferDialog) {
    btnCancelTransfer.addEventListener("click", () => transferDialog.close());
  }

  // Debt Dialog
  const openDebtModal = () => {
    if (debtForm) {
      debtForm.reset();
      const dateInput = document.getElementById("debt-due-date");
      if (dateInput) {
        // default to 7 days from now
        const d = new Date();
        d.setDate(d.getDate() + 7);
        dateInput.value = d.toISOString().split("T")[0];
      }
    }
    if (debtDialog) debtDialog.showModal();
  };
  if (btnOpenDebt) btnOpenDebt.addEventListener("click", openDebtModal);
  if (btnQuickDebt) btnQuickDebt.addEventListener("click", openDebtModal);
  if (btnCloseDebt && debtDialog) {
    btnCloseDebt.addEventListener("click", () => debtDialog.close());
  }
  if (btnCancelDebt && debtDialog) {
    btnCancelDebt.addEventListener("click", () => debtDialog.close());
  }

  // Settle Dialog Cancel
  if (btnCloseSettle && settleDialog) {
    btnCloseSettle.addEventListener("click", () => settleDialog.close());
  }
  if (btnCancelSettle && settleDialog) {
    btnCancelSettle.addEventListener("click", () => settleDialog.close());
  }

  // Subscription Dialog
  const openSubModal = () => {
    if (subForm) subForm.reset();
    if (subDialog) subDialog.showModal();
  };
  if (btnOpenSub) btnOpenSub.addEventListener("click", openSubModal);
  if (btnQuickSub) btnQuickSub.addEventListener("click", openSubModal);
  if (btnCloseSub && subDialog) {
    btnCloseSub.addEventListener("click", () => subDialog.close());
  }
  if (btnCancelSub && subDialog) {
    btnCancelSub.addEventListener("click", () => subDialog.close());
  }

  // Close modals on clicking backdrop
  [txDialog, taskDialog, transferDialog, debtDialog, settleDialog, subDialog].forEach(dialog => {
    if (!dialog) return;
    dialog.addEventListener("click", (e) => {
      const rect = dialog.getBoundingClientRect();
      const isInDialog = (
        rect.top <= e.clientY && e.clientY <= rect.top + rect.height &&
        rect.left <= e.clientX && e.clientX <= rect.left + rect.width
      );
      if (!isInDialog) {
        dialog.close();
      }
    });
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

  async function loadOutings() {
    const container = document.getElementById("outings-list");
    if (!container) return;

    try {
      const res = await fetch("/api/research/outings?location=downtown");
      if (!res.ok) throw new Error("Failed to load outings");
      const places = await res.json();

      const items = (Array.isArray(places) ? places : []).slice(0, 3);
      if (items.length === 0) {
        container.innerHTML = `<div class="muted-row">No se encontraron recomendaciones en este momento.</div>`;
        return;
      }

      container.innerHTML = items.map(p => `
        <div class="widget-item">
          <div class="widget-item-title">
            ${escapeHtml(p.name || "Lugar")} 
            <span class="text-primary">(${p.rating || "4.5"} ⭐ | ${p.price_tier || "$$"})</span>
          </div>
          <div class="widget-item-snippet">${escapeHtml(p.description || "")}</div>
          <div class="widget-item-meta">
            <span>📍 ${escapeHtml(p.address || "Zona Rosa / Centro")}</span>
            ${p.amenities ? `<span>✨ ${escapeHtml(p.amenities.join(", "))}</span>` : ''}
          </div>
        </div>
      `).join("");
    } catch (err) {
      console.error("Error loading outings:", err);
      container.innerHTML = `<div class="muted-row text-muted">Servicio de planes en modo simulado / sin conexión.</div>`;
    }
  }

  // ================= Form Submissions =================

  if (txForm) {
    txForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const amount = parseFloat(document.getElementById("tx-amount").value);
      const type = document.getElementById("tx-type").value;
      const category = document.getElementById("tx-category").value;
      const description = document.getElementById("tx-description").value;
      const dateVal = document.getElementById("tx-date").value;

      try {
        const res = await fetch("/api/finance/transactions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            amount: amount,
            type: type,
            category: category,
            description: description,
            date: dateVal ? `${dateVal}T12:00:00Z` : undefined,
          }),
        });

        if (res.ok) {
          showAlert("¡Transacción registrada exitosamente!");
          txDialog.close();
          refreshDashboard();
        } else {
          const errData = await res.json();
          showAlert(`Error: ${errData.detail || "Error en la validación"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al registrar transacción", "error");
      }
    });
  }

  if (taskForm) {
    taskForm.addEventListener("submit", async (e) => {
      e.preventDefault();
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
          taskDialog.close();
          loadTasks();
        } else {
          const errData = await res.json();
          showAlert(`Error: ${errData.detail || "Error en la validación"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al crear tarea", "error");
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
        html += `
          <div class="account-card" style="border-top: 4px solid ${escapeHtml(color)}">
            <div class="account-header">
              <span class="account-icon">${icon}</span>
              <span class="account-type-tag">${escapeHtml(acc.name)}</span>
            </div>
            <div class="account-balance">${formatCurrency(acc.balance || (acc.balance_cents / 100))}</div>
            <div class="account-share-bar">
              <div class="account-share-fill" style="width: ${Math.min(100, Math.max(0, share))}%; background: ${escapeHtml(color)}"></div>
            </div>
            <div class="account-footer">${share}% del patrimonio neto</div>
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

      if (recTbody) {
        if (receivables.length === 0) {
          recTbody.innerHTML = '<tr><td colspan="7" class="text-center muted-row">No tienes cobros pendientes 🎉</td></tr>';
        } else {
          recTbody.innerHTML = receivables.map(d => {
            const dueDateStr = d.due_date ? String(d.due_date).substring(0, 10) : "Sin fecha";
            const badgeClass = d.status === "partially_paid" ? "badge-warning" : "badge-info";
            const statusLabel = d.status === "partially_paid" ? "Abono Parcial" : "Pendiente";
            return `
              <tr>
                <td><strong>${escapeHtml(d.counterparty)}</strong></td>
                <td>${escapeHtml(d.reason)}</td>
                <td><span class="badge badge-light">${escapeHtml(d.account_name || "Efectivo")}</span></td>
                <td>${formatCurrency(d.remaining_amount || (d.remaining_cents / 100))}</td>
                <td>${dueDateStr}</td>
                <td><span class="badge ${badgeClass}">${statusLabel}</span></td>
                <td class="text-center">
                  <button class="btn btn-sm btn-outline-success btn-open-settle"
                    data-id="${escapeHtml(d.id || d.debt_id)}"
                    data-counterparty="${escapeHtml(d.counterparty)}"
                    data-remaining="${d.remaining_amount || (d.remaining_cents / 100)}"
                    data-cents="${d.remaining_cents}"
                    data-type="receivable">Abonar / Liquidar</button>
                </td>
              </tr>
            `;
          }).join("");
        }
      }

      if (payTbody) {
        if (payables.length === 0) {
          payTbody.innerHTML = '<tr><td colspan="7" class="text-center muted-row">No tienes deudas pendientes 🎉</td></tr>';
        } else {
          payTbody.innerHTML = payables.map(d => {
            const dueDateStr = d.due_date ? String(d.due_date).substring(0, 10) : "Sin fecha";
            const badgeClass = d.status === "partially_paid" ? "badge-warning" : "badge-danger";
            const statusLabel = d.status === "partially_paid" ? "Abono Parcial" : "Pendiente";
            return `
              <tr>
                <td><strong>${escapeHtml(d.counterparty)}</strong></td>
                <td>${escapeHtml(d.reason)}</td>
                <td><span class="badge badge-light">${escapeHtml(d.account_name || "Efectivo")}</span></td>
                <td>${formatCurrency(d.remaining_amount || (d.remaining_cents / 100))}</td>
                <td>${dueDateStr}</td>
                <td><span class="badge ${badgeClass}">${statusLabel}</span></td>
                <td class="text-center">
                  <button class="btn btn-sm btn-outline-primary btn-open-settle"
                    data-id="${escapeHtml(d.id || d.debt_id)}"
                    data-counterparty="${escapeHtml(d.counterparty)}"
                    data-remaining="${d.remaining_amount || (d.remaining_cents / 100)}"
                    data-cents="${d.remaining_cents}"
                    data-type="debt">Pagar / Abonar</button>
                </td>
              </tr>
            `;
          }).join("");
        }
      }

      document.querySelectorAll(".btn-open-settle").forEach(btn => {
        btn.addEventListener("click", () => {
          const debtId = btn.getAttribute("data-id");
          const counterparty = btn.getAttribute("data-counterparty");
          const remaining = btn.getAttribute("data-remaining");
          const type = btn.getAttribute("data-type");

          const settleIdInput = document.getElementById("settle-debt-id");
          const settleAmtInput = document.getElementById("settle-amount");
          if (settleIdInput) settleIdInput.value = debtId;
          if (settleAmtInput) settleAmtInput.value = "";

          if (settleSummaryBox) {
            const typeLabel = type === "receivable" ? "Cobro a favor de:" : "Deuda por pagar a:";
            settleSummaryBox.innerHTML = `
              <strong>${typeLabel} ${escapeHtml(counterparty)}</strong><br>
              Saldo restante: <strong>${formatCurrency(remaining)}</strong>
            `;
          }

          if (settleDialog) settleDialog.showModal();
        });
      });

    } catch (err) {
      if (recTbody) recTbody.innerHTML = '<tr><td colspan="7" class="text-center muted-row">Error al cargar cobros</td></tr>';
      if (payTbody) payTbody.innerHTML = '<tr><td colspan="7" class="text-center muted-row">Error al cargar deudas</td></tr>';
    }
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
          transferDialog.close();
          loadAccounts();
          loadFinancialSummary();
        } else {
          const errData = await res.json();
          showAlert(`Error: ${errData.detail || "Error en la transferencia"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al realizar transferencia", "error");
      }
    });
  }

  if (debtForm) {
    debtForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const debtType = document.getElementById("debt-type").value;
      const counterparty = document.getElementById("debt-counterparty").value;
      const amount = document.getElementById("debt-amount").value;
      const account = document.getElementById("debt-account").value;
      const reason = document.getElementById("debt-reason").value;
      const dueDate = document.getElementById("debt-due-date").value;

      try {
        const res = await fetch("/api/finance/debts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            debt_type: debtType,
            counterparty: counterparty,
            amount: parseFloat(amount),
            account: account,
            reason: reason,
            due_date: dueDate || undefined,
          }),
        });

        if (res.ok) {
          showAlert("¡Deuda o préstamo registrado exitosamente!");
          debtDialog.close();
          loadDebts();
          loadAccounts();
          loadPaymentCalendar();
        } else {
          const errData = await res.json();
          showAlert(`Error: ${errData.detail || "Error al registrar deuda"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al registrar deuda", "error");
      }
    });
  }

  if (settleForm) {
    settleForm.addEventListener("submit", async (e) => {
      e.preventDefault();
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
          settleDialog.close();
          loadDebts();
          loadAccounts();
          loadPaymentCalendar();
        } else {
          const errData = await res.json();
          showAlert(`Error: ${errData.detail || "Error al procesar pago"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al liquidar deuda", "error");
      }
    });
  }

  if (subForm) {
    subForm.addEventListener("submit", async (e) => {
      e.preventDefault();
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
          subDialog.close();
          loadSubscriptions();
          loadPaymentCalendar();
        } else {
          const errData = await res.json();
          showAlert(`Error: ${errData.detail || "Error al guardar suscripción"}`, "error");
        }
      } catch (err) {
        showAlert("Error de red al guardar suscripción", "error");
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
