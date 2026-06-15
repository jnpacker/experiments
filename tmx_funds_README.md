# tmx_funds.py

Fetch current and historical NAV (Net Asset Value) prices for Canadian mutual
funds using the public TMX Money GraphQL API.

No API key. No external dependencies. Standard library only.

---

## Background

Most mainstream financial data sources (Yahoo Finance, Google Finance, Morningstar)
do not carry TD proprietary mutual fund data. The TMX Money website
(`money.tmx.com`) does, and its frontend is backed by an unauthenticated public
GraphQL API at `https://app-money.tmx.com/graphql`.

This script exposes that API as a simple command-line tool.

**API behaviour worth knowing:**

- Results are capped at approximately one month of business days per request (~22
  rows). The script automatically chunks multi-month ranges by calendar month and
  merges the results, so you always get the full range in a single function call.
- Mutual fund NAVs are struck at end-of-day; `openPrice`, `dayHigh`, `dayLow`,
  and `volume` are always null or zero.
- The `datetime` field on historical rows is a plain date string (`YYYY-MM-DD`).
  On current quotes it includes a full ISO 8601 timestamp with timezone
  (`2026-06-12T20:00:00-04:00`).
- The API is undocumented and unofficial. Field names or behaviour could change
  without notice.

---

## Requirements

Python 3.10 or later. No third-party packages required.

---

## Files

| File | Purpose |
|---|---|
| `tmx_funds.py` | Main script |
| `test_tmx_funds.py` | Unit tests (zero real network calls) |

---

## Usage

### Current price

Fetch the latest NAV for one or more funds:

```
python3 tmx_funds.py TDB911 TDB900 TDB162
```

```
Symbol    Name                                           Price (CAD)   Change                52W High        52W Low         NAV Date
--------  ---------------------------------------------  ------------  --------------------  --------------  --------------  ------------
TDB911    TD International Index Fund - e-Series         $23.1900      +0.4200 (+1.84%)      $23.1900        $18.4323        2026-06-12
TDB900    TD Canadian Index Fund e-Series                $59.6700      +0.4700 (+0.79%)      $60.1700        $44.3149        2026-06-12
TDB162    TD Canadian Bond Fund - Investor Series        $12.6400      +0.0000 (+0.00%)      $12.7181        $12.0888        2026-06-12
```

### Historical price — single date

```
python3 tmx_funds.py TDB911 --date 2022-06-15
```

```
TDB911  —  TD International Index Fund - e-Series
Date          Close (NAV)     Change %
------------  --------------  ------------
2022-06-15    $11.7859        +0.853%
```

If the date is a weekend or market holiday the API automatically returns the
nearest prior business day.

### Historical price — date range

```
python3 tmx_funds.py TDB911 TDB900 --start 2026-06-01 --end 2026-06-12
```

```
TDB911  —  TD International Index Fund - e-Series
Date          Close (NAV)     Change %
------------  --------------  ------------
2026-06-12    $23.1900        +1.845%
2026-06-11    $22.7700        +0.752%
2026-06-10    $22.6000        -0.659%
...

TDB900  —  TD Canadian Index Fund e-Series
Date          Close (NAV)     Change %
------------  --------------  ------------
2026-06-12    $59.6700        +0.794%
...
```

### Scheduled dates

Sample specific days of the month (e.g. the 15th and 28th) across a date range.
The full range is fetched in **one API request per symbol per month**, then
filtered client-side — not one request per target date.

```
python3 tmx_funds.py TDB911 TDB900 --start 2025-01-01 --end 2025-06-30 --schedule 15,28
```

```
TDB911  —  TD International Index Fund - e-Series
Target Date   NAV Date      Close (NAV)     Sub?
------------  ------------  --------------  -----
2025-01-15    2025-01-15    $16.7453
2025-01-28    2025-01-28    $17.4358
2025-02-15    2025-02-14    $17.9000        *
2025-02-28    2025-02-28    $18.1500
...

  * Nearest prior business day used (weekend or holiday)
```

The `Sub?` column is marked `*` when the exact target date had no data (weekend
or holiday) and the nearest prior business day was used instead. Both the
originally requested date (`Target Date`) and the actual NAV date (`NAV Date`)
are shown so the substitution is always visible.

**February handling:** day 28 is used for February in non-leap years; day 29 in
leap years. Day 31 in any 30-day month is clamped to the last day of that month.

### JSON output

Add `--json` to any command for machine-readable output suitable for piping or
file redirection:

```
python3 tmx_funds.py TDB911 TDB900 --json
python3 tmx_funds.py TDB911 --date 2022-06-15 --json
python3 tmx_funds.py TDB911 --start 2024-01-01 --end 2024-12-31 --json > history.json
python3 tmx_funds.py TDB911 --start 2024-01-01 --end 2024-12-31 --schedule 15,28 --json > bimonthly.json
```

Current quote JSON shape:

```json
[
  {
    "symbol": "TDB911",
    "name": "TD International Index Fund - e-Series",
    "price": 23.19,
    "priceChange": 0.42,
    "percentChange": 1.844532,
    "datetime": "2026-06-12T20:00:00-04:00",
    "datatype": "mutual fund",
    "currency": "CAD",
    "prevClose": 22.77,
    "weeks52high": 23.19,
    "weeks52low": 18.4323
  }
]
```

Historical range JSON shape:

```json
[
  {
    "datetime": "2024-01-15",
    "closePrice": 15.0333,
    "changePercent": 0.701,
    "symbol": "TDB911"
  }
]
```

Scheduled dates JSON shape (adds `scheduled_date` and `substituted` fields):

```json
[
  {
    "datetime": "2025-01-15",
    "scheduled_date": "2025-01-15",
    "closePrice": 16.7453,
    "changePercent": 1.118,
    "substituted": false,
    "symbol": "TDB911"
  },
  {
    "datetime": "2025-02-14",
    "scheduled_date": "2025-02-15",
    "closePrice": 17.9,
    "changePercent": 0.4,
    "substituted": true,
    "symbol": "TDB911"
  }
]
```

---

## Fixed-NAV stubs

The TD High Interest Savings Account funds are not in the TMX database because
they function as deposit-like products with a permanently fixed NAV of **$10.00
CAD**. They are handled locally without any network call:

| Symbol | Name |
|---|---|
| `TDB8150` | TD High Interest Savings Account — Investor Series |
| `TDB8851` | TD High Interest Savings Account — e-Series |

In table output these rows are annotated with `*` and a footnote. In JSON output
they include a `"note"` field. In schedule/history mode, stub rows for weekends
are omitted (only business days are generated).

---

## All options

```
usage: tmx_funds.py [-h] [--date YYYY-MM-DD | --start YYYY-MM-DD]
                    [--end YYYY-MM-DD] [--schedule DAYS] [--json]
                    SYMBOL [SYMBOL ...]

positional arguments:
  SYMBOL              One or more fund codes, e.g. TDB911 TDB900

options:
  --date YYYY-MM-DD   Fetch NAV for a single historical date
  --start YYYY-MM-DD  Start of date range
  --end YYYY-MM-DD    End of date range (default: today)
  --schedule DAYS     Comma-separated day-of-month numbers, e.g. 15,28
                      Requires --start. Filters client-side from a full range
                      fetch; does not make one request per target date.
  --json              Output JSON instead of a formatted table
```

`--date` and `--start` are mutually exclusive. `--schedule` requires `--start`.

---

## Running the tests

```
python3 -m pytest test_tmx_funds.py -v
```

All 40 tests run in under a second. Zero real network calls are made — the
`graphql()` function is mocked throughout.

Test coverage:

| Class | What is tested |
|---|---|
| `TestMonthChunks` | Month boundary splitting, leap years, year rollover |
| `TestScheduleDates` | Day clamping, start/end boundary trimming, Feb edge cases |
| `TestFilterToSchedule` | Exact match, weekend fallback, pre-data-range target, mixed batch |
| `TestFetchCurrent` | Stub funds, live quote, 404 error, empty response |
| `TestFetchHistory` | Stub business-day generation, single-month one-request, two-month chunking, symbol attachment, error propagation, deduplication |
| `TestScheduleIntegration` | End-to-end schedule with mocked API, request count assertion, stub-with-schedule |
| `TestFormatters` | Price, change, and date formatting edge cases |

---

## API reference

**Endpoint:** `POST https://app-money.tmx.com/graphql`

**Authentication:** None.

### Current quote

```graphql
query getQuoteBySymbol($symbol: String, $locale: String) {
  getQuoteBySymbol(symbol: $symbol, locale: $locale) {
    symbol
    name
    price
    priceChange
    percentChange
    datetime
    datatype
    currency
    prevClose
    weeks52high
    weeks52low
  }
}
```

Variables: `{"symbol": "TDB911", "locale": "en"}`

### Historical prices

```graphql
query getCompanyPriceHistory(
  $symbol: String!
  $start: String
  $end: String
  $limit: Int
) {
  getCompanyPriceHistory(
    symbol: $symbol
    start: $start
    end: $end
    limit: $limit
  ) {
    datetime
    closePrice
    changePercent
  }
}
```

Variables: `{"symbol": "TDB911", "start": "2025-01-01", "end": "2025-01-31"}`

**Note:** The `limit` parameter does not expand the result beyond ~25 rows. For
ranges longer than one month, issue one request per calendar month.
