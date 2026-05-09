// ─── State ────────────────────────────────────────────────────────
let USER_ID = localStorage.getItem('fitness_user_id') || '';
let nutritionDate = new Date().toLocaleDateString('sv-SE');
let overviewDate = new Date().toLocaleDateString('sv-SE');
let currentModal = null;
let editingMealId = null;
let editingActivityId = null;
let editingRoutineId = null;
let editingExerciseId = null;
const mealsCache = {};       // id → meal object
const activitiesCache = {};  // id → activity object
const routinesCache = {};    // id → routine object
const exercisesCache = {};   // id → exercise object

// ─── Init ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('headerDate').textContent =
    new Date().toLocaleDateString('it-IT', { weekday:'long', day:'numeric', month:'long', year:'numeric' });

  setupNavigation();

  if (!USER_ID) {
    USER_ID = prompt('Inserisci il tuo User ID Supabase (vedi README per come ottenerlo):') || '';
    if (USER_ID) localStorage.setItem('fitness_user_id', USER_ID);
  }

  if (USER_ID) {
    loadOverview();
    loadUserSidebar();
  }

  updateNutritionDateLabel();
});

// ─── Navigation ───────────────────────────────────────────────────
function setupNavigation() {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', e => {
      e.preventDefault();
      const tab = item.dataset.tab;
      document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
      item.classList.add('active');
      document.getElementById('tab-' + tab).classList.add('active');
      onTabSwitch(tab);
    });
  });
}

function onTabSwitch(tab) {
  if (tab === 'overview') loadOverview();
  if (tab === 'nutrition') loadNutrition();
  if (tab === 'activities') loadActivities();
  if (tab === 'exercises') loadExercises();
  if (tab === 'training') loadTraining();
  if (tab === 'health') loadHealth();
  if (tab === 'settings') loadSettings();
  if (tab === 'goals') loadGoals();
}

async function refreshAll() {
  const activeTab = document.querySelector('.nav-item.active')?.dataset.tab || 'overview';
  onTabSwitch(activeTab);
}

// ─── Overview ─────────────────────────────────────────────────────
function changeOverviewDate(delta) {
  const [y, m, d] = overviewDate.split('-').map(Number);
  const next = new Date(y, m - 1, d + delta);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  if (next > today) return;
  overviewDate = next.toLocaleDateString('sv-SE');
  loadOverview();
}

function updateOverviewDateLabel() {
  const [y, m, d] = overviewDate.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  const todayStr = new Date().toLocaleDateString('sv-SE');
  const isToday = overviewDate === todayStr;
  const label = isToday ? 'Oggi' : dt.toLocaleDateString('it-IT', { day:'2-digit', month:'2-digit', year:'numeric' });
  document.getElementById('overviewDate').textContent = label;
  const nextBtn = document.getElementById('overviewNextBtn');
  if (nextBtn) nextBtn.disabled = isToday;
}

async function loadOverview() {
  if (!USER_ID) return;
  updateOverviewDateLabel();

  // KPI e macros: caricamento critico, indipendente dai grafici
  try {
    const today = await api.today(USER_ID, overviewDate);
    renderKPIs(today);
    renderMacros(today);
  } catch (e) {
    console.error('loadOverview KPI error', e);
  }

  // Grafici e attività: caricamento opzionale, errori non bloccano i KPI
  const [calTrend, weightTrend, weekData] = await Promise.allSettled([
    api.calorieTrend(USER_ID, 30),
    api.weightTrend(USER_ID, 60),
    api.week(USER_ID, 0),
  ]);

  if (calTrend.status === 'fulfilled') renderCalorieChart(calTrend.value);
  if (weightTrend.status === 'fulfilled') renderWeightChart(weightTrend.value);
  if (weekData.status === 'fulfilled') renderWeeklyActivities(weekData.value.days);

  loadGoals();
}

function renderKPIs(today) {
  setText('kpiCalIn', Math.round(today.calories_in) + ' kcal');
  setText('kpiCalOut', Math.round(today.calories_out) + ' kcal');

  const sourceEl = document.getElementById('kpiCalOutSource');
  if (sourceEl) {
    if (today.total_calories_iphone) {
      sourceEl.textContent = 'da iPhone Fitness ✓';
      sourceEl.style.color = 'var(--accent)';
    } else if (today.bmr) {
      sourceEl.textContent = `stima BMR — inserisci il totale da app Fitness`;
      sourceEl.style.color = 'var(--text2)';
    } else {
      sourceEl.textContent = '';
    }
  }

  const net = today.net_calories;
  const netEl = document.getElementById('kpiBalance');
  netEl.textContent = (net >= 0 ? '+' : '') + Math.round(net) + ' kcal';
  netEl.style.color = net > 0 ? '#ff4757' : '#00d4aa';

  setText('kpiCalGoal', '/ ' + today.calorie_goal + ' kcal');
  setText('kpiWeight', today.weight_kg ? today.weight_kg + ' kg' : '—');

  const pct = Math.min(100, (today.calories_in / today.calorie_goal) * 100);
  setWidth('kpiCalInBar', pct + '%');
}

function renderMacros(today) {
  const macros = [
    { key: 'Protein', val: today.protein_g, goal: today.protein_goal_g },
    { key: 'Carbs',   val: today.carbs_g,   goal: today.carbs_goal_g },
    { key: 'Fat',     val: today.fat_g,     goal: today.fat_goal_g },
  ];
  macros.forEach(m => {
    setText('macro' + m.key, Math.round(m.val) + 'g');
    setText('macro' + m.key + 'Goal', (m.goal || '—') + 'g');
    const pct = m.goal ? Math.min(100, (m.val / m.goal) * 100) : 0;
    setWidth('macro' + m.key + 'Bar', pct + '%');
  });
}

function renderWeeklyActivities(days) {
  const container = document.getElementById('weeklyActivities');
  const acts = days.flatMap(d => d.activities || []);
  if (!acts.length) { container.innerHTML = '<p style="color:var(--text2)">Nessuna attività questa settimana</p>'; return; }
  container.innerHTML = acts.map(a => activityItemHtml(a)).join('');
}

// ─── Nutrition ────────────────────────────────────────────────────
async function loadNutrition() {
  if (!USER_ID) return;
  const meals = await api.getMeals(USER_ID, nutritionDate).catch(() => []);
  renderMealGroups(meals);
}

function renderMealGroups(meals) {
  const groups = { breakfast: [], lunch: [], dinner: [], snack: [] };
  const labels = { breakfast: '🌅 Colazione', lunch: '☀️ Pranzo', dinner: '🌙 Cena', snack: '🍎 Spuntini' };

  meals.forEach(m => {
    mealsCache[m.id] = m;
    const key = m.meal_time || 'snack';
    if (groups[key]) groups[key].push(m);
    else groups.snack.push(m);
  });

  const container = document.getElementById('mealGroups');
  container.innerHTML = Object.entries(groups).map(([key, items]) => {
    if (!items.length) return '';
    const totalCal = items.reduce((s, m) => s + (m.calories || 0), 0);
    return `
      <div class="meal-group">
        <div class="meal-group-header">
          <span>${labels[key]}</span>
          <span>${Math.round(totalCal)} kcal</span>
        </div>
        ${items.map(m => `
          <div class="meal-item">
            <div style="flex:1">
              <div class="meal-item-name">${esc(m.name)}</div>
              <div class="meal-item-macros">P: ${m.protein_g}g · C: ${m.carbs_g}g · G: ${m.fat_g}g${m.quantity_g ? ' · ' + m.quantity_g + 'g' : ''}</div>
            </div>
            <div style="display:flex;align-items:center;gap:.4rem">
              <span class="meal-item-cals">${Math.round(m.calories)} kcal</span>
              <button class="meal-delete" onclick="openEditMealModal('${m.id}')" title="Modifica">✏️</button>
              <button class="meal-delete" onclick="deleteMeal('${m.id}')" title="Elimina">🗑</button>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }).join('');
}

function changeNutritionDate(delta) {
  const [y, m, d] = nutritionDate.split('-').map(Number);
  const next = new Date(y, m - 1, d + delta);   // aritmetica locale, nessuna conversione UTC
  const today = new Date();
  // non andare oltre oggi
  if (next > today) return;
  nutritionDate = [
    next.getFullYear(),
    String(next.getMonth() + 1).padStart(2, '0'),
    String(next.getDate()).padStart(2, '0'),
  ].join('-');
  updateNutritionDateLabel();
  loadNutrition();
}

function goToToday() {
  nutritionDate = new Date().toLocaleDateString('sv-SE'); // 'sv-SE' usa formato YYYY-MM-DD
  updateNutritionDateLabel();
  loadNutrition();
}

function updateNutritionDateLabel() {
  const [y, m, d] = nutritionDate.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  const today = new Date().toLocaleDateString('sv-SE');
  const isToday = nutritionDate === today;

  document.getElementById('nutritionDateLabel').textContent = isToday
    ? 'Oggi · ' + date.toLocaleDateString('it-IT', { day:'numeric', month:'short' })
    : date.toLocaleDateString('it-IT', { weekday:'short', day:'numeric', month:'short' });

  const fwdBtn = document.getElementById('btnNutritionForward');
  const todayBtn = document.getElementById('btnNutritionToday');
  if (fwdBtn) fwdBtn.style.display = isToday ? 'none' : '';
  if (todayBtn) todayBtn.style.display = isToday ? 'none' : '';
}

async function deleteMeal(id) {
  if (!confirm('Elimina questo pasto?')) return;
  await api.deleteMeal(id);
  loadNutrition();
}

// ─── Activities ───────────────────────────────────────────────────
async function loadActivities() {
  if (!USER_ID) return;
  const acts = await api.getActivities(USER_ID, 30).catch(() => []);
  acts.forEach(a => { activitiesCache[a.id] = a; });
  document.getElementById('activitiesList').innerHTML =
    acts.length ? acts.map(a => activityItemHtml(a)).join('') : '<p style="color:var(--text2)">Nessuna attività registrata</p>';
}

const ACTIVITY_ICONS = { run:'🏃', ride:'🚴', swim:'🏊', walk:'🚶', hike:'🥾', strength:'🏋️', yoga:'🧘', other:'⚡' };

function activityItemHtml(a) {
  const icon = ACTIVITY_ICONS[a.activity_type] || '⚡';
  const stats = [
    a.duration_min && `⏱ ${a.duration_min}min`,
    a.distance_km && `📍 ${a.distance_km}km`,
    a.elevation_m && `⛰ ${a.elevation_m}m`,
    a.avg_heart_rate && `❤️ ${a.avg_heart_rate}bpm`,
    a.rpe && `RPE ${a.rpe}/10`,
  ].filter(Boolean);

  const conditionPills = [
    a.sleep_hours   && `💤 ${a.sleep_hours}h sonno`,
    a.stress_level  && `😤 stress ${a.stress_level}/10`,
  ].filter(Boolean);

  const conditionRows = [
    a.condition_pre    && `<div class="condition-row"><span class="condition-label">Prima:</span> <span>${esc(a.condition_pre)}</span></div>`,
    a.condition_during && `<div class="condition-row"><span class="condition-label">Durante:</span> <span>${esc(a.condition_during)}</span></div>`,
    a.condition_post   && `<div class="condition-row"><span class="condition-label">Dopo:</span> <span>${esc(a.condition_post)}</span></div>`,
    a.physical_notes   && `<div class="condition-row" style="color:var(--danger)"><span class="condition-label">⚠ Fisico:</span> <span>${esc(a.physical_notes)}</span></div>`,
  ].filter(Boolean);

  const hasCondition = conditionPills.length || conditionRows.length;

  return `
    <div class="activity-item">
      <span class="activity-type-icon">${icon}</span>
      <div class="activity-info" style="flex:1;min-width:0">
        <div class="activity-name">${esc(a.name)}</div>
        <div class="activity-meta">${a.activity_date} · ${a.source || 'manual'}</div>
        ${hasCondition ? `
        <div class="activity-condition">
          ${conditionPills.map(p => `<span class="condition-pill">${p}</span>`).join('')}
          ${conditionRows.join('')}
        </div>` : ''}
      </div>
      <div class="activity-stats">
        ${stats.map(s => `<span class="stat-pill">${s}</span>`).join('')}
      </div>
      <div style="display:flex;gap:.3rem;margin-left:.5rem">
        <button class="meal-delete" onclick="openEditActivityModal('${a.id}')" title="Modifica">✏️</button>
        <button class="meal-delete" onclick="deleteActivity('${a.id}')" title="Elimina">🗑</button>
      </div>
    </div>
  `;
}

async function deleteActivity(id) {
  if (!confirm('Elimina questa attività?')) return;
  await api.deleteActivity(id);
  loadActivities();
}

// ─── Training ─────────────────────────────────────────────────────
async function loadTraining() {
  if (!USER_ID) return;
  const { plan, sessions } = await api.getPlan(USER_ID).catch(() => ({ plan: null, sessions: [] }));
  renderPlanHeader(plan);
  renderSessions(sessions);
}

function renderPlanHeader(plan) {
  const el = document.getElementById('trainingPlanHeader');
  if (!plan) {
    el.innerHTML = '<p style="color:var(--text2)">Nessun piano attivo. Creane uno con il pulsante qui sotto.</p>';
    return;
  }
  el.innerHTML = `
    <div class="plan-header">
      <div class="plan-name">${esc(plan.name)}</div>
      <div class="plan-goal">${esc(plan.goal)}</div>
      <div style="font-size:.75rem;color:var(--text2);margin-top:.5rem">
        Dal ${plan.start_date} al ${plan.end_date} · ${plan.weekly_sessions} sessioni/settimana
      </div>
    </div>
  `;
}

function renderSessions(sessions) {
  const container = document.getElementById('trainingSessions');
  if (!sessions.length) { container.innerHTML = '<p style="color:var(--text2)">Nessuna sessione pianificata</p>'; return; }

  const STATUS_LABELS = { planned: 'Pianificata', completed: 'Completata', skipped: 'Saltata', modified: 'Modificata' };

  container.innerHTML = sessions.slice(0, 30).map(s => {
    const d = new Date(s.scheduled_date + 'T00:00:00');
    const dayName = d.toLocaleDateString('it-IT', { weekday: 'short' });
    const dayNum = d.getDate();
    const icon = ACTIVITY_ICONS[s.activity_type] || '⚡';

    return `
      <div class="session-card">
        <div class="session-date">
          <div class="session-day">${dayName}</div>
          <div class="session-dd">${dayNum}</div>
        </div>
        <div class="session-info">
          <div class="session-title">${icon} ${esc(s.title)}</div>
          <div class="session-desc">${esc(s.description).substring(0, 120)}${s.description.length > 120 ? '…' : ''}</div>
          <div class="session-meta">
            <span class="session-status status-${s.status}">${STATUS_LABELS[s.status] || s.status}</span>
            <span class="session-intensity">⚡ ${s.intensity}</span>
            <span class="stat-pill">⏱ ${s.duration_target_min}min</span>
            ${s.distance_target_km ? `<span class="stat-pill">📍 ${s.distance_target_km}km</span>` : ''}
          </div>
        </div>
        <div style="display:flex;flex-direction:column;gap:.35rem">
          <button class="btn btn-sm btn-outline" onclick="markSession('${s.id}','completed')">✅</button>
          <button class="btn btn-sm btn-outline" onclick="markSession('${s.id}','skipped')">⏭</button>
        </div>
      </div>
    `;
  }).join('');
}

async function markSession(id, status) {
  await api.updateSession(id, { status });
  loadTraining();
}

async function loadSuggestedWorkout() {
  const data = await api.suggestWorkout(USER_ID).catch(() => null);
  if (!data) return;
  renderSuggestedWorkout(data);
}

function renderSuggestedWorkout(data) {
  const el = document.getElementById('suggestedWorkout');
  if (!data || !data.session_title) { el.innerHTML = '<p style="color:var(--text2)">Nessun suggerimento disponibile</p>'; return; }

  const renderExercises = (list) => (list || []).map(e => `
    <div class="workout-exercise">
      <span class="ex-name">${esc(e.exercise)}</span>
      <span class="ex-params">
        ${e.sets ? `${e.sets}×${e.reps}` : ''}
        ${e.duration_min ? `${e.duration_min}min` : ''}
        ${e.rest_sec ? ` · riposo ${e.rest_sec}s` : ''}
      </span>
      ${e.notes ? `<span class="ex-note">${esc(e.notes)}</span>` : ''}
    </div>
  `).join('');

  el.innerHTML = `
    <div><strong>${esc(data.session_title)}</strong>
    <span style="color:var(--text2);font-size:.8rem;margin-left:.5rem">~${data.total_duration_min}min · ~${data.estimated_calories}kcal</span></div>
    <p style="font-size:.8rem;color:var(--text2);margin:.5rem 0">${esc(data.why || '')}</p>
    ${data.warm_up?.length ? `<div class="workout-phase"><div class="workout-phase-title">🔥 Riscaldamento</div>${renderExercises(data.warm_up)}</div>` : ''}
    ${data.main_workout?.length ? `<div class="workout-phase"><div class="workout-phase-title">💪 Allenamento</div>${renderExercises(data.main_workout)}</div>` : ''}
    ${data.cool_down?.length ? `<div class="workout-phase"><div class="workout-phase-title">🧊 Defaticamento</div>${renderExercises(data.cool_down)}</div>` : ''}
  `;
}

// ─── Goals ───────────────────────────────────────────────────────
async function loadGoals() {
  if (!USER_ID) return;
  const data = await api.getGoals(USER_ID).catch(() => null);
  if (!data) return;
  renderGoalsCards(data, 'goalsProgressCards');
  renderGoalsCards(data, 'goalsOverviewCards', true);
  const title = document.getElementById('goalsOverviewTitle');
  if (title) title.style.display = hasAnyGoal(data) ? '' : 'none';
  populateGoalForm(data.profile || {});
}

function hasAnyGoal(data) {
  return data.weight_progress || data.cycling.goal_km || data.running.goal_km || data.steps.goal_day;
}

function renderGoalsCards(data, containerId, compact = false) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const cards = [];

  if (data.weight_progress) {
    const w = data.weight_progress;
    const direction = w.kg_remaining > 0 ? `perdere ${Math.abs(w.kg_remaining)} kg` : w.kg_remaining < 0 ? `aumentare ${Math.abs(w.kg_remaining)} kg` : '🎉 Obiettivo raggiunto!';
    cards.push(goalCardHtml('⚖️', 'Peso', `${w.current} kg`, `Obiettivo: ${w.target} kg · ${w.days_remaining > 0 ? w.days_remaining + ' giorni · ' + direction : direction}`, w.percent, 'fill-weight'));
  }

  if (data.cycling.goal_km) {
    const c = data.cycling;
    cards.push(goalCardHtml('🚴', 'Ciclismo ' + new Date().getFullYear(), `${c.done_km} km`, `Obiettivo: ${c.goal_km} km · mancano ${Math.max(0, c.goal_km - c.done_km)} km`, c.percent, 'fill-cycling'));
  }

  if (data.running.goal_km) {
    const r = data.running;
    cards.push(goalCardHtml('🏃', 'Corsa ' + new Date().getFullYear(), `${r.done_km} km`, `Obiettivo: ${r.goal_km} km · mancano ${Math.max(0, r.goal_km - r.done_km)} km`, r.percent, 'fill-running'));
  }

  if (data.steps.goal_day && data.steps.avg_30d) {
    const s = data.steps;
    cards.push(goalCardHtml('👟', 'Passi medi (30gg)', `${(s.avg_30d || 0).toLocaleString('it-IT')}`, `Obiettivo: ${(s.goal_day).toLocaleString('it-IT')} passi/giorno`, s.percent, 'fill-steps'));
  }

  if (!cards.length && !compact) {
    el.innerHTML = '<p style="color:var(--text2)">Nessun obiettivo impostato. Usa il form qui sotto per aggiungerne.</p>';
    return;
  }

  el.innerHTML = cards.join('');
}

function goalCardHtml(icon, title, value, sub, percent, fillClass) {
  const pct = Math.min(100, percent || 0);
  return `
    <div class="goal-card">
      <div class="goal-card-icon">${icon}</div>
      <div class="goal-card-title">${title}</div>
      <div class="goal-card-value">${value}</div>
      <div class="goal-card-sub">${sub}</div>
      <div class="goal-card-bar"><div class="goal-card-fill ${fillClass}" style="width:${pct}%"></div></div>
      <div class="goal-card-pct">${pct.toFixed(0)}%</div>
    </div>`;
}

function populateGoalForm(profile) {
  setVal('gGoalWeight', profile.goal_weight_kg || '');
  setVal('gGoalWeightDate', profile.goal_weight_date || '');
  setVal('gGoalCycling', profile.goal_cycling_km_year || '');
  setVal('gGoalRunning', profile.goal_run_km_year || '');
  setVal('gGoalSteps', profile.goal_steps_day || '');
  setVal('gGoalCustom', profile.goals_custom || '');
}

async function saveGoals() {
  const data = {
    goal_weight_kg: parseFloatOrNull('gGoalWeight'),
    goal_weight_date: getVal('gGoalWeightDate') || null,
    goal_cycling_km_year: parseFloatOrNull('gGoalCycling'),
    goal_run_km_year: parseFloatOrNull('gGoalRunning'),
    goal_steps_day: parseIntOrNull('gGoalSteps'),
    goals_custom: getVal('gGoalCustom') || null,
  };
  await api.updateUser(USER_ID, data);
  alert('✅ Obiettivi salvati!');
  loadGoals();
  loadOverview();
}

// ─── Health ───────────────────────────────────────────────────────
async function loadHealth() {
  if (!USER_ID) return;
  // precompila la data con oggi se non già impostata dall'utente
  const healthDateEl = document.getElementById('healthDate');
  if (healthDateEl && !healthDateEl.value) {
    healthDateEl.value = new Date().toLocaleDateString('sv-SE');
  }
  const [healthData, weightData] = await Promise.all([
    api.getHealth(USER_ID, 30),
    api.weightHistory(USER_ID, 60),
  ]);
  renderWeightChart(weightData, 'chartWeightHealth');
  renderSleepStepsChart(healthData.reverse());
}

async function saveHealthData() {
  const healthDate = getVal('healthDate') || new Date().toLocaleDateString('sv-SE');
  const data = {
    user_id: USER_ID,
    health_date: healthDate,
    weight_kg: parseFloatOrNull('inputWeight'),
    sleep_hours: parseFloatOrNull('inputSleep'),
    steps: parseIntOrNull('inputSteps'),
    body_battery: parseIntOrNull('inputBodyBattery'),
    hrv_ms: parseFloatOrNull('inputHrv'),
    stress_score: parseIntOrNull('inputStress'),
    total_calories_iphone: parseIntOrNull('inputIphoneCalories'),
  };
  try {
    await api.saveHealth(data);
    alert('Dati salute salvati ✅');
    loadHealth();
    loadOverview();
  } catch (e) {
    alert('Errore nel salvataggio: ' + e.message);
  }
}

// ─── Settings ─────────────────────────────────────────────────────
async function loadSettings() {
  if (!USER_ID) return;
  const profile = await api.getUser(USER_ID).catch(() => ({}));
  setVal('settingName', profile.name);
  setVal('settingAge', profile.age);
  setVal('settingHeight', profile.height_cm);
  setVal('settingGoal', profile.goal);
  setVal('settingCalories', profile.daily_calorie_goal);
  setVal('settingProtein', profile.protein_goal_g);
  setVal('settingCarbs', profile.carbs_goal_g);
  setVal('settingFat', profile.fat_goal_g);
  // Cycling profile
  setVal('settingFtp', profile.ftp_watts || '');
  setVal('settingCadMin', profile.target_cadence_min || '');
  setVal('settingCadMax', profile.target_cadence_max || '');
  const medEl = document.getElementById('settingMedical');
  if (medEl) medEl.value = profile.medical_notes || '';
}

async function saveSettings() {
  const medEl = document.getElementById('settingMedical');
  const data = {
    name: getVal('settingName'),
    age: parseIntOrNull2('settingAge'),
    height_cm: parseFloatOrNull('settingHeight'),
    goal: getVal('settingGoal'),
    daily_calorie_goal: parseInt(getVal('settingCalories')) || 2400,
    protein_goal_g: parseInt(getVal('settingProtein')) || 150,
    carbs_goal_g: parseInt(getVal('settingCarbs')) || 280,
    fat_goal_g: parseInt(getVal('settingFat')) || 75,
    ftp_watts: parseIntOrNull('settingFtp'),
    target_cadence_min: parseIntOrNull('settingCadMin'),
    target_cadence_max: parseIntOrNull('settingCadMax'),
    medical_notes: medEl ? (medEl.value || null) : null,
  };
  await api.updateUser(USER_ID, data);
  alert('Impostazioni salvate ✅');
  loadUserSidebar();
}

async function loadUserSidebar() {
  const profile = await api.getUser(USER_ID).catch(() => ({}));
  document.getElementById('sidebarUser').textContent = profile.name || 'Utente';
}

// ─── Strava ───────────────────────────────────────────────────────
function connectStrava() {
  window.open(`/api/strava/connect/${USER_ID}`, '_blank');
}

async function syncStrava() {
  const result = await api.syncStrava(USER_ID).catch(e => ({ error: e.message }));
  alert(result.error ? 'Errore: ' + result.error : `Sincronizzate ${result.imported} nuove attività`);
  loadActivities();
}

// ─── Peso rapido ──────────────────────────────────────────────────
function openCalorieBruciateModal() {
  openModal('modalCalorieBruciate');
  setVal('calbDate', overviewDate || new Date().toLocaleDateString('sv-SE'));
  const current = document.getElementById('kpiCalOut').textContent.replace(' kcal', '').trim();
  // pre-popola solo se è un valore iPhone (non stima BMR)
  const source = document.getElementById('kpiCalOutSource')?.textContent || '';
  setVal('calbInput', source.includes('iPhone') ? current : '');
  setTimeout(() => document.getElementById('calbInput')?.focus(), 100);
}

async function saveCalorieBruciate() {
  const val = parseInt(getVal('calbInput'));
  if (isNaN(val) || val <= 0) { alert('Inserisci un valore valido'); return; }
  const d = getVal('calbDate') || new Date().toLocaleDateString('sv-SE');
  try {
    await api.saveHealth({ user_id: USER_ID, health_date: d, total_calories_iphone: val });
    closeModal();
    loadOverview();
  } catch (e) {
    alert('Errore nel salvataggio: ' + e.message);
  }
}

async function saveIphoneCalories() {
  const val = parseInt(getVal('inputIphoneCalories'));
  if (isNaN(val) || val <= 0) { alert('Inserisci un valore valido'); return; }
  const d = getVal('healthDate') || new Date().toLocaleDateString('sv-SE');
  try {
    await api.saveHealth({ user_id: USER_ID, health_date: d, total_calories_iphone: val });
    alert('Calorie totali salvate ✅');
    loadOverview();
  } catch (e) {
    alert('Errore nel salvataggio: ' + e.message);
  }
}

function openWeightModal() {
  openModal('modalWeight');
  const el = document.getElementById('quickWeightInput');
  const current = document.getElementById('kpiWeight').textContent.replace(' kg', '').trim();
  el.value = current !== '—' ? current : '';
  setVal('quickWeightDate', new Date().toLocaleDateString('sv-SE'));
  setTimeout(() => el.focus(), 100);
}

async function saveQuickWeight() {
  const val = parseFloat(getVal('quickWeightInput').replace(',', '.'));
  if (isNaN(val) || val <= 0) { alert('Inserisci un peso valido'); return; }
  const d = getVal('quickWeightDate') || new Date().toLocaleDateString('sv-SE');
  try {
    await api.saveHealth({ user_id: USER_ID, health_date: d, weight_kg: val });
    closeModal();
    loadOverview();
    loadHealth();
  } catch (e) {
    alert('Errore nel salvataggio: ' + e.message);
  }
}

// ─── Edit pasto ───────────────────────────────────────────────────
function openEditMealModal(mealId) {
  const m = mealsCache[mealId];
  if (!m) return;
  editingMealId = mealId;

  setVal('mealTime', m.meal_time || 'snack');
  setVal('mealName', m.name);
  setVal('mealCalories', m.calories);
  setVal('mealProtein', m.protein_g);
  setVal('mealCarbs', m.carbs_g);
  setVal('mealFat', m.fat_g);
  setVal('mealFiber', m.fiber_g);
  setVal('mealQuantity', m.quantity_g || '');
  setVal('mealNotes', m.notes || '');

  const header = document.querySelector('#modalMeal .modal-header h3');
  if (header) header.textContent = 'Modifica pasto';

  openModal('modalMeal');
}

function openAddMealModal() {
  editingMealId = null;
  ['mealName','mealCalories','mealProtein','mealCarbs','mealFat','mealFiber','mealQuantity','mealNotes']
    .forEach(id => setVal(id, ''));
  const header = document.querySelector('#modalMeal .modal-header h3');
  if (header) header.textContent = 'Aggiungi pasto';
  openModal('modalMeal');
}

// ─── Edit attività ────────────────────────────────────────────────
function openEditActivityModal(activityId) {
  const a = activitiesCache[activityId];
  if (!a) return;
  editingActivityId = activityId;

  setVal('activityType', a.activity_type || 'other');
  setVal('activityName', a.name);
  setVal('activityDuration', a.duration_min);
  setVal('activityDistance', a.distance_km || '');
  setVal('activityElevation', a.elevation_m || '');
  setVal('activityNotes', a.notes || '');

  const header = document.querySelector('#modalActivity .modal-header h3');
  if (header) header.textContent = 'Modifica attività';

  openModal('modalActivity');
}

function openAddActivityModal() {
  editingActivityId = null;
  ['activityName','activityDuration','activityDistance','activityElevation','activityNotes']
    .forEach(id => setVal(id, ''));
  const header = document.querySelector('#modalActivity .modal-header h3');
  if (header) header.textContent = 'Registra attività';
  openModal('modalActivity');
}

// ─── Modals ───────────────────────────────────────────────────────
function openModal(id) {
  closeModal();
  currentModal = id;
  document.getElementById('modalOverlay').classList.add('open');
  document.getElementById(id).classList.add('open');
}

function closeModal() {
  if (currentModal) {
    document.getElementById(currentModal)?.classList.remove('open');
    currentModal = null;
  }
  document.getElementById('modalOverlay').classList.remove('open');
}

function openAddModal() {
  const activeTab = document.querySelector('.nav-item.active')?.dataset.tab;
  if (activeTab === 'nutrition') openAddMealModal();
  else if (activeTab === 'activities') openAddActivityModal();
  else if (activeTab === 'overview') openCalorieBruciateModal();
  else openAddMealModal();
}

function openNewPlanModal() { openModal('modalNewPlan'); }
function openAdjustPlanModal() { openModal('modalAdjustPlan'); }

async function saveMeal() {
  const data = {
    user_id: USER_ID,
    meal_date: nutritionDate,
    meal_time: getVal('mealTime'),
    name: getVal('mealName'),
    calories: parseFloat(getVal('mealCalories')) || 0,
    protein_g: parseFloat(getVal('mealProtein')) || 0,
    carbs_g: parseFloat(getVal('mealCarbs')) || 0,
    fat_g: parseFloat(getVal('mealFat')) || 0,
    fiber_g: parseFloat(getVal('mealFiber')) || 0,
    quantity_g: parseFloatOrNull('mealQuantity'),
    notes: getVal('mealNotes'),
    source: editingMealId ? (mealsCache[editingMealId]?.source || 'manual') : 'manual',
  };
  if (!data.name) { alert('Inserisci il nome del pasto'); return; }
  if (editingMealId) {
    await api.updateMeal(editingMealId, data);
  } else {
    await api.addMeal(data);
  }
  editingMealId = null;
  closeModal();
  loadNutrition();
  loadOverview();
}

async function saveActivity() {
  const existing = editingActivityId ? activitiesCache[editingActivityId] : null;
  const data = {
    user_id: USER_ID,
    activity_date: existing?.activity_date || new Date().toISOString().split('T')[0],
    activity_type: getVal('activityType'),
    name: getVal('activityName'),
    duration_min: parseFloat(getVal('activityDuration')) || 0,
    distance_km: parseFloatOrNull('activityDistance'),
    elevation_m: parseFloatOrNull('activityElevation'),
    notes: getVal('activityNotes'),
    strava_id: existing?.strava_id || null,
    source: existing?.source || 'manual',
  };
  if (!data.name) { alert('Inserisci il nome dell\'attività'); return; }
  try {
    if (editingActivityId) {
      await api.updateActivity(editingActivityId, data);
    } else {
      await api.addActivity(data);
    }
    editingActivityId = null;
    closeModal();
    loadActivities();
    loadOverview();
  } catch (e) {
    alert('Errore nel salvataggio: ' + e.message);
  }
}

async function generatePlan() {
  const req = getVal('planRequest');
  if (!req.trim()) { alert('Descrivi il tuo obiettivo'); return; }
  closeModal();
  document.getElementById('trainingPlanHeader').innerHTML = '<p style="color:var(--text2)">⏳ Generazione piano in corso con Claude AI...</p>';
  try {
    await api.generatePlan(USER_ID, req);
    loadTraining();
  } catch(e) {
    alert('Errore generazione piano: ' + e.message);
  }
}

async function submitPlanAdjustment() {
  const data = {
    reason: getVal('adjustReason'),
    detail: getVal('adjustDetail'),
    skip_days: parseInt(getVal('adjustSkipDays')) || 0,
    reduce_intensity: document.getElementById('adjustReduceIntensity').checked,
  };
  closeModal();
  try {
    const result = await api.adjustPlan(USER_ID, data);
    alert(`Piano aggiornato!\n\n${result.assessment}\n\n💬 ${result.motivational_message}`);
    loadTraining();
  } catch(e) {
    alert('Errore: ' + e.message);
  }
}

// ─── Exercises ────────────────────────────────────────────────────
const ROUTINE_TYPE_LABELS = { strength: 'Forza', mobility: 'Mobilità', warmup: 'Riscaldamento', cooldown: 'Defaticamento' };

async function loadExercises() {
  if (!USER_ID) return;
  const routines = await api.getRoutines(USER_ID).catch(() => []);
  routines.forEach(r => {
    routinesCache[r.id] = r;
    (r.exercises || []).forEach(e => { exercisesCache[e.id] = e; });
  });
  renderRoutines(routines);
}

function renderRoutines(routines) {
  const container = document.getElementById('routinesList');
  if (!routines || !routines.length) {
    container.innerHTML = '<p style="color:var(--text2)">Nessuna routine. Crea la tua prima routine!</p>';
    return;
  }
  container.innerHTML = routines.map(r => {
    const exercises = r.exercises || [];
    const typeLabel = ROUTINE_TYPE_LABELS[r.type] || r.type;
    const exRows = exercises.length
      ? exercises.map(e => `
        <div style="display:flex;align-items:center;gap:.5rem;padding:.4rem 0;border-bottom:1px solid var(--border)">
          <span style="flex:1;font-size:.9rem">${esc(e.name)}</span>
          <span style="color:var(--text2);font-size:.82rem;min-width:80px">
            ${e.sets ? e.sets + '×' : ''}${e.reps ? esc(e.reps) : ''}${e.rest_seconds ? ' · ' + e.rest_seconds + 's' : ''}
          </span>
          <button class="meal-delete" onclick="openEditExerciseModal('${e.id}')" title="Modifica">✏️</button>
          <button class="meal-delete" onclick="deleteExercise('${e.id}')" title="Elimina">🗑</button>
        </div>`).join('')
      : '<p style="color:var(--text2);font-size:.85rem;padding:.5rem 0">Nessun esercizio ancora.</p>';

    return `
      <div class="card" style="margin-bottom:1rem">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.5rem">
          <div>
            <div style="font-weight:600;font-size:1.05rem">${esc(r.name)}</div>
            <div style="color:var(--accent);font-size:.8rem">${typeLabel}</div>
            ${r.description ? `<div style="color:var(--text2);font-size:.82rem;margin-top:.2rem">${esc(r.description)}</div>` : ''}
          </div>
          <div style="display:flex;gap:.3rem">
            <button class="btn btn-sm btn-outline" onclick="openEditRoutineModal('${r.id}')">✏️ Modifica</button>
            <button class="btn btn-sm btn-outline" onclick="deleteRoutine('${r.id}')">🗑 Elimina</button>
          </div>
        </div>
        <div style="margin-bottom:.75rem">${exRows}</div>
        <button class="btn btn-sm btn-outline" onclick="openAddExerciseModal('${r.id}')">+ Aggiungi esercizio</button>
      </div>
    `;
  }).join('');
}

function openAddRoutineModal() {
  editingRoutineId = null;
  setVal('routineName', '');
  setVal('routineType', 'strength');
  setVal('routineDescription', '');
  const title = document.getElementById('routineModalTitle');
  if (title) title.textContent = 'Nuova routine';
  openModal('modalRoutine');
}

function openEditRoutineModal(id) {
  const r = routinesCache[id];
  if (!r) return;
  editingRoutineId = id;
  setVal('routineName', r.name);
  setVal('routineType', r.type || 'strength');
  setVal('routineDescription', r.description || '');
  const title = document.getElementById('routineModalTitle');
  if (title) title.textContent = 'Modifica routine';
  openModal('modalRoutine');
}

async function saveRoutine() {
  const name = getVal('routineName').trim();
  if (!name) { alert('Inserisci il nome della routine'); return; }
  const data = {
    user_id: USER_ID,
    name,
    type: getVal('routineType'),
    description: getVal('routineDescription') || null,
  };
  try {
    if (editingRoutineId) {
      await api.updateRoutine(editingRoutineId, data);
    } else {
      await api.addRoutine(data);
    }
    editingRoutineId = null;
    closeModal();
    loadExercises();
  } catch(e) {
    alert('Errore nel salvataggio: ' + e.message);
  }
}

async function deleteRoutine(id) {
  if (!confirm('Elimina questa routine e tutti i suoi esercizi?')) return;
  await api.deleteRoutine(id);
  delete routinesCache[id];
  loadExercises();
}

function openAddExerciseModal(routineId) {
  editingExerciseId = null;
  setVal('exerciseName', '');
  setVal('exerciseSets', '');
  setVal('exerciseReps', '');
  setVal('exerciseRest', '');
  setVal('exerciseNotes', '');
  setVal('exerciseRoutineId', routineId);
  const title = document.getElementById('exerciseModalTitle');
  if (title) title.textContent = 'Nuovo esercizio';
  openModal('modalExercise');
}

function openEditExerciseModal(id) {
  const e = exercisesCache[id];
  if (!e) return;
  editingExerciseId = id;
  setVal('exerciseName', e.name);
  setVal('exerciseSets', e.sets || '');
  setVal('exerciseReps', e.reps || '');
  setVal('exerciseRest', e.rest_seconds || '');
  setVal('exerciseNotes', e.notes || '');
  setVal('exerciseRoutineId', e.routine_id);
  const title = document.getElementById('exerciseModalTitle');
  if (title) title.textContent = 'Modifica esercizio';
  openModal('modalExercise');
}

async function saveExercise() {
  const name = getVal('exerciseName').trim();
  if (!name) { alert('Inserisci il nome dell\'esercizio'); return; }
  const routineId = getVal('exerciseRoutineId');
  const data = {
    routine_id: routineId,
    user_id: USER_ID,
    name,
    sets: parseIntOrNull('exerciseSets'),
    reps: getVal('exerciseReps') || null,
    rest_seconds: parseIntOrNull('exerciseRest'),
    notes: getVal('exerciseNotes') || null,
  };
  try {
    if (editingExerciseId) {
      await api.updateExercise(editingExerciseId, data);
    } else {
      await api.addExercise(data);
    }
    editingExerciseId = null;
    closeModal();
    loadExercises();
  } catch(e) {
    alert('Errore nel salvataggio: ' + e.message);
  }
}

async function deleteExercise(id) {
  if (!confirm('Elimina questo esercizio?')) return;
  await api.deleteExercise(id);
  delete exercisesCache[id];
  loadExercises();
}

// ─── Helpers ──────────────────────────────────────────────────────
function setText(id, val) { const el = document.getElementById(id); if (el) el.textContent = val ?? '—'; }
function setWidth(id, val) { const el = document.getElementById(id); if (el) el.style.width = val; }
function getVal(id) { return document.getElementById(id)?.value || ''; }
function setVal(id, val) { const el = document.getElementById(id); if (el && val != null) el.value = val; }
function parseFloatOrNull(id) { const v = parseFloat(getVal(id)); return isNaN(v) ? null : v; }
function parseIntOrNull(id) { const v = parseInt(getVal(id)); return isNaN(v) ? null : v; }
function parseIntOrNull2(id) { return parseIntOrNull(id); }
function esc(str) { return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
