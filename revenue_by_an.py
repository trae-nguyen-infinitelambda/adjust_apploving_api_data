"""
Revenue by Ad Network (Daily): Fetch daily revenue from AppLovin MAX
Revenue Reporting API, aggregate by ad network, push to Google Sheets
tab "Revenue Daily by AN".

Structure: each row is an ad network name, each column is a date.
First run: pulls from 2026-04-06 to today.
Subsequent runs: updates yesterday + adds today.
"""
import pandas as pd
from datetime import datetime, timedelta

from api_fetchers import fetch_max_revenue_by_network
from sheets_helper import get_worksheet, update_pivot_table

# =========================
# CONFIG
# =========================
SHEET_TAB = "Revenue Daily by AN"
FIRST_RUN_START = "2026-04-06"


def get_date_range():
    """
    Determine date range.
    Always fetches from FIRST_RUN_START to today.
    The sheet logic handles deduplication (existing columns overwritten).
    """
    today = datetime.today()
    date_from = FIRST_RUN_START
    date_to = today.strftime("%Y-%m-%d")
    return date_from, date_to


def build_revenue_by_an_pivot(raw_df):
    """
    Given raw daily revenue data (columns: day, network, revenue),
    pivot to: rows = network, columns = day, values = sum(revenue).

    Returns a DataFrame with index = network names, columns = date strings.
    """
    if raw_df.empty:
        return pd.DataFrame()

    # Sum revenue per (day, network) — in case of duplicates
    grouped = raw_df.groupby(["day", "network"], as_index=False)["revenue"].sum()

    # Pivot: rows=network, columns=day, values=revenue
    pivot = grouped.pivot_table(
        index="network",
        columns="day",
        values="revenue",
        aggfunc="sum",
        fill_value=0.0,
    )

    # Sort columns (dates) and rows (network names)
    pivot = pivot.sort_index(axis=1)  # sort dates left to right
    pivot = pivot.sort_index(axis=0)  # sort network names A-Z

    return pivot


def main():
    date_from, date_to = get_date_range()
    print(f"Revenue by Ad Network: {date_from} → {date_to}")

    # 1. Fetch revenue data by ad network from MAX
    print("  Fetching MAX revenue by ad network...")
    raw = fetch_max_revenue_by_network(date_from, date_to)

    if raw.empty:
        print("  ⚠️  No revenue data returned.")
        return

    # 2. Pivot to [network x dates] format
    pivot = build_revenue_by_an_pivot(raw)

    if pivot.empty:
        print("  ⚠️  Pivot table is empty after processing.")
        return

    # Print to console
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)
    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
    print("\n" + pivot.to_string())

    # 3. Push to Google Sheets
    print(f"\n  Pushing to Google Sheets tab '{SHEET_TAB}'...")
    ws = get_worksheet(SHEET_TAB)
    update_pivot_table(ws, pivot)

    print("  Done!")


if __name__ == "__main__":
    main()