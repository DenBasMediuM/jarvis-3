-- Постоянные клиенты: применить один раз к рабочей базе
--   npx wrangler d1 execute jarvis-feedback --remote --file=migrations/0003_clients.sql
CREATE TABLE IF NOT EXISTS clients_clients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL DEFAULT 'person',
  name TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'other',
  stage TEXT NOT NULL DEFAULT 'found',
  stage_at TEXT NOT NULL,
  lost_reason TEXT,
  phones TEXT NOT NULL DEFAULT '[]',
  contacts TEXT NOT NULL DEFAULT '[]',
  legal TEXT NOT NULL DEFAULT '{}',
  conditions TEXT NOT NULL DEFAULT '{}',
  area TEXT,
  devices TEXT,
  notes TEXT,
  next_step TEXT,
  next_step_at TEXT,
  last_touch_at TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cl_stage ON clients_clients(stage);
CREATE TABLE IF NOT EXISTS clients_contracts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER NOT NULL,
  number TEXT,
  kind TEXT NOT NULL DEFAULT 'legal',
  status TEXT NOT NULL DEFAULT 'draft',
  signed_at TEXT,
  valid_from TEXT,
  valid_to TEXT,
  file_url TEXT,
  body TEXT,
  notes TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cl_contract_client ON clients_contracts(client_id);
CREATE TABLE IF NOT EXISTS clients_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  login TEXT,
  action TEXT NOT NULL,
  client_id INTEGER,
  contract_id INTEGER,
  channel TEXT,
  text TEXT
);
CREATE INDEX IF NOT EXISTS idx_cl_log_at ON clients_log(at);
CREATE TABLE IF NOT EXISTS clients_decisions (
  phone TEXT PRIMARY KEY,
  decision TEXT NOT NULL,
  until TEXT,
  reason TEXT,
  client_id INTEGER,
  login TEXT,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clients_templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  body TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clients_snapshot (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
