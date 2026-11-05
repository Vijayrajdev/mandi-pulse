# Source notes — data.gov.in Mandi prices API

Observed behaviour of the source API. Update this file whenever we learn something new.
Each fact has the date it was observed, because government APIs change without notice.

---

## 1. Endpoint

| Item | Value |
|---|---|
| Dataset | Current Daily Price of Various Commodities from Various Markets (Mandi) — from AGMARKNET |
| URL | `https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070` |
| Auth | `api-key` query parameter (free key from data.gov.in → My Account). Stored in `.env` as `DATA_GOV_API_KEY`. |

### Parameters

| Param | Example | Meaning |
|---|---|---|
| `api-key` | — | Your key. Never log or commit it. |
| `format` | `json` | Response format (`json`, `xml`, `csv`). |
| `limit` | `1000` | Rows per page. |
| `offset` | `0`, `1000`, … | How many rows to skip (used for paging). |
| `filters[<field>]` | `filters[state]=Kerala` | Optional exact-match filter. |

### Example call (terminal)

```bash
set -a; source .env; set +a
curl -s "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070?api-key=$DATA_GOV_API_KEY&format=json&limit=5" | python3 -m json.tool
```

---

## 2. Response shape (observed 2026-11-05)

The response is one JSON object. Rows are in `records`; everything else is metadata.

```json
{
  "updated_date": "2026-11-05T08:01:15Z",
  "total": 12517,
  "count": 5,
  "limit": "5",
  "offset": "0",
  "message": "Resource lists",
  "status": "...",
  "records": [ { ...row... }, ... ]
}
```

Useful metadata fields:

| Field | Type | Meaning |
|---|---|---|
| `total` | **int** | Total rows available today (12,517 on 2026-11-05). |
| `count` | **int** | Rows in *this* page. |
| `limit` | **string** ⚠️ | Echo of requested limit, e.g. `"5"`. |
| `offset` | **string** ⚠️ | Echo of requested offset, e.g. `"0"`. |
| `updated_date` | string (ISO, UTC) | When the source last refreshed the data. |

⚠️ `total`/`count` are numbers but `limit`/`offset` are strings → convert with `int()` before comparing.

Other metadata present (not needed for now): `created`, `updated`, `created_date`, `title`, `desc`, `org`, `sector`,
`field` (list of field definitions), `version`, `index_name`, `catalog_uuid`, etc.

---

## 3. Record fields (observed 2026-11-05)

| Field | Type | Example |
|---|---|---|
| `state` | string | `"Keralam"` |
| `district` | string | `"Kozhikode(Calicut)"` |
| `market` | string | `"Mukkom Market"` |
| `commodity` | string | `"Pumpkin"` |
| `variety` | string | `"Pumpkin"` |
| `grade` | string | `"FAQ"` |
| `arrival_date` | string, **`dd/mm/yyyy`** | `"05/11/2026"` |
| `min_price` | int | `2000` |
| `max_price` | int | `2300` |
| `modal_price` | int | `2200` |

- Prices came back as **integers**, but still handle missing/blank/zero values defensively.
- `arrival_date` must be converted to ISO `YYYY-MM-DD` before storage (project convention).
- Price unit is **not** in the record. Assumed Rs/quintal for most commodities, but not all (see CLAUDE.md §5.3).

---

## 4. Pagination (observed 2026-11-05)

| Experiment | Result |
|---|---|
| `limit=5&offset=0` vs `limit=5&offset=5` | Different rows → offset paging works. |
| `limit=1000` | `count=1000`, valid JSON. ✅ |
| `limit=10000` | ❌ **Broken JSON** — response cut off at ~1.6 MB (`JSONDecodeError`). |
| `offset=20000` (beyond `total`) | `count=0`, empty `records`, still HTTP 200. |

Takeaways for the collector:
- Use a **page size of ~1000** (≈13 requests/day at current volume). Don't use very large limits.
- Stop paging when a page returns **0 records** (or when `offset >= total`).
- **Always check the JSON parses** — a 200 response can still be a truncated body. Treat a parse failure as retryable.
- Rows are probably not in a guaranteed order; if data refreshes mid-pull, pages could shift
  (rows skipped/duplicated). Compare `records_received` vs `total` in the manifest, and dedup later on the natural key.

---

## 5. Errors, rate limits, timing

| Topic | Status |
|---|---|
| Invalid API key response | _TODO — HTTP status + body_ |
| Rate-limit headers / 429 behaviour | _TODO_ |
| Response speed | Slow / inconsistent at times — a header-only request took >2 min on 2026-11-05. **Always set a timeout.** |
| Daily publish time | `updated_date` was `08:01:15Z` (13:31 IST) on 2026-11-05. _TODO: check on several days to choose a collection time._ |

---

## 6. Data-quality observations

| Observation | Example | Handled in |
|---|---|---|
| State names differ from common spelling | `Keralam` (not `Kerala`) | Phase 2 name standardisation |
| District names include alternate names in brackets | `Kozhikode(Calicut)` | Phase 2 |
| Mixed case in market names | `RYTHU BAZAR FALAKNUMA` vs `Mukkom Market` | Phase 2 (normalise case/spaces) |
| Commodity repeated as variety | commodity `Pumpkin`, variety `Pumpkin` | Fine — keep as-is |

---

## 7. Open questions

- [ ] What time does the data refresh each day? (Record `updated_date` daily for a week.)
- [ ] Is there a rate limit? What does a 429 look like?
- [ ] What does an invalid/expired key return?
- [ ] Is row order stable between pages within one pull?
- [ ] Does `total` change during the day (late-reporting markets)?
- [ ] Does yesterday's data disappear completely once today's arrives?
