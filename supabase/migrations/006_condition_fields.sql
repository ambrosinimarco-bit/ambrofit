-- Percezione condizione allenamento
ALTER TABLE activities
  ADD COLUMN IF NOT EXISTS condition_pre    TEXT,
  ADD COLUMN IF NOT EXISTS condition_during TEXT,
  ADD COLUMN IF NOT EXISTS condition_post   TEXT,
  ADD COLUMN IF NOT EXISTS sleep_hours      NUMERIC(3,1),
  ADD COLUMN IF NOT EXISTS stress_level     INT;

-- Pre-condizione giornaliera (registrata prima dell'allenamento)
ALTER TABLE daily_health
  ADD COLUMN IF NOT EXISTS pre_condition TEXT;
