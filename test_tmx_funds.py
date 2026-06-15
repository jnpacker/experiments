#!/usr/bin/env python3
"""
test_tmx_funds.py — Unit tests for tmx_funds.py.

All network calls are mocked. Zero real HTTP requests are made.

Run with:
  python -m pytest test_tmx_funds.py -v
  # or without pytest:
  python test_tmx_funds.py
"""

import json
import sys
import unittest
from datetime import date
from io import StringIO
from unittest.mock import MagicMock, call, patch

import tmx_funds as tf

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

QUOTE_TDB911 = {
    "data": {
        "getQuoteBySymbol": {
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
            "weeks52low": 18.4323,
        }
    }
}

QUOTE_NOT_FOUND = {
    "errors": [{"message": "Sorry, we couldn't find any results.", "code": "404"}],
    "data": {"getQuoteBySymbol": None},
}

# A month of business days for January 2025
HISTORY_JAN_2025 = {
    "data": {
        "getCompanyPriceHistory": [
            {"datetime": "2025-01-31", "closePrice": 17.7664, "changePercent": 0.331},
            {"datetime": "2025-01-30", "closePrice": 17.708,  "changePercent": 0.579},
            {"datetime": "2025-01-29", "closePrice": 17.6011, "changePercent": 0.499},
            {"datetime": "2025-01-28", "closePrice": 17.4358, "changePercent": -0.443},
            {"datetime": "2025-01-27", "closePrice": 17.5136, "changePercent": 0.446},
            {"datetime": "2025-01-24", "closePrice": 17.4358, "changePercent": 0.508},
            {"datetime": "2025-01-23", "closePrice": 17.3482, "changePercent": 0.282},
            {"datetime": "2025-01-22", "closePrice": 17.2996, "changePercent": 0.396},
            {"datetime": "2025-01-21", "closePrice": 17.2315, "changePercent": 0.68},
            {"datetime": "2025-01-20", "closePrice": 17.1149, "changePercent": 0.686},
            {"datetime": "2025-01-17", "closePrice": 16.9982, "changePercent": 0.286},
            {"datetime": "2025-01-16", "closePrice": 16.9495, "changePercent": 1.12},
            {"datetime": "2025-01-15", "closePrice": 16.7453, "changePercent": 1.118},
            {"datetime": "2025-01-14", "closePrice": 16.5606, "changePercent": -0.248},
            {"datetime": "2025-01-13", "closePrice": 16.5897, "changePercent": -0.787},
            {"datetime": "2025-01-10", "closePrice": 16.7162, "changePercent": -0.946},
            {"datetime": "2025-01-09", "closePrice": 16.8717, "changePercent": 0.059},
            {"datetime": "2025-01-08", "closePrice": 16.862,  "changePercent": -0.461},
            {"datetime": "2025-01-07", "closePrice": 16.9398, "changePercent": 0.22},
            {"datetime": "2025-01-06", "closePrice": 16.9009, "changePercent": 0.462},
            {"datetime": "2025-01-03", "closePrice": 16.8231, "changePercent": -0.116},
            {"datetime": "2025-01-02", "closePrice": 16.8426, "changePercent": 0.0},
        ]
    }
}

HISTORY_FEB_2025 = {
    "data": {
        "getCompanyPriceHistory": [
            {"datetime": "2025-02-28", "closePrice": 18.15,  "changePercent": 0.2},
            {"datetime": "2025-02-27", "closePrice": 18.11,  "changePercent": -0.1},
            {"datetime": "2025-02-14", "closePrice": 17.90,  "changePercent": 0.4},
            {"datetime": "2025-02-03", "closePrice": 17.75,  "changePercent": 0.3},
        ]
    }
}

HISTORY_ERROR = {
    "errors": [{"message": "Sorry, we couldn't find any results for \"BADFUND\"."}],
    "data": {"getCompanyPriceHistory": None},
}


# ---------------------------------------------------------------------------
# _month_chunks
# ---------------------------------------------------------------------------

class TestMonthChunks(unittest.TestCase):
    def test_single_month(self):
        chunks = tf._month_chunks("2025-01-10", "2025-01-25")
        self.assertEqual(chunks, [("2025-01-10", "2025-01-25")])

    def test_two_months(self):
        chunks = tf._month_chunks("2025-01-15", "2025-02-20")
        self.assertEqual(chunks, [
            ("2025-01-15", "2025-01-31"),
            ("2025-02-01", "2025-02-20"),
        ])

    def test_year_boundary(self):
        chunks = tf._month_chunks("2024-12-01", "2025-01-31")
        self.assertEqual(chunks, [
            ("2024-12-01", "2024-12-31"),
            ("2025-01-01", "2025-01-31"),
        ])

    def test_exact_month_boundaries(self):
        chunks = tf._month_chunks("2025-03-01", "2025-03-31")
        self.assertEqual(chunks, [("2025-03-01", "2025-03-31")])

    def test_february_leap_year(self):
        chunks = tf._month_chunks("2024-02-01", "2024-02-29")
        self.assertEqual(chunks, [("2024-02-01", "2024-02-29")])

    def test_february_non_leap_year(self):
        chunks = tf._month_chunks("2025-02-01", "2025-03-31")
        self.assertEqual(chunks, [
            ("2025-02-01", "2025-02-28"),
            ("2025-03-01", "2025-03-31"),
        ])


# ---------------------------------------------------------------------------
# schedule_dates
# ---------------------------------------------------------------------------

class TestScheduleDates(unittest.TestCase):
    def test_basic_two_days(self):
        targets = tf.schedule_dates("2025-01-01", "2025-02-28", [15, 28])
        self.assertEqual(targets, [
            date(2025, 1, 15),
            date(2025, 1, 28),
            date(2025, 2, 15),
            date(2025, 2, 28),
        ])

    def test_clamps_to_month_end(self):
        # Day 31 in February should become Feb 28 (non-leap)
        targets = tf.schedule_dates("2025-02-01", "2025-02-28", [31])
        self.assertEqual(targets, [date(2025, 2, 28)])

    def test_clamps_leap_february(self):
        # Day 31 in Feb 2024 (leap) should become Feb 29
        targets = tf.schedule_dates("2024-02-01", "2024-02-29", [31])
        self.assertEqual(targets, [date(2024, 2, 29)])

    def test_respects_start_boundary(self):
        # Start is Jan 20; day 15 should be skipped for January
        targets = tf.schedule_dates("2025-01-20", "2025-02-28", [15, 28])
        self.assertEqual(targets, [
            date(2025, 1, 28),
            date(2025, 2, 15),
            date(2025, 2, 28),
        ])

    def test_respects_end_boundary(self):
        # End is Feb 20; day 28 should be skipped for February
        targets = tf.schedule_dates("2025-01-01", "2025-02-20", [15, 28])
        self.assertEqual(targets, [
            date(2025, 1, 15),
            date(2025, 1, 28),
            date(2025, 2, 15),
        ])

    def test_single_day_single_month(self):
        targets = tf.schedule_dates("2025-06-01", "2025-06-30", [15])
        self.assertEqual(targets, [date(2025, 6, 15)])

    def test_year_boundary(self):
        targets = tf.schedule_dates("2024-12-01", "2025-01-31", [28])
        self.assertEqual(targets, [date(2024, 12, 28), date(2025, 1, 28)])


# ---------------------------------------------------------------------------
# filter_to_schedule
# ---------------------------------------------------------------------------

class TestFilterToSchedule(unittest.TestCase):
    # Use January 2025 rows (business days only)
    def _jan_rows(self):
        return [dict(r) for r in HISTORY_JAN_2025["data"]["getCompanyPriceHistory"]]

    def test_exact_match(self):
        # Jan 15 2025 is a Wednesday — exists in data
        rows = self._jan_rows()
        targets = [date(2025, 1, 15)]
        result = tf.filter_to_schedule(rows, targets)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["datetime"], "2025-01-15")
        self.assertEqual(result[0]["scheduled_date"], "2025-01-15")
        self.assertFalse(result[0]["substituted"])
        self.assertAlmostEqual(result[0]["closePrice"], 16.7453)

    def test_weekend_falls_back_to_friday(self):
        # Jan 18 2025 is a Saturday — should fall back to Jan 17 (Friday)
        rows = self._jan_rows()
        targets = [date(2025, 1, 18)]
        result = tf.filter_to_schedule(rows, targets)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["scheduled_date"], "2025-01-18")
        self.assertEqual(result[0]["datetime"], "2025-01-17")
        self.assertTrue(result[0]["substituted"])

    def test_holiday_falls_back(self):
        # Jan 1 2025 is New Year's Day (not in data) — falls back to Dec 31 2024
        # but our rows only start Jan 2; should get no prior row
        rows = self._jan_rows()
        targets = [date(2024, 12, 31)]  # before the data
        result = tf.filter_to_schedule(rows, targets)
        self.assertEqual(len(result), 1)
        self.assertIn("error", result[0])
        self.assertIsNone(result[0]["closePrice"])

    def test_multiple_targets_mixed(self):
        rows = self._jan_rows()
        targets = [date(2025, 1, 15), date(2025, 1, 18), date(2025, 1, 28)]
        result = tf.filter_to_schedule(rows, targets)
        self.assertEqual(len(result), 3)
        # Jan 15: exact
        self.assertFalse(result[0]["substituted"])
        self.assertEqual(result[0]["datetime"], "2025-01-15")
        # Jan 18 (Sat): substitute -> Jan 17
        self.assertTrue(result[1]["substituted"])
        self.assertEqual(result[1]["datetime"], "2025-01-17")
        # Jan 28: exact (Tuesday)
        self.assertFalse(result[2]["substituted"])
        self.assertEqual(result[2]["datetime"], "2025-01-28")


# ---------------------------------------------------------------------------
# fetch_current
# ---------------------------------------------------------------------------

class TestFetchCurrent(unittest.TestCase):
    def test_stub_tdb8150(self):
        # Should return $10 without any network call
        result = tf.fetch_current("TDB8150")
        self.assertEqual(result["price"], 10.0)
        self.assertEqual(result["currency"], "CAD")
        self.assertIn("note", result)
        self.assertEqual(result["datetime"], date.today().isoformat())

    def test_stub_case_insensitive(self):
        result = tf.fetch_current("tdb8150")
        self.assertEqual(result["price"], 10.0)

    @patch("tmx_funds.graphql", return_value=QUOTE_TDB911)
    def test_live_fund(self, mock_gql):
        result = tf.fetch_current("TDB911")
        self.assertEqual(result["symbol"], "TDB911")
        self.assertAlmostEqual(result["price"], 23.19)
        self.assertEqual(result["currency"], "CAD")
        mock_gql.assert_called_once()

    @patch("tmx_funds.graphql", return_value=QUOTE_NOT_FOUND)
    def test_not_found_returns_error(self, mock_gql):
        result = tf.fetch_current("BADFUND")
        self.assertIn("error", result)
        self.assertIn("Not found", result["error"])

    @patch("tmx_funds.graphql", return_value={"data": {"getQuoteBySymbol": None}})
    def test_no_data_returns_error(self, mock_gql):
        result = tf.fetch_current("TDB911")
        self.assertIn("error", result)


# ---------------------------------------------------------------------------
# fetch_history
# ---------------------------------------------------------------------------

class TestFetchHistory(unittest.TestCase):
    def test_stub_generates_business_days_only(self):
        # 2025-01-04 (Sat) to 2025-01-06 (Mon): only Mon Jan 6 should appear
        rows = tf.fetch_history("TDB8150", "2025-01-04", "2025-01-06")
        dates = [r["datetime"] for r in rows]
        self.assertIn("2025-01-06", dates)   # Monday
        self.assertNotIn("2025-01-04", dates)  # Saturday
        self.assertNotIn("2025-01-05", dates)  # Sunday
        for r in rows:
            self.assertEqual(r["closePrice"], 10.0)

    @patch("tmx_funds.graphql", return_value=HISTORY_JAN_2025)
    def test_single_month_one_request(self, mock_gql):
        rows = tf.fetch_history("TDB911", "2025-01-01", "2025-01-31")
        mock_gql.assert_called_once()
        self.assertEqual(len(rows), 22)  # 22 business days in Jan 2025
        # Rows should be sorted descending
        dates = [r["datetime"] for r in rows]
        self.assertEqual(dates, sorted(dates, reverse=True))

    @patch("tmx_funds.graphql", side_effect=[HISTORY_JAN_2025, HISTORY_FEB_2025])
    def test_two_months_two_requests(self, mock_gql):
        rows = tf.fetch_history("TDB911", "2025-01-01", "2025-02-28")
        self.assertEqual(mock_gql.call_count, 2)
        # Combined and deduplicated
        dates = {r["datetime"] for r in rows}
        self.assertIn("2025-01-15", dates)
        self.assertIn("2025-02-28", dates)

    @patch("tmx_funds.graphql", side_effect=[HISTORY_JAN_2025, HISTORY_FEB_2025])
    def test_symbol_attached_to_rows(self, mock_gql):
        rows = tf.fetch_history("TDB911", "2025-01-01", "2025-02-28")
        for row in rows:
            self.assertEqual(row["symbol"], "TDB911")

    @patch("tmx_funds.graphql", return_value=HISTORY_ERROR)
    def test_api_error_propagates(self, mock_gql):
        rows = tf.fetch_history("BADFUND", "2025-01-01", "2025-01-31")
        self.assertEqual(len(rows), 1)
        self.assertIn("error", rows[0])

    @patch("tmx_funds.graphql", return_value=HISTORY_JAN_2025)
    def test_deduplicates_overlapping_chunks(self, mock_gql):
        # If somehow the same date appears twice (shouldn't happen but be safe)
        dupe_response = {
            "data": {
                "getCompanyPriceHistory": [
                    {"datetime": "2025-01-15", "closePrice": 16.7453, "changePercent": 1.118},
                    {"datetime": "2025-01-15", "closePrice": 16.9999, "changePercent": 9.999},  # dupe
                ]
            }
        }
        with patch("tmx_funds.graphql", return_value=dupe_response):
            rows = tf.fetch_history("TDB911", "2025-01-15", "2025-01-15")
        jan15_rows = [r for r in rows if r["datetime"] == "2025-01-15"]
        self.assertEqual(len(jan15_rows), 1)


# ---------------------------------------------------------------------------
# Integration: schedule mode end-to-end (logic only, no network)
# ---------------------------------------------------------------------------

class TestScheduleIntegration(unittest.TestCase):
    @patch("tmx_funds.graphql", side_effect=[HISTORY_JAN_2025, HISTORY_FEB_2025])
    def test_schedule_15_and_28(self, mock_gql):
        """15th and 28th of Jan+Feb 2025 — two API calls, four output rows."""
        raw = tf.fetch_history("TDB911", "2025-01-01", "2025-02-28")
        targets = tf.schedule_dates("2025-01-01", "2025-02-28", [15, 28])
        result = tf.filter_to_schedule(raw, targets)

        self.assertEqual(len(result), 4)

        # Jan 15 — Wednesday, exact match
        self.assertEqual(result[0]["scheduled_date"], "2025-01-15")
        self.assertFalse(result[0]["substituted"])
        self.assertAlmostEqual(result[0]["closePrice"], 16.7453)

        # Jan 28 — Tuesday, exact match
        self.assertEqual(result[1]["scheduled_date"], "2025-01-28")
        self.assertFalse(result[1]["substituted"])
        self.assertAlmostEqual(result[1]["closePrice"], 17.4358)

        # Feb 15 — Saturday 2025, falls back to Feb 14 (Friday)
        self.assertEqual(result[2]["scheduled_date"], "2025-02-15")
        self.assertTrue(result[2]["substituted"])
        self.assertEqual(result[2]["datetime"], "2025-02-14")

        # Feb 28 — Friday, exact match
        self.assertEqual(result[3]["scheduled_date"], "2025-02-28")
        self.assertFalse(result[3]["substituted"])
        self.assertAlmostEqual(result[3]["closePrice"], 18.15)

    @patch("tmx_funds.graphql", return_value=HISTORY_JAN_2025)
    def test_only_one_api_call_per_symbol_per_month(self, mock_gql):
        """Confirm we do NOT make one call per target date."""
        tf.fetch_history("TDB911", "2025-01-01", "2025-01-31")
        # One month = one API call
        self.assertEqual(mock_gql.call_count, 1)

    def test_stub_schedule_no_network(self):
        """TDB8150 stub should never hit the network even in schedule mode."""
        raw = tf.fetch_history("TDB8150", "2025-01-01", "2025-01-31")
        targets = tf.schedule_dates("2025-01-01", "2025-01-31", [15, 28])
        result = tf.filter_to_schedule(raw, targets)
        # Both should be exact matches (business days)
        self.assertEqual(result[0]["closePrice"], 10.0)
        self.assertEqual(result[1]["closePrice"], 10.0)
        self.assertFalse(result[0]["substituted"])


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

class TestFormatters(unittest.TestCase):
    def test_fmt_price_normal(self):
        self.assertEqual(tf.fmt_price(23.19), "$23.1900")

    def test_fmt_price_none(self):
        self.assertEqual(tf.fmt_price(None), "—")

    def test_fmt_price_round_number(self):
        self.assertEqual(tf.fmt_price(10.0), "$10.0000")

    def test_fmt_change_positive(self):
        self.assertIn("+", tf.fmt_change(0.42, 1.84))
        self.assertIn("1.84%", tf.fmt_change(0.42, 1.84))

    def test_fmt_change_negative(self):
        result = tf.fmt_change(-0.30, -1.29)
        self.assertIn("-0.3000", result)
        self.assertIn("-1.29%", result)

    def test_fmt_change_none(self):
        self.assertEqual(tf.fmt_change(None, None), "—")

    def test_fmt_date_strips_time(self):
        self.assertEqual(tf.fmt_date("2026-06-12T20:00:00-04:00"), "2026-06-12")

    def test_fmt_date_plain(self):
        self.assertEqual(tf.fmt_date("2025-01-15"), "2025-01-15")

    def test_fmt_date_none(self):
        self.assertEqual(tf.fmt_date(None), "—")


if __name__ == "__main__":
    unittest.main(verbosity=2)
