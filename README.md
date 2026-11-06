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
| Ingestion | Python + `requests` (daily run from an Indian IP — see below) | Scheduled runner with an Indian egress IP → Databricks Volume |
| Processing | PySpark + Delta Lake | Databricks Jobs |
| Transform | dbt + DuckDB | dbt + Databricks SQL |
| API | FastAPI | Databricks Apps |
| Infra | — | Terraform + Databricks Asset Bundles |

## Roadmap

- [x] **Phase 0** — Setup (Python, Java 17, local Spark + Delta) — *mostly done*
- [ ] **Phase 1** — Daily collector (API client ✅, JSONL writer + manifest ✅, Databricks upload ✅, automated schedule 🚧, tests 🚧)
- [ ] **Phase 2** — PySpark: bronze → silver → features
- [ ] **Phase 3** — dbt: incremental models, snapshots, tests
- [ ] **Phase 4** — FastAPI: prices, trends, arbitrage, anomalies
- [ ] **Phase 5** — LLM `/ask` endpoint
- [ ] **Phase 6** — Deploy on Databricks, CI/CD, Terraform

## Data source

- **Current Daily Price of Various Commodities from Various Markets (Mandi)**, data.gov.in (from AGMARKNET)
- **Variety-wise Daily Market Prices Data of Commodity**, data.gov.in (historical, since 2010)

Notes on how the API behaves and its quirks are in [`docs/source_notes.md`](docs/source_notes.md).

> ⚠️ **data.gov.in blocks requests from outside India.** GitHub-hosted runners and Databricks Free Edition
> can't reach it, so the collector currently runs manually from a machine in India. An automated schedule
> (GitHub Actions through an India-based SSH tunnel) is in progress.

## Running locally

Requires Python 3.12 and Java 17 (for PySpark).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# .env (never committed)
#   DATA_GOV_API_KEY=...        free key from data.gov.in
#   DATABRICKS_HOST=...         only needed for the upload step
#   DATABRICKS_TOKEN=...
```

Daily collection (run from the project root, from an Indian IP):

```bash
python -m ingestion.collect_daily                  # -> data/raw/agmarknet/ingest_date=<IST date>/
python -m ingestion.collect_daily --max-pages 1    # quick test run (not uploaded)
python -m ingestion.upload_to_volume               # -> Databricks Volume
```

---

Built by [Vijay](https://github.com/Vijayrajdev) as a learning and portfolio project.
