-- D1 схема модуля «Улучшения»
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  login TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',          -- open | submitted | merged | abandoned
  rounds INTEGER NOT NULL DEFAULT 0,            -- сколько раз ИИ задавал уточнения
  user_messages INTEGER NOT NULL DEFAULT 0,
  context_json TEXT,
  messages_json TEXT NOT NULL DEFAULT '[]',     -- [{role, text, at}]
  last_ai_json TEXT,                            -- последний ответ ИИ (draft + assessment)
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_login ON conversations(login, created_at);

CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  login TEXT NOT NULL,
  conversation_id INTEGER,
  type TEXT NOT NULL DEFAULT 'improvement',
  title TEXT NOT NULL,
  area TEXT,
  problem TEXT,
  proposal TEXT,
  benefit TEXT,
  acceptance_json TEXT,
  original_text TEXT,
  assessment_json TEXT,
  duplicate_hint INTEGER,
  status TEXT NOT NULL DEFAULT 'new',           -- new | approved | in_progress | done | rejected
  admin_comment TEXT,
  priority INTEGER,
  decided_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_req_login ON requests(login);
CREATE INDEX IF NOT EXISTS idx_req_status ON requests(status);

CREATE TABLE IF NOT EXISTS votes (
  request_id INTEGER NOT NULL,
  login TEXT NOT NULL,
  comment TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (request_id, login)
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT NOT NULL
);
