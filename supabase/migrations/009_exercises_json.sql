-- Add exercises_json column to training_sessions for strength/mobility session details
ALTER TABLE training_sessions
  ADD COLUMN IF NOT EXISTS exercises_json TEXT;
