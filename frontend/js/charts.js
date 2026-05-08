Chart.defaults.color = '#8b90b8';
Chart.defaults.borderColor = '#2e3350';
Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';

const CHART_COLORS = {
  accent:  '#6c63ff',
  green:   '#00d4aa',
  danger:  '#ff4757',
  warn:    '#ffa502',
  protein: '#4ade80',
  carbs:   '#facc15',
  fat:     '#f97316',
};

let chartInstances = {};

function destroyChart(id) {
  if (chartInstances[id]) {
    chartInstances[id].destroy();
    delete chartInstances[id];
  }
}

function renderCalorieChart(data) {
  destroyChart('calories');
  const ctx = document.getElementById('chartCalories');
  if (!ctx || !data.length) return;

  chartInstances.calories = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.map(d => formatDateShort(d.date)),
      datasets: [
        {
          label: 'Assunte',
          data: data.map(d => d.calories_in),
          backgroundColor: 'rgba(108,99,255,.7)',
          borderRadius: 4,
        },
        {
          label: 'Bruciate',
          data: data.map(d => d.calories_out),
          backgroundColor: 'rgba(0,212,170,.6)',
          borderRadius: 4,
        },
        {
          label: 'Obiettivo',
          data: data.map(d => d.goal),
          type: 'line',
          borderColor: CHART_COLORS.warn,
          borderDash: [5,3],
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'top' } },
      scales: {
        x: { grid: { display: false } },
        y: { grid: { color: '#2e3350' } },
      },
    },
  });
}

function renderWeightChart(data, canvasId = 'chartWeight') {
  destroyChart(canvasId);
  const ctx = document.getElementById(canvasId);
  if (!ctx || !data.length) return;

  chartInstances[canvasId] = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.map(d => formatDateShort(d.health_date)),
      datasets: [{
        label: 'Peso (kg)',
        data: data.map(d => d.weight_kg),
        borderColor: CHART_COLORS.accent,
        backgroundColor: 'rgba(108,99,255,.1)',
        borderWidth: 2,
        pointRadius: 3,
        fill: true,
        tension: 0.3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false } },
        y: {
          grid: { color: '#2e3350' },
          ticks: { callback: v => v + ' kg' },
        },
      },
    },
  });
}

function renderSleepStepsChart(healthData) {
  destroyChart('sleep');
  const ctx = document.getElementById('chartSleep');
  if (!ctx || !healthData.length) return;

  chartInstances.sleep = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: healthData.map(d => formatDateShort(d.health_date)),
      datasets: [
        {
          label: 'Sonno (h)',
          data: healthData.map(d => d.sleep_hours),
          backgroundColor: 'rgba(108,99,255,.7)',
          borderRadius: 4,
          yAxisID: 'y',
        },
        {
          label: 'Passi (÷1000)',
          data: healthData.map(d => (d.steps || 0) / 1000),
          backgroundColor: 'rgba(0,212,170,.6)',
          borderRadius: 4,
          yAxisID: 'y',
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'top' } },
      scales: {
        x: { grid: { display: false } },
        y: { grid: { color: '#2e3350' } },
      },
    },
  });
}

function formatDateShort(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit' });
}
