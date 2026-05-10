CREATE TABLE IF NOT EXISTS food_items (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID REFERENCES user_profiles(id) ON DELETE CASCADE,
  name              TEXT NOT NULL,
  brand             TEXT,
  calories_per_100g NUMERIC,
  protein_per_100g  NUMERIC,
  carbs_per_100g    NUMERIC,
  fat_per_100g      NUMERIC,
  fiber_per_100g    NUMERIC,
  source            TEXT DEFAULT 'manual',
  created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS food_items_user_name_idx ON food_items (user_id, lower(name));
