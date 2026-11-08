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
      // Set today's date default
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

  // Close modals on clicking backdrop
  [txDialog, taskDialog].forEach(dialog => {
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
  }

  // Initial load
  refreshDashboard();
});
