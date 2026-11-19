-- Аутсорс мастера: применить один раз к рабочей базе
--   npx wrangler d1 execute jarvis-feedback --remote --file=migrations/0002_outsource.sql
CREATE TABLE IF NOT EXISTS outsource_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL DEFAULT 'master_home',
  name TEXT NOT NULL,
  contact TEXT,
  source_url TEXT,
  area TEXT,
  devices TEXT,
  terms TEXT,
  stage TEXT NOT NULL DEFAULT 'found',
  stage_at TEXT NOT NULL,
  lost_reason TEXT,
  crm_engineer TEXT,
  cash_contractor TEXT,
  notes TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_out_cand_stage ON outsource_candidates(stage);
CREATE TABLE IF NOT EXISTS outsource_trials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id INTEGER NOT NULL,
  ticket TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'client',
  device TEXT,
  issue TEXT,
  handed_at TEXT NOT NULL,
  due_at TEXT,
  price REAL,
  comment TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  result_quality INTEGER,
  result_on_time INTEGER,
  result_decision TEXT,
  result_comment TEXT,
  result_by TEXT,
  result_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_out_trial_cand ON outsource_trials(candidate_id);
CREATE TABLE IF NOT EXISTS outsource_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  login TEXT,
  action TEXT NOT NULL,
  candidate_id INTEGER,
  trial_id INTEGER,
  text TEXT
);
CREATE INDEX IF NOT EXISTS idx_out_log_at ON outsource_log(at);
