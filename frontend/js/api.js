const API_BASE = '';  // stesso origine

async function apiFetch(path, opts = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || res.statusText);
  }
  return res.json();
}

// ── Dashboard ──────────────────────────────────────────────────────
const api = {
  today:          (uid, date) => apiFetch(`/api/dashboard/today/${uid}${date ? '?target_date='+date : ''}`),
  getFitness:     (uid) => apiFetch(`/api/dashboard/fitness/${uid}`),
  week:           (uid, offset=0) => apiFetch(`/api/dashboard/week/${uid}?week_offset=${offset}`),
  calorieTrend:   (uid, days=30) => apiFetch(`/api/dashboard/calorie-trend/${uid}?days=${days}`),
  weightTrend:    (uid, days=60) => apiFetch(`/api/dashboard/weight-trend/${uid}?days=${days}`),
  suggestWorkout: (uid, mins=45) => apiFetch(`/api/dashboard/suggest-workout/${uid}?available_time=${mins}`),
  getGoals:       (uid) => apiFetch(`/api/dashboard/goals/${uid}`),
  getUser:        (uid) => apiFetch(`/api/dashboard/user/${uid}`),
  updateUser:     (uid, data) => apiFetch(`/api/dashboard/user/${uid}`, { method: 'PUT', body: data }),

  // Meals
  getMeals:       (uid, date) => apiFetch(`/api/meals/?user_id=${uid}${date ? '&meal_date='+date : ''}`),
  addMeal:        (data) => apiFetch('/api/meals/', { method: 'POST', body: data }),
  updateMeal:     (id, data) => apiFetch(`/api/meals/${id}`, { method: 'PUT', body: data }),
  deleteMeal:     (id) => apiFetch(`/api/meals/${id}`, { method: 'DELETE' }),

  // Activities
  getActivities:  (uid, days=7) => apiFetch(`/api/activities/?user_id=${uid}&days=${days}`),
  addActivity:    (data) => apiFetch('/api/activities/', { method: 'POST', body: data }),
  updateActivity: (id, data) => apiFetch(`/api/activities/${id}`, { method: 'PUT', body: data }),
  deleteActivity: (id) => apiFetch(`/api/activities/${id}`, { method: 'DELETE' }),

  // Health
  getHealth:      (uid, days=30) => apiFetch(`/api/health/?user_id=${uid}&days=${days}`),
  saveHealth:     (data) => apiFetch('/api/health/', { method: 'POST', body: data }),
  updateHealth:   (id, data) => apiFetch(`/api/health/${id}`, { method: 'PUT', body: data }),
  weightHistory:  (uid, days=60) => apiFetch(`/api/health/weight-trend?user_id=${uid}&days=${days}`),

  // Training
  getPlan:        (uid) => apiFetch(`/api/training/plan/${uid}`),
  adjustPlan:     (uid, data) => apiFetch(`/api/training/plan/${uid}/adjust`, { method: 'POST', body: data }),
  updateSession:  (sid, data) => apiFetch(`/api/training/session/${sid}`, { method: 'PATCH', body: data }),
  getSessions:    (uid, days=14) => apiFetch(`/api/training/sessions/${uid}?days=${days}`),
  generateIcs:    (uid, planText, weekStart) => apiFetch('/api/training/generate-ics', {
    method: 'POST',
    body: { user_id: uid, plan_text: planText, week_start: weekStart },
  }),
  generateZwo:    (uid, sessionType, durationMin) => apiFetch('/api/training/generate-zwo', {
    method: 'POST',
    body: { user_id: uid, session_type: sessionType, duration_min: durationMin },
  }),

  // Chat / Coach
  coachChat: (uid, message, history, sessionId) => apiFetch('/api/chat/coach', {
    method: 'POST',
    body: { user_id: uid, message, session_history: history, session_id: sessionId || null },
  }),
  getCoachHistory: (uid, days = 7) => apiFetch(`/api/chat/history/${uid}?days=${days}`),

  // Strava
  syncStrava:       (uid) => apiFetch(`/api/strava/sync/${uid}`, { method: 'POST' }),
  resyncAllStrava:  (uid, days=90) => apiFetch(`/api/strava/resync-all/${uid}?days=${days}`, { method: 'POST' }),

  // Exercises
  getRoutines:    (uid) => apiFetch(`/api/exercises/?user_id=${uid}`),
  addRoutine:     (data) => apiFetch('/api/exercises/routines', { method: 'POST', body: data }),
  updateRoutine:  (id, data) => apiFetch(`/api/exercises/routines/${id}`, { method: 'PUT', body: data }),
  deleteRoutine:  (id) => apiFetch(`/api/exercises/routines/${id}`, { method: 'DELETE' }),
  addExercise:    (data) => apiFetch('/api/exercises/', { method: 'POST', body: data }),
  updateExercise: (id, data) => apiFetch(`/api/exercises/${id}`, { method: 'PUT', body: data }),
  deleteExercise: (id) => apiFetch(`/api/exercises/${id}`, { method: 'DELETE' }),
};
