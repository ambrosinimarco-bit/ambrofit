-- activity_date already exists from 001_initial.sql
-- calories already exists as NUMERIC(7,1) — calories_burned added as requested
ALTER TABLE activities ADD COLUMN IF NOT EXISTS calories_burned INTEGER;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS intensity TEXT;
