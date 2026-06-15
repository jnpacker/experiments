#!/usr/bin/env python3
"""
tmx_funds.py — Fetch Canadian mutual fund NAV data from the TMX Money GraphQL API.

Endpoint: https://app-money.tmx.com/graphql (public, no auth required)

Usage:
  # Current price for one or more funds
  python tmx_funds.py TDB911 TDB900 TDB162

  # Historical price on a specific date
  python tmx_funds.py TDB911 --date 2022-06-15

  # Price range (date series)
  python tmx_funds.py TDB911 --start 2024-01-01 --end 2024-03-31

  # Scheduled dates (e.g. 15th and 28th of each month) — ONE request per symbol
  python tmx_funds.py TDB911 TDB900 --start 2024-01-01 --end 2024-12-31 --schedule 15,28

  # JSON output (pipe-friendly)
  python tmx_funds.py TDB911 TDB900 --json

  # JSON to file
  python tmx_funds.py TDB911 --start 2024-01-01 --end 2024-12-31 --json > prices.json
  python tmx_funds.py TDB911 --start 2024-01-01 --end 2024-12-31 --schedule 15,28 --json > bimonthly.json

Notes:
  - TDB8150 (TD High Interest Savings Account) is not in the TMX database.
    It is a fixed-NAV fund always priced at $10.00 CAD and is handled as a
    built-in stub without hitting the API.
  - Mutual funds have no intraday prices; openPrice/volume are always null/0.
  - --schedule fetches the full range in ONE API request per symbol, then filters
    client-side. If a target date falls on a weekend or holiday, the nearest prior
    available business day is used and noted in the output.
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta

import urllib.request
import urllib.error

GRAPHQL_URL = "https://app-money.tmx.com/graphql"

# Funds that are not in the TMX database and need local stubs.
FIXED_NAV_STUBS = {
    "TDB8150": {
        "symbol": "TDB8150",
        "name": "TD High Interest Savings Account - Investor Series",
        "price": 10.0,
        "currency": "CAD",
        "datatype": "mutual fund",
        "note": "Fixed-NAV stub (not in TMX database)",
    },
    "TDB8851": {
        "symbol": "TDB8851",
        "name": "TD High Interest Savings Account - e-Series",
        "price": 10.0,
        "currency": "CAD",
        "datatype": "mutual fund",
        "note": "Fixed-NAV stub (not in TMX database)",
    },
}

CURRENT_QUOTE_QUERY = """
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
"""

HISTORY_QUERY = """
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
"""


def graphql(query: str, variables: dict) -> dict:
    """Execute a GraphQL query against the TMX Money API."""
    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        print(f"Network error: {e}", file=sys.stderr)
        sys.exit(1)


def fetch_current(symbol: str) -> dict:
    """Fetch the current/latest NAV for a single fund."""
    if symbol.upper() in FIXED_NAV_STUBS:
        stub = FIXED_NAV_STUBS[symbol.upper()].copy()
        stub["datetime"] = date.today().isoformat()
        stub["priceChange"] = 0.0
        stub["percentChange"] = 0.0
        stub["prevClose"] = 10.0
        stub["weeks52high"] = 10.0
        stub["weeks52low"] = 10.0
        return stub

    result = graphql(CURRENT_QUOTE_QUERY, {"symbol": symbol, "locale": "en"})

    errors = result.get("errors")
    if errors:
        code = errors[0].get("code")
        msg = errors[0].get("message", "Unknown error")
        if code == "404":
            return {"symbol": symbol, "error": f"Not found: {msg}"}
        return {"symbol": symbol, "error": msg}

    data = result.get("data", {}).get("getQuoteBySymbol")
    if not data:
        return {"symbol": symbol, "error": "No data returned"}
    return data


def _month_chunks(start: str, end: str) -> list[tuple[str, str]]:
    """
    Split a date range into (chunk_start, chunk_end) pairs, one per calendar month.
    The TMX API returns at most ~25 rows per request regardless of the limit param,
    so we chunk by month to retrieve a full multi-month range.
    """
    import calendar
    start_d = datetime.strptime(start, "%Y-%m-%d").date()
    end_d = datetime.strptime(end, "%Y-%m-%d").date()
    chunks = []
    year, month = start_d.year, start_d.month
    while date(year, month, 1) <= end_d:
        last_day = calendar.monthrange(year, month)[1]
        chunk_start = max(start_d, date(year, month, 1))
        chunk_end = min(end_d, date(year, month, last_day))
        chunks.append((chunk_start.isoformat(), chunk_end.isoformat()))
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return chunks


def fetch_history(symbol: str, start: str, end: str) -> list:
    """
    Fetch historical NAV records for a fund over a date range.

    The TMX API silently caps results at ~25 rows per request (approx. one month
    of business days). For ranges longer than a month we automatically chunk by
    calendar month and merge the results, so callers always get the full range
    with a single call to this function.
    """
    if symbol.upper() in FIXED_NAV_STUBS:
        stub_name = FIXED_NAV_STUBS[symbol.upper()]["name"]
        rows = []
        d = datetime.strptime(start, "%Y-%m-%d").date()
        end_d = datetime.strptime(end, "%Y-%m-%d").date()
        while d <= end_d:
            if d.weekday() < 5:  # Mon–Fri only
                rows.append({
                    "datetime": d.isoformat(),
                    "closePrice": 10.0,
                    "changePercent": 0.0,
                    "symbol": symbol.upper(),
                    "name": stub_name,
                    "note": "Fixed-NAV stub",
                })
            d += timedelta(days=1)
        return rows

    chunks = _month_chunks(start, end)
    all_rows = []
    for chunk_start, chunk_end in chunks:
        result = graphql(HISTORY_QUERY, {
            "symbol": symbol,
            "start": chunk_start,
            "end": chunk_end,
        })
        errors = result.get("errors")
        if errors:
            msg = errors[0].get("message", "Unknown error")
            return [{"symbol": symbol, "error": msg}]
        rows = result.get("data", {}).get("getCompanyPriceHistory", [])
        all_rows.extend(rows)

    # Deduplicate (unlikely but safe) and sort descending to match API default order
    seen = {}
    for row in all_rows:
        seen[row["datetime"][:10]] = row
    sorted_rows = sorted(seen.values(), key=lambda r: r["datetime"], reverse=True)

    for row in sorted_rows:
        row["symbol"] = symbol.upper()
    return sorted_rows


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_price(val) -> str:
    if val is None:
        return "—"
    return f"${val:,.4f}"


def fmt_change(val, pct) -> str:
    if val is None:
        return "—"
    sign = "+" if val >= 0 else ""
    pct_str = f" ({sign}{pct:.2f}%)" if pct is not None else ""
    return f"{sign}{val:,.4f}{pct_str}"


def fmt_date(val) -> str:
    if not val:
        return "—"
    # Trim time/timezone for mutual funds — date is what matters
    return val[:10]


def print_current_table(results: list[dict]):
    col_widths = [8, 45, 12, 20, 14, 14, 12]
    headers = ["Symbol", "Name", "Price (CAD)", "Change", "52W High", "52W Low", "NAV Date"]
    sep = "  ".join("-" * w for w in col_widths)
    header_row = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(header_row)
    print(sep)
    for r in results:
        if "error" in r:
            row = [
                r.get("symbol", "?").ljust(col_widths[0]),
                f"ERROR: {r['error']}"[:col_widths[1]].ljust(col_widths[1]),
                *["—".ljust(w) for w in col_widths[2:]],
            ]
        else:
            note = f" *" if r.get("note") else ""
            row = [
                r.get("symbol", "").ljust(col_widths[0]),
                (r.get("name", "") + note)[:col_widths[1]].ljust(col_widths[1]),
                fmt_price(r.get("price")).ljust(col_widths[2]),
                fmt_change(r.get("priceChange"), r.get("percentChange")).ljust(col_widths[3]),
                fmt_price(r.get("weeks52high")).ljust(col_widths[4]),
                fmt_price(r.get("weeks52low")).ljust(col_widths[5]),
                fmt_date(r.get("datetime")).ljust(col_widths[6]),
            ]
        print("  ".join(row))
    stubs = [r for r in results if r.get("note")]
    if stubs:
        print("\n  * Fixed-NAV stub — not in TMX database, always $10.00 CAD")


def schedule_dates(start: str, end: str, days: list[int]) -> list[date]:
    """
    Generate target dates for every month in [start, end] where the day-of-month
    is in `days`. Clamps to the last day of the month when the target day exceeds
    the month length (e.g. day 28 in February becomes Feb 28).
    """
    import calendar
    start_d = datetime.strptime(start, "%Y-%m-%d").date()
    end_d = datetime.strptime(end, "%Y-%m-%d").date()

    targets = []
    # Walk month by month
    year, month = start_d.year, start_d.month
    while date(year, month, 1) <= end_d:
        last_day = calendar.monthrange(year, month)[1]
        for day in sorted(days):
            actual_day = min(day, last_day)
            target = date(year, month, actual_day)
            if start_d <= target <= end_d:
                targets.append(target)
        # Advance to next month
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return targets


def filter_to_schedule(rows: list[dict], targets: list[date]) -> list[dict]:
    """
    Given a full history row list and a set of target dates, return one row per
    target date using the nearest prior available business day if the exact date
    has no data (weekend / holiday).

    Adds a `scheduled_date` field (the originally requested date) and a
    `substituted` bool so callers know when a fallback was used.
    """
    # Build a lookup: date string -> row
    by_date = {r["datetime"][:10]: r for r in rows}
    available = sorted(by_date.keys())  # ascending list of available date strings

    result = []
    for target in targets:
        target_str = target.isoformat()
        if target_str in by_date:
            row = dict(by_date[target_str])
            row["scheduled_date"] = target_str
            row["substituted"] = False
        else:
            # Find the nearest prior available date
            prior = [d for d in available if d <= target_str]
            if prior:
                row = dict(by_date[prior[-1]])
                row["scheduled_date"] = target_str
                row["substituted"] = True
            else:
                # Target is before all available data
                row = {
                    "datetime": target_str,
                    "scheduled_date": target_str,
                    "closePrice": None,
                    "changePercent": None,
                    "substituted": False,
                    "error": "Before available data range",
                }
        result.append(row)
    return result


def print_schedule_table(symbol: str, rows: list[dict]):
    if not rows:
        print(f"No data returned for {symbol}")
        return
    if rows and "error" in rows[0] and "scheduled_date" not in rows[0]:
        print(f"Error for {symbol}: {rows[0]['error']}")
        return

    col_widths = [12, 12, 14, 5]
    headers = ["Target Date", "NAV Date", "Close (NAV)", "Sub?"]
    sep = "  ".join("-" * w for w in col_widths)
    header_row = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))

    name = rows[0].get("name", symbol)
    print(f"\n{symbol}  —  {name}")
    print(header_row)
    print(sep)
    substitutions = 0
    for r in rows:
        sub_flag = "*" if r.get("substituted") else ""
        if sub_flag:
            substitutions += 1
        price = fmt_price(r.get("closePrice")) if r.get("closePrice") is not None else "N/A"
        row = [
            r.get("scheduled_date", "—").ljust(col_widths[0]),
            fmt_date(r.get("datetime")).ljust(col_widths[1]),
            price.ljust(col_widths[2]),
            sub_flag.ljust(col_widths[3]),
        ]
        print("  ".join(row))
    if substitutions:
        print(f"\n  * Nearest prior business day used (weekend or holiday)")
    note = rows[0].get("note")
    if note:
        print(f"\n  Note: {note}")


def print_history_table(symbol: str, rows: list[dict]):
    if not rows:
        print(f"No data returned for {symbol}")
        return
    if "error" in rows[0]:
        print(f"Error for {symbol}: {rows[0]['error']}")
        return

    col_widths = [12, 14, 12]
    headers = ["Date", "Close (NAV)", "Change %"]
    sep = "  ".join("-" * w for w in col_widths)
    header_row = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))

    name = rows[0].get("name", symbol)
    print(f"\n{symbol}  —  {name}")
    print(header_row)
    print(sep)
    for r in rows:
        pct = r.get("changePercent")
        pct_str = f"{pct:+.3f}%" if pct is not None else "—"
        row = [
            fmt_date(r.get("datetime")).ljust(col_widths[0]),
            fmt_price(r.get("closePrice")).ljust(col_widths[1]),
            pct_str.ljust(col_widths[2]),
        ]
        print("  ".join(row))
    note = rows[0].get("note")
    if note:
        print(f"\n  * {note}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch Canadian mutual fund NAV data from TMX Money.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "symbols",
        nargs="+",
        metavar="SYMBOL",
        help="One or more fund codes, e.g. TDB911 TDB900",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Fetch NAV for a single historical date",
    )
    group.add_argument(
        "--start",
        metavar="YYYY-MM-DD",
        help="Start of date range (requires --end)",
    )
    parser.add_argument(
        "--end",
        metavar="YYYY-MM-DD",
        default=date.today().isoformat(),
        help="End of date range (default: today)",
    )
    parser.add_argument(
        "--schedule",
        metavar="DAYS",
        help=(
            "Comma-separated day-of-month numbers to sample (e.g. '15,28'). "
            "Fetches the full range in one request per symbol and filters client-side. "
            "If a target date is a weekend or holiday, the nearest prior business day "
            "is used. Requires --start and --end."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted table",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    symbols = [s.upper() for s in args.symbols]

    # Validate date arguments
    if args.start and not args.end:
        print("Error: --start requires --end", file=sys.stderr)
        sys.exit(1)

    if args.schedule and not args.start:
        print("Error: --schedule requires --start (and optionally --end)", file=sys.stderr)
        sys.exit(1)

    # Parse schedule days
    schedule_days = None
    if args.schedule:
        try:
            schedule_days = [int(d.strip()) for d in args.schedule.split(",")]
            if not all(1 <= d <= 31 for d in schedule_days):
                raise ValueError
        except ValueError:
            print("Error: --schedule must be comma-separated day numbers 1–31 (e.g. '15,28')", file=sys.stderr)
            sys.exit(1)

    # --- Scheduled dates mode ---
    if schedule_days:
        start = args.start
        end = args.end
        targets = schedule_dates(start, end, schedule_days)

        all_rows = []
        for symbol in symbols:
            raw_rows = fetch_history(symbol, start, end)
            # Attach symbol name from first row if available
            filtered = filter_to_schedule(raw_rows, targets)
            for row in filtered:
                row["symbol"] = symbol
                if raw_rows and "name" in raw_rows[0]:
                    row.setdefault("name", raw_rows[0]["name"])
            all_rows.extend(filtered)

        if args.json:
            print(json.dumps(all_rows, indent=2))
        else:
            seen = {}
            for row in all_rows:
                seen.setdefault(row["symbol"], []).append(row)
            for symbol, rows in seen.items():
                print_schedule_table(symbol, rows)

    # --- Historical range mode ---
    elif args.start or args.date:
        start = args.date or args.start
        end = args.date or args.end

        all_rows = []
        for symbol in symbols:
            rows = fetch_history(symbol, start, end)
            all_rows.extend(rows)

        if args.json:
            print(json.dumps(all_rows, indent=2))
        else:
            # Group by symbol for display
            seen = {}
            for row in all_rows:
                seen.setdefault(row["symbol"], []).append(row)
            for symbol, rows in seen.items():
                print_history_table(symbol, rows)

    # --- Current quote mode ---
    else:
        results = [fetch_current(s) for s in symbols]

        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print_current_table(results)


if __name__ == "__main__":
    main()
