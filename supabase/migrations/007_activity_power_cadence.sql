ALTER TABLE activities
  ADD COLUMN IF NOT EXISTS avg_power_w       INT,
  ADD COLUMN IF NOT EXISTS normalized_power_w INT,
  ADD COLUMN IF NOT EXISTS avg_cadence_rpm   NUMERIC(4,1),
  ADD COLUMN IF NOT EXISTS tss               NUMERIC(6,1);
