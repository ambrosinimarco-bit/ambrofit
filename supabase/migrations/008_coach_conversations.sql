-- Storico conversazioni con il coach AI
CREATE TABLE IF NOT EXISTS coach_conversations (
  id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    TEXT        NOT NULL,
  role       TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
  message    TEXT        NOT NULL,
  session_id TEXT        NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coach_conv_user    ON coach_conversations (user_id);
CREATE INDEX IF NOT EXISTS idx_coach_conv_session  ON coach_conversations (session_id);
CREATE INDEX IF NOT EXISTS idx_coach_conv_created  ON coach_conversations (created_at DESC);
