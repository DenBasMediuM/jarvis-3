-- Платная диагностика: применить один раз к рабочей базе
--   npx wrangler d1 execute jarvis-feedback --remote --file=migrations/0004_diag.sql
CREATE TABLE IF NOT EXISTS diag_cases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'consult',
  source TEXT NOT NULL DEFAULT 'other',
  device TEXT,
  category TEXT,
  master TEXT,
  consult_note TEXT,
  price INTEGER,
  prepay INTEGER NOT NULL DEFAULT 0,
  decline_reason TEXT,
  comment TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  status_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diag_ticket ON diag_cases(ticket);
CREATE TABLE IF NOT EXISTS diag_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  login TEXT,
  action TEXT NOT NULL,
  case_id INTEGER,
  ticket TEXT,
  text TEXT
);
CREATE INDEX IF NOT EXISTS idx_diag_log_at ON diag_log(at);
CREATE TABLE IF NOT EXISTS diag_snapshot (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
