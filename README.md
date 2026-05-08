# 🏋️ Fitness Tracker — Setup completo

Sistema completo di fitness tracking con bot Telegram, integrazione Strava, backend FastAPI e dashboard web.

---

## Stack

| Componente | Tecnologia |
|---|---|
| Backend | Python 3.12 + FastAPI |
| Bot Telegram | python-telegram-bot 21 |
| AI | Claude claude-opus-4-7 (vision + testo) |
| Trascrizione audio | Groq Whisper large-v3 |
| Database | Supabase (PostgreSQL) |
| Attività sportive | Strava API v3 |
| Dashboard | HTML + Chart.js (vanilla JS) |

---

## Setup passo per passo

### 1. Clona e installa dipendenze

```bash
cd fitness-tracker
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configura le variabili d'ambiente

```bash
cp .env.example .env
```

Modifica `.env` con i tuoi valori reali (vedi sezione API Keys qui sotto).

### 3. Crea il database su Supabase

1. Vai su [supabase.com](https://supabase.com) → Nuovo progetto
2. Apri **SQL Editor**
3. Incolla ed esegui il contenuto di `supabase/migrations/001_initial.sql`
4. In **Project Settings → API** copia:
   - `Project URL` → `SUPABASE_URL`
   - `anon public` → `SUPABASE_KEY`
   - `service_role` → `SUPABASE_SERVICE_KEY`

### 4. Ottieni il tuo User ID

Dopo aver eseguito la migrazione SQL:
1. Avvia l'app: `uvicorn backend.main:app --reload`
2. Manda `/start` al bot Telegram
3. In Supabase → Table Editor → `user_profiles` → copia l'`id` della tua riga
4. Incollalo nella dashboard web quando richiesto (o in `.env` come `DEFAULT_USER_TELEGRAM_ID`)

---

## Ottenere le API Keys

### Telegram Bot Token
1. Apri Telegram → cerca `@BotFather`
2. Invia `/newbot` → segui le istruzioni
3. Copia il token → `TELEGRAM_BOT_TOKEN`
4. Per il tuo Telegram ID: scrivi a `@userinfobot`

### Anthropic (Claude)
1. Vai su [console.anthropic.com](https://console.anthropic.com)
2. API Keys → Create Key
3. Copia → `ANTHROPIC_API_KEY`

### Groq (Whisper)
1. Vai su [console.groq.com](https://console.groq.com)
2. API Keys → Create
3. Copia → `GROQ_API_KEY`

### Strava API
1. Vai su [strava.com/settings/api](https://www.strava.com/settings/api)
2. Crea un'app (Authorization Callback Domain: `localhost`)
3. Copia **Client ID** → `STRAVA_CLIENT_ID`
4. Copia **Client Secret** → `STRAVA_CLIENT_SECRET`
5. In `.env` imposta `STRAVA_REDIRECT_URI=http://localhost:8000/api/strava/callback`

---

## Avvio in sviluppo (locale)

```bash
# Assicurati che .env sia configurato
uvicorn backend.main:app --reload --port 8000
```

- **Dashboard web**: http://localhost:8000
- **API docs**: http://localhost:8000/docs
- **Bot Telegram**: funziona in modalità polling (non serve webhook in locale)

---

## Avvio in produzione (webhook)

Per la produzione serve un dominio pubblico con HTTPS (es. con [ngrok](https://ngrok.com) in test o un VPS).

```bash
# Con ngrok in test
ngrok http 8000
# Copia l'URL https → TELEGRAM_WEBHOOK_URL e APP_BASE_URL in .env
# Poi imposta ENVIRONMENT=production
```

Con Docker:
```bash
docker-compose up -d
```

---

## Collegare Strava

1. Con il server avviato, apri: `http://localhost:8000/api/strava/connect/<tuo-user-id>`
2. Autorizza l'accesso su Strava
3. Le attività vengono sincronizzate automaticamente (ultimi 30 giorni)
4. Le nuove attività arrivano via webhook in produzione, o usa `/syncstrava` nel bot

### Registrare il webhook Strava (solo produzione)

```bash
curl -X POST http://localhost:8000/api/strava/register-webhook
```

---

## Usare il Bot Telegram

### Input supportati

| Tipo | Esempi |
|---|---|
| Testo pasto | "ho mangiato una pizza margherita" |
| Testo attività | "ho pedalato 40km in 2 ore" |
| Testo peso | "peso 75.3 kg oggi" |
| Foto cibo | invia foto del piatto → stima automatica calorie |
| Foto etichetta | invia foto etichetta + caption "150g" → legge valori nutrizionali |
| Foto Garmin | invia screenshot Garmin Connect → estrae Body Battery, HRV, sonno, stress |
| Vocale | descrivi pasto o attività a voce |

### Comandi

```
/start          — benvenuto e istruzioni
/riepilogo      — riepilogo nutrizionale di oggi
/peso 75.5      — registra peso
/passi 8500     — registra passi
/sonno 7.5      — registra ore di sonno
/piano          — vedi piano di allenamento
/nuovopiano     — crea piano con Claude AI
/strava         — collega account Strava
/syncstrava     — sincronizza attività Strava
/aiuto          — tutti i comandi
```

---

## Dashboard Web

Apri http://localhost:8000 nel browser.

Al primo accesso ti verrà chiesto il **User ID Supabase** (puoi trovarlo nella tabella `user_profiles`).

### Funzionalità dashboard

- **Panoramica**: KPI giornalieri, bilancio calorico, trend 30 giorni, andamento peso
- **Nutrizione**: log pasti per pasto (colazione/pranzo/cena/spuntini), dettaglio macros, navigazione date
- **Attività**: lista attività con stats, import Strava, inserimento manuale
- **Piano**: sessioni del piano corrente, completamento sessioni, generazione AI, gestione pause/modifiche
- **Salute**: inserimento peso/sonno/passi/Garmin, grafici andamento
- **Impostazioni**: profilo, obiettivi giornalieri, collegamento Strava

---

## Struttura del progetto

```
fitness-tracker/
├── .env.example              # Template variabili d'ambiente
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── backend/
│   ├── main.py               # FastAPI app + avvio bot
│   ├── config.py             # Pydantic Settings
│   ├── database/
│   │   ├── client.py         # Client Supabase singleton
│   │   └── models.py         # Pydantic models
│   ├── api/routes/
│   │   ├── meals.py          # CRUD pasti
│   │   ├── activities.py     # CRUD attività
│   │   ├── health.py         # Dati salute giornalieri
│   │   ├── strava.py         # OAuth2 + webhook Strava
│   │   ├── dashboard.py      # Aggregazioni per dashboard
│   │   ├── training.py       # Piano allenamento
│   │   └── webhook.py        # Webhook Telegram
│   ├── bot/
│   │   ├── telegram_bot.py   # Setup handlers bot
│   │   └── handlers/
│   │       ├── command_handler.py  # /start /riepilogo /peso ecc.
│   │       ├── text_handler.py     # Messaggi testo → analisi pasto
│   │       ├── photo_handler.py    # Foto → cibo / etichetta / Garmin
│   │       └── voice_handler.py    # Vocale → trascrizione → analisi
│   └── services/
│       ├── claude_service.py       # Tutte le chiamate Claude API
│       ├── groq_service.py         # Trascrizione Whisper
│       ├── strava_service.py       # Strava API + OAuth
│       ├── nutrition_service.py    # Calcoli nutrizionali
│       └── training_plan_service.py # Logica piano allenamento
├── frontend/
│   ├── index.html            # Dashboard single-page
│   ├── css/style.css         # Dark theme responsive
│   └── js/
│       ├── api.js            # Client API REST
│       ├── charts.js         # Chart.js helpers
│       └── app.js            # Logica dashboard
└── supabase/
    └── migrations/
        └── 001_initial.sql   # Schema completo PostgreSQL
```

---

## Troubleshooting

**Il bot non risponde:**
- Verifica `TELEGRAM_BOT_TOKEN` in `.env`
- In locale usa polling (default) — non serve webhook
- Controlla i log: `uvicorn backend.main:app --reload`

**Errore Supabase:**
- Verifica `SUPABASE_URL` e `SUPABASE_SERVICE_KEY`
- Assicurati di aver eseguito la migrazione SQL

**Errore Strava OAuth:**
- Verifica `STRAVA_REDIRECT_URI` corrisponda esattamente a quello configurato su Strava
- In locale deve essere `http://localhost:8000/api/strava/callback`

**Claude non analizza le foto:**
- Verifica `ANTHROPIC_API_KEY`
- Le foto vengono convertite in base64 — verifica che la foto non sia troppo grande (>20MB)

**Errore Groq / audio:**
- Verifica `GROQ_API_KEY`
- Telegram invia l'audio in formato OGG/OPUS — già gestito nativamente
