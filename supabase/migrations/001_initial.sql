-- ═══════════════════════════════════════════════════════════════════
-- FITNESS TRACKER — Schema iniziale
-- ═══════════════════════════════════════════════════════════════════

-- Abilita UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── User Profiles ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_profiles (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id             TEXT UNIQUE NOT NULL,
    name                    TEXT,
    age                     INT,
    height_cm               NUMERIC(5,1),
    weight_kg               NUMERIC(5,2),
    goal                    TEXT,          -- lose_weight | maintain | gain_muscle
    daily_calorie_goal      INT DEFAULT 2200,
    protein_goal_g          INT DEFAULT 160,
    carbs_goal_g            INT DEFAULT 220,
    fat_goal_g              INT DEFAULT 80,
    strava_athlete_id       TEXT,
    strava_access_token     TEXT,
    strava_refresh_token    TEXT,
    strava_token_expires_at TIMESTAMPTZ,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

-- ── Meals ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS meals (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    meal_date   DATE NOT NULL DEFAULT CURRENT_DATE,
    meal_time   TEXT,                  -- breakfast | lunch | dinner | snack
    name        TEXT NOT NULL,
    calories    NUMERIC(7,1) NOT NULL DEFAULT 0,
    protein_g   NUMERIC(6,1) DEFAULT 0,
    carbs_g     NUMERIC(6,1) DEFAULT 0,
    fat_g       NUMERIC(6,1) DEFAULT 0,
    fiber_g     NUMERIC(6,1) DEFAULT 0,
    quantity_g  NUMERIC(7,1),
    notes       TEXT,
    source      TEXT DEFAULT 'manual', -- manual | telegram_text | telegram_photo | telegram_voice | telegram_label
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_meals_user_date ON meals(user_id, meal_date DESC);

-- ── Activities ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS activities (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    activity_date   DATE NOT NULL DEFAULT CURRENT_DATE,
    activity_type   TEXT DEFAULT 'other', -- run | ride | swim | walk | hike | strength | yoga | other
    name            TEXT NOT NULL,
    duration_min    NUMERIC(7,1) NOT NULL DEFAULT 0,
    distance_km     NUMERIC(8,2),
    elevation_m     NUMERIC(7,1),
    calories        NUMERIC(7,1),
    avg_heart_rate  INT,
    max_heart_rate  INT,
    strava_id       TEXT UNIQUE,
    notes           TEXT,
    source          TEXT DEFAULT 'manual', -- manual | strava | telegram_text | telegram_voice
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_activities_user_date ON activities(user_id, activity_date DESC);

-- ── Daily Health ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_health (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    health_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    weight_kg       NUMERIC(5,2),
    sleep_hours     NUMERIC(4,1),
    steps           INT,
    body_battery    INT,
    hrv_ms          NUMERIC(6,1),
    stress_score    INT,
    resting_hr      INT,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, health_date)
);

CREATE INDEX idx_health_user_date ON daily_health(user_id, health_date DESC);

-- ── Training Plans ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_plans (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id          UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    goal             TEXT NOT NULL,
    description      TEXT,
    start_date       DATE NOT NULL,
    end_date         DATE NOT NULL,
    weekly_sessions  INT DEFAULT 4,
    is_active        BOOLEAN DEFAULT TRUE,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ── Training Sessions ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_sessions (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plan_id              UUID NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
    user_id              UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    scheduled_date       DATE NOT NULL,
    activity_type        TEXT NOT NULL DEFAULT 'other',
    title                TEXT NOT NULL,
    description          TEXT NOT NULL DEFAULT '',
    duration_target_min  INT NOT NULL DEFAULT 45,
    distance_target_km   NUMERIC(6,2),
    intensity            TEXT DEFAULT 'moderate', -- easy | moderate | hard | race
    status               TEXT DEFAULT 'planned',  -- planned | completed | skipped | modified
    notes                TEXT,
    created_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sessions_user_date ON training_sessions(user_id, scheduled_date);
CREATE INDEX idx_sessions_plan ON training_sessions(plan_id, scheduled_date);

-- ── Row Level Security (opzionale, abilita se necessario) ─────────
-- ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE meals ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE activities ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE daily_health ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE training_plans ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE training_sessions ENABLE ROW LEVEL SECURITY;
