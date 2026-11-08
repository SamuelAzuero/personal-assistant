/**
 * Autonomous Personal Assistant - Financial Charting Module (Chart.js)
 */

let categoryChartInstance = null;
let trendChartInstance = null;

const CHART_PALETTE = [
  "#3b82f6", // Blue
  "#10b981", // Emerald
  "#f59e0b", // Amber
  "#ef4444", // Red
  "#8b5cf6", // Purple
  "#06b6d4", // Cyan
  "#ec4899", // Pink
  "#f97316", // Orange
  "#6366f1", // Indigo
  "#64748b", // Slate
];

/**
 * Render or update the spending by category donut chart.
 * @param {Array<{category: string, total_cents: number, total: number}>} categoryData
 */
function renderCategoryChart(categoryData) {
  const canvas = document.getElementById("categoryChart");
  if (!canvas || typeof Chart === "undefined") return;

  // Filter categories with positive spending
  const expenses = (categoryData || []).filter(item => {
    const val = item.total || (item.total_cents ? item.total_cents / 100 : 0);
    return val > 0 && item.category !== "Income";
  });

  const labels = expenses.length > 0 
    ? expenses.map(e => e.category) 
    : ["Sin gastos aún"];
  
  const values = expenses.length > 0 
    ? expenses.map(e => (e.total || (e.total_cents ? e.total_cents / 100 : 0))) 
    : [1];

  const backgroundColors = expenses.length > 0 
    ? labels.map((_, i) => CHART_PALETTE[i % CHART_PALETTE.length]) 
    : ["#334155"];

  if (categoryChartInstance) {
    categoryChartInstance.destroy();
  }

  const ctx = canvas.getContext("2d");
  categoryChartInstance = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: labels,
      datasets: [{
        data: values,
        backgroundColor: backgroundColors,
        borderWidth: 2,
        borderColor: "#151d2f",
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "right",
          labels: {
            color: "#94a3b8",
            font: { family: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", size: 11 },
            boxWidth: 12,
            padding: 10,
          },
        },
        tooltip: {
          callbacks: {
            label: function(context) {
              const label = context.label || "";
              const val = context.raw || 0;
              return `${label}: $${Number(val).toLocaleString("es-CO", { maximumFractionDigits: 0 })} COP`;
            }
          }
        }
      },
      cutout: "68%",
    },
  });
}

/**
 * Render or update the monthly spending and income trend chart.
 * @param {{total_income: number, total_expenses: number, net_balance: number}} summary
 */
function renderTrendChart(summary) {
  const canvas = document.getElementById("trendChart");
  if (!canvas || typeof Chart === "undefined") return;

  const income = summary ? (summary.total_income || 0) : 0;
  const expense = summary ? (summary.total_expenses || 0) : 0;
  const net = summary ? (summary.net_balance || 0) : 0;

  if (trendChartInstance) {
    trendChartInstance.destroy();
  }

  const ctx = canvas.getContext("2d");
  trendChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels: ["Ingresos Totales", "Gastos Totales", "Ahorro Neto"],
      datasets: [{
        label: "Monto ($ COP)",
        data: [income, expense, net],
        backgroundColor: [
          "#10b981", // Green for income
          "#ef4444", // Red for expense
          net >= 0 ? "#3b82f6" : "#f59e0b", // Blue / amber for net
        ],
        borderRadius: 6,
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(context) {
              const val = context.raw || 0;
              return `$${Number(val).toLocaleString("es-CO", { maximumFractionDigits: 0 })} COP`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: "#94a3b8", font: { size: 11 } },
        },
        y: {
          grid: { color: "rgba(51, 65, 85, 0.4)" },
          ticks: {
            color: "#94a3b8",
            callback: function(val) { return "$" + Number(val).toLocaleString("es-CO", { maximumFractionDigits: 0 }); },
            font: { size: 11 },
          },
        },
      },
    },
  });
}

// Export functions to global scope for app.js
window.renderCategoryChart = renderCategoryChart;
window.renderTrendChart = renderTrendChart;
