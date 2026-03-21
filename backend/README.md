# OpenConfigs — Setup Guide

## Estrutura
```
openconfigs/
├── backend/       → Python FastAPI
│   ├── main.py
│   ├── requirements.txt
│   ├── Procfile
│   └── .env.example
└── frontend/      → HTML estático
    └── index.html
```

---

## 1. Supabase — Configurações finais

### Adicionar coluna user_id na tabela configs
No Supabase → Table Editor → configs → Definition → Add column:
- Name: `user_id` | Type: `text`

### Pegar a Service Role Key (para o admin funcionar)
Settings → API → **service_role** (secret) → copie

### Desativar RLS (Row Level Security) por enquanto
Table Editor → configs → Add RLS policy → desative o toggle "Enable RLS"

---

## 2. Criar repo no GitHub para as configs

1. Crie um repo público chamado `openconfigs-storage`
2. Crie um arquivo `configs/.gitkeep` para inicializar a pasta
3. Gere um Personal Access Token:
   - github.com/settings/tokens → Generate new token (classic)
   - Marque: `repo` (acesso total)
   - Copie o token

---

## 3. Deploy do Backend — Railway (gratuito)

1. Acesse **railway.app** → login com GitHub
2. New Project → Deploy from GitHub repo → selecione o repo
3. Configure o **Root Directory** como `backend`
4. Vá em **Variables** e adicione:

```
SUPABASE_URL=https://edrhihdxvbzmahbasehl.supabase.co
SUPABASE_ANON_KEY=eyJhbGci...
SUPABASE_SERVICE_KEY=sua_service_role_key
GITHUB_TOKEN=seu_github_token
GITHUB_REPO=seuuser/openconfigs-storage
GITHUB_BRANCH=main
ADMIN_EMAIL=seu@email.com
```

5. Railway vai gerar uma URL tipo: `https://openconfigs.railway.app`

---

## 4. Configurar o Frontend

No `frontend/index.html`, linha 284, troque:
```js
const API = 'https://SEU-BACKEND.railway.app';
```
pela URL que o Railway gerou.

---

## 5. Deploy do Frontend — Vercel

1. Suba o projeto no GitHub (pasta `frontend/`)
2. Acesse **vercel.com** → New Project → importe o repo
3. Root Directory: `frontend`
4. Deploy!

---

## 6. Configurar email no Supabase

Authentication → Email Templates → customize os templates de confirmação.

Authentication → Settings → SMTP:
- Use seu email (Gmail com App Password, ou SendGrid grátis)

---

## Rotas da API

| Método | Rota | Auth | Descrição |
|--------|------|------|-----------|
| POST | /auth/register | ❌ | Cadastro |
| POST | /auth/login | ❌ | Login |
| GET | /configs | ❌ | Listar configs |
| POST | /configs | ✅ | Upload config |
| DELETE | /configs/:id | ✅ | Deletar (dono) |
| GET | /admin/stats | 🛡 Admin | Estatísticas |
| GET | /admin/users | 🛡 Admin | Usuários |
| DELETE | /admin/configs/:id | 🛡 Admin | Deletar qualquer |
