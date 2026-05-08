-- ═══════════════════════════════════════════════════════════════════
-- FITNESS TRACKER — Obiettivi personali
-- Esegui nel SQL Editor di Supabase dopo 001_initial.sql
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE user_profiles
  ADD COLUMN IF NOT EXISTS goal_weight_kg        NUMERIC(5,2),
  ADD COLUMN IF NOT EXISTS goal_weight_date      DATE,
  ADD COLUMN IF NOT EXISTS goal_cycling_km_year  NUMERIC(8,1),
  ADD COLUMN IF NOT EXISTS goal_steps_day        INT,
  ADD COLUMN IF NOT EXISTS goal_run_km_year      NUMERIC(8,1),
  ADD COLUMN IF NOT EXISTS goals_custom          TEXT;  -- testo libero per altri obiettivi
