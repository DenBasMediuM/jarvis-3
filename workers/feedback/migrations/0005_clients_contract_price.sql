-- Постоянные клиенты: предмет (код ДК 021) и цена договора
--   npx wrangler d1 execute jarvis-feedback --remote --file=migrations/0005_clients_contract_price.sql
ALTER TABLE clients_contracts ADD COLUMN subject TEXT;
ALTER TABLE clients_contracts ADD COLUMN price REAL;
