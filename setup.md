# Life & Brand — Stock Control Platform: Setup Reference

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Structure](#2-repository-structure)
3. [Prerequisites](#3-prerequisites)
4. [Local Development Setup](#4-local-development-setup)
5. [Environment Variables & API Keys](#5-environment-variables--api-keys)
6. [Database Setup](#6-database-setup)
7. [Third-Party Service Configuration](#7-third-party-service-configuration)
8. [Cron Jobs & Automation](#8-cron-jobs--automation)
9. [Docker Deployment](#9-docker-deployment)
10. [API Reference](#10-api-reference)
11. [Data Model Reference](#11-data-model-reference)
12. [Spot-Check Algorithm Reference](#12-spot-check-algorithm-reference)
13. [Future Integrations](#13-future-integrations)

---

## 1. Project Overview

A stock control and freshness management platform built for Life & Brand hospitality operations. Core features:

| Feature | Description |
|---|---|
| Smart spot-check scheduling | Daily rotating count prompts per department, guaranteed 7-day full cycle |
| Perishable batch tracking | Stock tracked by received date and best-before date (Central Kitchen items) |
| Freshness alerts | Multi-channel notifications to managers when items approach expiry |
| Invoice OCR | Claude vision API reads supplier invoice photos and extracts line items |
| Procurement workflow | Purchase orders → GRN receiving → invoice matching |

**Tech stack:**
- Backend: Python 3.12, FastAPI, SQLAlchemy, Alembic, PostgreSQL
- Frontend: React 18, TypeScript, Vite, TanStack Query
- Infrastructure: Docker, Docker Compose

---

## 2. Repository Structure

```
LifeandBrand/
├── backend/
│   ├── app/
│   │   ├── api/routes/         # FastAPI route handlers
│   │   │   ├── alerts.py       # Expiry alert management and contact CRUD
│   │   │   ├── batches.py      # Batch monitoring (expiring, active)
│   │   │   ├── deliveries.py   # GRN receiving — creates batches on accept
│   │   │   ├── invoice_ocr.py  # Claude vision OCR endpoint
│   │   │   ├── purchase_orders.py
│   │   │   ├── spot_checks.py  # Session generation and count submission
│   │   │   └── suppliers.py
│   │   ├── models/             # SQLAlchemy ORM models
│   │   │   ├── alert.py        # ExpiryAlert — notification audit log
│   │   │   ├── batch.py        # ItemBatch — perishable batch tracking
│   │   │   ├── contact.py      # LocationContact — alert recipients
│   │   │   ├── delivery.py     # Delivery + DeliveryLine (GRN)
│   │   │   ├── invoice.py      # Invoice + InvoiceLine
│   │   │   ├── item.py         # Item + UnitOfMeasure + Department enum
│   │   │   ├── location.py     # Location (site/restaurant)
│   │   │   ├── purchase_order.py
│   │   │   ├── recipe.py       # MenuItem + RecipeLine (drives theoretical usage)
│   │   │   ├── sale.py         # Sale + SaleLine (from Micros POS)
│   │   │   ├── spot_check.py   # SpotCheckSession + SpotCheckItem + SpotCheckBatchCount
│   │   │   ├── stock.py        # StockMovement (immutable audit ledger)
│   │   │   └── supplier.py     # Supplier + SupplierItem (price catalogue)
│   │   ├── services/
│   │   │   ├── alert_engine.py         # Alert check logic and deduplication
│   │   │   ├── invoice_ocr.py          # Claude API call and JSON parsing
│   │   │   ├── notifications.py        # Email / Teams / WhatsApp adapters
│   │   │   └── spot_check_selector.py  # Item scoring and selection algorithm
│   │   ├── config.py           # Pydantic settings (reads from .env)
│   │   └── main.py             # FastAPI app and router registration
│   ├── alembic/                # Database migration scripts
│   ├── alembic.ini
│   ├── .env.example            # Template — copy to .env and fill in
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Alerts.tsx      # Freshness alert management and history
│   │   │   ├── Dashboard.tsx   # Summary metrics
│   │   │   ├── Deliveries.tsx  # GRN list
│   │   │   ├── InvoiceOCR.tsx  # Invoice photo upload and review
│   │   │   ├── PurchaseOrders.tsx
│   │   │   ├── SpotChecks.tsx  # Daily spot-check sessions and count entry
│   │   │   └── Suppliers.tsx
│   │   ├── hooks/useApi.ts     # Axios instance pointed at /api/v1
│   │   ├── types/index.ts      # TypeScript interfaces for all entities
│   │   ├── App.tsx             # Router and sidebar nav
│   │   └── index.css           # Global styles and design tokens
│   ├── Dockerfile
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml
└── setup.md                    # This file
```

---

## 3. Prerequisites

| Tool | Minimum version | Notes |
|---|---|---|
| Docker | 24.x | Required for containerised setup |
| Docker Compose | 2.x | Bundled with Docker Desktop |
| Python | 3.12 | Local backend development only |
| Node.js | 20.x | Local frontend development only |
| PostgreSQL | 16 | Managed via Docker; or supply your own |

---

## 4. Local Development Setup

### Option A — Docker (recommended, no Python/Node install needed)

```bash
# 1. Clone the repo
git clone https://github.com/ArnovZ080/LifeandBrand.git
cd LifeandBrand

# 2. Create your environment file
cp backend/.env.example backend/.env
# Edit backend/.env — fill in at minimum the API keys you need

# 3. Start all services
docker compose up

# 4. Run database migrations (first time only, in a second terminal)
docker compose exec backend alembic revision --autogenerate -m "initial"
docker compose exec backend alembic upgrade head
```

Services once running:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API docs (Swagger): http://localhost:8000/docs
- PostgreSQL: localhost:5432

### Option B — Local (backend and frontend separately)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env

# Start a local PostgreSQL instance (or use the Docker one):
docker run -d --name lb-postgres \
  -e POSTGRES_USER=stockuser \
  -e POSTGRES_PASSWORD=stockpass \
  -e POSTGRES_DB=stockdb \
  -p 5432:5432 postgres:16-alpine

alembic revision --autogenerate -m "initial"
alembic upgrade head
uvicorn app.main:app --reload
```

```bash
# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

---

## 5. Environment Variables & API Keys

Copy `backend/.env.example` to `backend/.env`. Never commit `.env` to git — it is in `.gitignore`.

### Database

| Variable | Example | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://stockuser:stockpass@localhost:5432/stockdb` | Change host to `db` when using Docker Compose |
| `SECRET_KEY` | any long random string | Used for future auth signing |

### Anthropic API (Invoice OCR)

Used by the Invoice Capture page to read supplier invoice photos.

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → API Keys |

**Cost note:** Uses `claude-sonnet-4-6`. Each invoice image extraction costs approximately $0.003–$0.015 USD depending on image size and line-item count. No setup beyond the API key is required.

### Email / SMTP (Freshness Alerts)

Works with Office 365, Gmail, or any SMTP relay.

| Variable | Example | Notes |
|---|---|---|
| `SMTP_HOST` | `smtp.office365.com` | Gmail: `smtp.gmail.com` |
| `SMTP_PORT` | `587` | Use 587 for STARTTLS |
| `SMTP_USER` | `stockalerts@yourdomain.com` | The sending address |
| `SMTP_PASSWORD` | — | O365: use an App Password, not your login password |
| `SMTP_FROM_ADDRESS` | `stockalerts@yourdomain.com` | Defaults to `SMTP_USER` if blank |

**Office 365 App Password:** Microsoft 365 admin centre → Users → [user] → Mail → Manage email apps → ensure SMTP AUTH is enabled. Then generate an app password under Security settings.

**Gmail App Password:** Google Account → Security → 2-Step Verification → App passwords. Requires 2FA to be enabled.

### WhatsApp via Twilio (Freshness Alerts)

| Variable | Where to get it |
|---|---|
| `TWILIO_ACCOUNT_SID` | https://console.twilio.com → Account Info |
| `TWILIO_AUTH_TOKEN` | https://console.twilio.com → Account Info |
| `TWILIO_WHATSAPP_FROM` | Your approved Twilio WhatsApp sender number (E.164 format: `+14155238886` for sandbox) |

**Setup steps:**
1. Create a Twilio account at https://www.twilio.com
2. Navigate to Messaging → Try it out → Send a WhatsApp message (sandbox for testing)
3. For production: submit a WhatsApp Business Profile approval request through Twilio — takes 1–5 business days
4. Each recipient must opt in (send a message to the Twilio number first, or via Twilio's opt-in flow)

**SA number format:** Always use E.164 format — e.g. `+27821234567` (replace leading `0` with `+27`)

### Microsoft Teams (Freshness Alerts)

Teams webhooks are configured **per contact** in the UI, not in `.env`. Each manager needs their own webhook URL from their Teams channel.

**Setup per manager:**
1. Open the Teams channel where that manager wants to receive alerts
2. Click `···` (More options) → Connectors
3. Search for "Incoming Webhook" → Configure
4. Give it a name (e.g. "Life & Brand Alerts") → Create
5. Copy the webhook URL and paste it into the contact's record in the Alerts page

---

## 6. Database Setup

### Running migrations

```bash
# Generate a new migration after model changes
alembic revision --autogenerate -m "describe what changed"

# Apply all pending migrations
alembic upgrade head

# Roll back one migration
alembic downgrade -1
```

### Key tables

| Table | Purpose |
|---|---|
| `locations` | Restaurant / site records |
| `items` | Master ingredient and product catalogue |
| `units_of_measure` | kg, litre, each, etc. |
| `suppliers` | Supplier master with Sage ID reference |
| `supplier_items` | Price catalogue per supplier per item |
| `menu_items` | POS items from Micros |
| `recipe_lines` | Ingredient quantities per menu item (drives theoretical usage) |
| `purchase_orders` / `purchase_order_lines` | Procurement |
| `deliveries` / `delivery_lines` | GRN receiving |
| `item_batches` | Perishable batch tracking — one row per delivery line for perishable items |
| `invoices` / `invoice_lines` | Supplier invoices |
| `stock_movements` | Immutable ledger of all stock in/out |
| `sales` / `sale_lines` | POS sales data (from Micros) |
| `spot_check_sessions` | Daily spot-check sessions per department |
| `spot_check_items` | Items selected per session with scores |
| `spot_check_batch_counts` | Per-batch counts for perishable items |
| `location_contacts` | Alert recipients with channel preferences |
| `expiry_alerts` | Audit log of every alert sent, failed, or suppressed |

### First-time seed data required

Before the spot-check system can select items, the following must be set up manually (UI coming):

1. Create at least one `Location`
2. Create `UnitOfMeasure` records (kg, litre, each, portion, etc.)
3. Create `Item` records — set `department`, `is_perishable`, `default_shelf_life_days`, and `unit_cost`
4. Create `MenuItem` records and `RecipeLine` records linking menu items to ingredients

---

## 7. Third-Party Service Configuration

### Micros POS (future integration)

Micros provides sales data which drives **theoretical stock usage** via the recipe engine.

| Variable | Notes |
|---|---|
| `MICROS_API_URL` | Base URL of the Micros REST API endpoint |
| `MICROS_API_KEY` | API key from Micros system administration |

**Connector location:** `backend/app/connectors/` — stub exists, implementation pending.

**What the integration needs to provide:**
- Daily sales by menu item (`SaleLine` records) — `quantity_sold` per `menu_item.micros_item_id`
- The `micros_item_id` on each `MenuItem` must match the Micros system's item identifier

### Sage (future integration)

Sage is used for supplier master data and invoice posting.

| Variable | Notes |
|---|---|
| `SAGE_API_URL` | Sage API base URL |
| `SAGE_CLIENT_ID` | OAuth 2.0 client ID from Sage developer portal |
| `SAGE_CLIENT_SECRET` | OAuth 2.0 client secret |

**What the integration needs to provide:**
- Supplier master sync → populates `suppliers` table, keeps `sage_supplier_id` in sync
- Invoice posting → when an invoice is approved in this system, POST it to Sage GL
- The `sage_supplier_id` field on `Supplier` and `sage_invoice_id` on `Invoice` hold the cross-reference keys

---

## 8. Cron Jobs & Automation

Add these to the server's crontab (`crontab -e`) once deployed:

```cron
# Freshness alert checks — runs at shift start morning and afternoon
# Checks all active batches, sends to configured contacts, deduplicates automatically
30 6  * * *  curl -s -X POST "http://localhost:8000/api/v1/alerts/trigger" >> /var/log/lb-alerts.log 2>&1
0  14 * * *  curl -s -X POST "http://localhost:8000/api/v1/alerts/trigger" >> /var/log/lb-alerts.log 2>&1

# Spot-check session generation — generates all dept sessions at shift start
# Adjust location_id and department as needed per site
30 6  * * *  curl -s -X POST "http://localhost:8000/api/v1/spot-checks/generate" \
               -H "Content-Type: application/json" \
               -d '{"location_id":1,"department":"kitchen","session_slot":1}' >> /var/log/lb-spotcheck.log 2>&1
```

**Alert deduplication:** The alert engine records every sent alert in `expiry_alerts`. Running the cron twice will not send duplicate messages — the engine checks for same-batch, same-level, same-contact alerts already sent today.

---

## 9. Docker Deployment

### Development (local)

```bash
docker compose up           # start all services
docker compose up -d        # start in background
docker compose down         # stop
docker compose logs backend # view backend logs
```

### Production notes

For production, replace the Docker Compose setup with:

1. **Database:** Managed PostgreSQL (AWS RDS, Azure Database for PostgreSQL, or Supabase). Update `DATABASE_URL` in the environment.

2. **Backend:** Deploy the FastAPI app behind a reverse proxy (nginx or Caddy). The Dockerfile builds a production-ready image:
   ```bash
   docker build -t lifeandbrand-backend ./backend
   ```

3. **Frontend:** Build static files and serve via nginx or a CDN:
   ```bash
   cd frontend && npm run build
   # Outputs to frontend/dist/
   ```

4. **Environment variables:** In production, inject via your cloud provider's secrets manager (AWS Secrets Manager, Azure Key Vault, etc.) — never commit `.env` to the repository.

5. **SSL:** Always run behind HTTPS in production. Let's Encrypt via Caddy is the simplest option.

---

## 10. API Reference

Interactive Swagger docs are available at `http://localhost:8000/docs` when the backend is running.

### Key endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/spot-checks/today?location_id=1` | Today's spot-check sessions |
| `POST` | `/api/v1/spot-checks/generate` | Generate a new session (runs selection algorithm) |
| `POST` | `/api/v1/spot-checks/{session_id}/items/{item_id}/count` | Submit a non-perishable count |
| `POST` | `/api/v1/spot-checks/{session_id}/items/{item_id}/batch-count` | Submit a per-batch count for perishables |
| `GET` | `/api/v1/spot-checks/coverage/{location_id}/{department}` | 7-day cycle coverage report |
| `GET` | `/api/v1/batches/expiring?location_id=1&within_days=2` | Batches expiring within N days |
| `GET` | `/api/v1/batches/active?location_id=1` | All active perishable batches |
| `POST` | `/api/v1/deliveries/{id}/accept` | Accept delivery — posts stock movements and creates batches |
| `POST` | `/api/v1/invoice-ocr/extract` | Upload invoice image → Claude extracts structured data |
| `POST` | `/api/v1/alerts/trigger?location_id=1` | Run the expiry alert check |
| `GET` | `/api/v1/alerts/contacts?location_id=1` | List alert recipients |
| `POST` | `/api/v1/alerts/contacts` | Add an alert recipient |
| `GET` | `/api/v1/alerts/history?location_id=1&days=7` | Alert send history |

---

## 11. Data Model Reference

### Department enum

`bar` · `kitchen` · `floor` · `general`

### Item fields relevant to spot-check scoring

| Field | Type | Purpose |
|---|---|---|
| `department` | enum | Which team is responsible for this item |
| `unit_cost` | decimal | Used for value scoring — high-cost items get more frequent checks |
| `is_perishable` | bool | If true, stock is tracked by batch; spot checks show per-batch counts |
| `default_shelf_life_days` | int | Fallback best-before calculation if not provided on delivery |

### ItemBatch status lifecycle

```
ACTIVE → EXPIRING_SOON → EXPIRED
                        → DEPLETED (quantity_remaining reaches 0)
```

`EXPIRING_SOON` triggers when `days_until_expiry <= 2` (configurable via `EXPIRY_WARNING_DAYS` in `batch.py`).

### ExpiryAlert levels

| Level value | Meaning | Alert fires when |
|---|---|---|
| `48` | Warning | hours until expiry ≤ 48 |
| `24` | Action Required | hours until expiry ≤ 24 |
| `0` | Urgent | expires today |

Each level fires **once per batch per contact per day**.

---

## 12. Spot-Check Algorithm Reference

**File:** `backend/app/services/spot_check_selector.py`

### Scoring formula

```
total_score = (0.20 × velocity) + (0.25 × value) + (0.35 × variance_history) + (0.20 × recency)
```

| Signal | Weight | Source | Description |
|---|---|---|---|
| `velocity` | 20% | `sale_lines` × `recipe_lines`, last 14 days | Average daily theoretical usage — fast movers have more exposure |
| `value` | 25% | `items.unit_cost` | Normalised unit cost — high-value items (Dom Perignon etc.) get more frequent checks regardless of sales velocity |
| `variance_history` | 35% | Past `spot_check_items.variance_pct`, last 30 days | Average absolute variance % — items with a track record of going missing are weighted most heavily |
| `recency` | 20% | Last `counted_at` in `spot_check_items` | Days since last check, capped at 7 (cycle length) |

### 7-day cycle guarantee

Any item not checked within 7 days (`CYCLE_DAYS`) is flagged `is_overdue = True` and added to the session **before** scored items. Session size grows automatically to fit all overdue items (hard cap: 15 items per session via `MAX_SESSION_SIZE`).

Items never checked before get a default variance history score of 5% — moderate, not zero — so they enter rotation rather than being permanently deprioritised.

### Key constants (editable in `spot_check_selector.py`)

| Constant | Default | Effect |
|---|---|---|
| `BASE_ITEMS_PER_SESSION` | `5` | Target items per session when no overdue items exist |
| `CYCLE_DAYS` | `7` | Days before an item is considered overdue |
| `MAX_SESSION_SIZE` | `15` | Hard cap on items per session |
| `VELOCITY_LOOKBACK_DAYS` | `14` | Days of sales history used for velocity score |
| `VARIANCE_LOOKBACK_DAYS` | `30` | Days of spot-check history used for variance score |

---

## 13. Future Integrations

Placeholder connectors exist in `backend/app/connectors/`. These are the planned integrations in priority order:

### Micros POS
- **Purpose:** Import daily sales data automatically (instead of manual `Sale` entry)
- **What to build:** Scheduled job that calls Micros API daily, creates `Sale` and `SaleLine` records, keyed on `menu_items.micros_item_id`
- **Credentials needed:** `MICROS_API_URL`, `MICROS_API_KEY`

### Sage
- **Purpose:** Sync supplier master data; post approved invoices to the GL
- **What to build:** OAuth 2.0 flow for token management; supplier sync on schedule; invoice POST on approval
- **Credentials needed:** `SAGE_API_URL`, `SAGE_CLIENT_ID`, `SAGE_CLIENT_SECRET`

### Kissflow / Asana (workflow approvals)
- **Purpose:** Route purchase order and invoice approvals through existing workflow tools
- **What to build:** Webhook receiver to update PO/invoice status when approved in Kissflow

### Dineplan (reservations)
- **Purpose:** Use reservation covers data to improve theoretical usage forecasting (expected covers → expected consumption)
- **What to build:** Reservation feed to adjust demand forecasting in the spot-check selector

### Safety Culture / iAuditor
- **Purpose:** Trigger spot-check sessions from Safety Culture inspection checklists
- **What to build:** Webhook integration to generate `SpotCheckSession` records when a relevant audit is started

---

*Last updated: May 2026*
*Platform version: 0.4.0*
*Branch: `claude/plan-data-platform-SrPj8`*
