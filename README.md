# Mandi-Pulse

![Status](https://img.shields.io/badge/status-in%20progress-yellow)
![Python](https://img.shields.io/badge/python-3.12-blue)
![PySpark](https://img.shields.io/badge/PySpark-4.x-E25A1C)
![Delta Lake](https://img.shields.io/badge/Delta%20Lake-4.x-00ADD4)
![dbt](https://img.shields.io/badge/dbt-duckdb%20%7C%20databricks-FF694B)
![Databricks](https://img.shields.io/badge/deploy-Databricks-FF3621)

> 🚧 **Work in progress.** This project is being built step by step. Things will change.

**Price intelligence for Indian agricultural wholesale markets (mandis).**

Farmers and traders can't easily tell where a crop sells best today, how its price is trending,
or whether today's price is unusual. Mandi-Pulse collects daily mandi prices from India's
open-data API, cleans them up, and serves trends, anomalies and best-market comparisons through a REST API.

---

## What it will do

- **Collect daily prices** from the [data.gov.in](https://data.gov.in) AGMARKNET API and build its own history
  (the source only shows today's prices).
- **Clean messy data**: different spellings of the same market or commodity, mixed units, invalid price ranges.
- **Analyse prices**: trends, rolling averages, unusual-price (anomaly) detection, and the best market within X km.
- **Serve it through a public API** (FastAPI) with docs, auth and rate limiting.
- **Answer plain-English questions** (`/ask`), with an LLM picking which API endpoint to call.

## Architecture (planned)

```
data.gov.in API ──► Daily collector ──► Raw JSONL ──► PySpark ──► Delta (silver) ──► dbt marts ──► FastAPI
   (Python, retries,      (by ingest date)    (clean, dedupe,               (trends,          (+ /ask LLM)
    pagination)                                standardise)                  anomalies)
```

| Layer | Local | Cloud |
|---|---|---|
| Ingestion | Python + `requests` | GitHub Actions cron → Databricks Workflows |
| Processing | PySpark + Delta Lake | Databricks Jobs |
| Transform | dbt + DuckDB | dbt + Databricks SQL |
| API | FastAPI | Databricks Apps |
| Infra | — | Terraform + Databricks Asset Bundles |

## Roadmap

- [x] **Phase 0** — Setup (Python, Java 17, local Spark + Delta) — *mostly done*
- [ ] **Phase 1** — Daily collector (API client ✅, daily JSONL writer 🚧)
- [ ] **Phase 2** — PySpark: bronze → silver → features
- [ ] **Phase 3** — dbt: incremental models, snapshots, tests
- [ ] **Phase 4** — FastAPI: prices, trends, arbitrage, anomalies
- [ ] **Phase 5** — LLM `/ask` endpoint
- [ ] **Phase 6** — Deploy on Databricks, CI/CD, Terraform

## Data source

- **Current Daily Price of Various Commodities from Various Markets (Mandi)**, data.gov.in (from AGMARKNET)
- **Variety-wise Daily Market Prices Data of Commodity**, data.gov.in (historical, since 2010)

Notes on how the API behaves and its quirks are in [`docs/source_notes.md`](docs/source_notes.md).

## Running locally

> Setup instructions will be added as the pieces come together.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install delta-spark dbt-duckdb requests python-dotenv pytest ruff
echo "DATA_GOV_API_KEY=your_key_here" > .env   # free key from data.gov.in
```

---

Built by [Vijay](https://github.com/Vijayrajdev) as a learning and portfolio project.
