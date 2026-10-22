# jarvis-debt-inbox (Cloudflare Worker)

Inbox решений дебиторки: витрина `POST /decision`, Jarvis `GET /inbox` + `POST /inbox/ack`.

## Деплой кода (один раз после создания Worker в Dashboard)

1. Откройте Worker **jarvis-debt-inbox** → **Edit code** (или Deployments → Quick edit).
2. Замените содержимое на файл [`src/index.js`](src/index.js).
3. **Save and deploy**.

Либо из терминала (нужен `CLOUDFLARE_API_TOKEN`):

```bash
cd workers/debt-inbox
npx wrangler deploy
```

Секреты `WRITE_KEY` / `READ_KEY` и binding `INBOX` уже задаются в Dashboard — wrangler их не затирает при деплое кода через UI.
