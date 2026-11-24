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

-- ---------- Аутсорс мастера (раздел витрины «Аутсорс мастера») ----------
-- Кандидаты в аутсорсеры: воронка менеджера.
CREATE TABLE IF NOT EXISTS outsource_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL DEFAULT 'master_home',     -- master_home | master_sc | service
  name TEXT NOT NULL,
  contact TEXT,                                  -- телефон / телеграм
  source_url TEXT,                               -- ссылка на объявление
  area TEXT,                                     -- город / район
  devices TEXT,                                  -- какую технику берёт
  terms TEXT,                                    -- условия оплаты
  stage TEXT NOT NULL DEFAULT 'found',           -- found | contacted | trial | regular | paused | lost
  stage_at TEXT NOT NULL,
  lost_reason TEXT,
  crm_engineer TEXT,                             -- мастер в Gincore (как в карточке заказа)
  cash_contractor TEXT,                          -- получатель выплат в кассе Gincore
  notes TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_out_cand_stage ON outsource_candidates(stage);

-- Пробные (и последующие отслеживаемые) передачи устройств.
CREATE TABLE IF NOT EXISTS outsource_trials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id INTEGER NOT NULL,
  ticket TEXT NOT NULL,                          -- № квитанции Gincore
  source TEXT NOT NULL DEFAULT 'client',         -- donor | client
  device TEXT,
  issue TEXT,
  handed_at TEXT NOT NULL,                       -- YYYY-MM-DD
  due_at TEXT,                                   -- обещанный срок, YYYY-MM-DD
  price REAL,                                    -- согласованная цена работы
  comment TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  result_quality INTEGER,                        -- 1..5
  result_on_time INTEGER,                        -- 1 / 0
  result_decision TEXT,                          -- take | again | reject
  result_comment TEXT,
  result_by TEXT,
  result_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_out_trial_cand ON outsource_trials(candidate_id);

-- Журнал действий менеджера (отчётность по процессу).
CREATE TABLE IF NOT EXISTS outsource_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  login TEXT,
  action TEXT NOT NULL,                          -- candidate_created | candidate_updated | stage_changed | trial_created | trial_result | note
  candidate_id INTEGER,
  trial_id INTEGER,
  text TEXT
);
CREATE INDEX IF NOT EXISTS idx_out_log_at ON outsource_log(at);
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
  subject TEXT,
  price REAL,
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
