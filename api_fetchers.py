"""
Shared API fetching logic for Adjust and AppLovin MAX APIs.
Used by both weekly (main.py) and daily (daily_report.py) reports.
"""
import os
import requests
import pandas as pd

# =========================
# CONFIG
# =========================
ADJUST_API_TOKEN = os.getenv("ADJUST_API_TOKEN")
APP_TOKEN = os.getenv("ADJUST_APP_TOKEN")
MAX_API_KEY = os.getenv("MAX_API_KEY")

# Adjust metrics to pull (discovered via filters_data endpoint)
ADJUST_METRICS = ",".join([
    "installs", "cost", "all_revenue", "gross_profit",
    "ecpi_all", "ecpi", "daus",
    "roas_d0", "roas_d1", "roas_d7",
    "time_spent_d0", "time_spent_d1", "time_spent_d7",
    "time_spent_per_user_d0", "time_spent_per_user_d1", "time_spent_per_user_d7",
])

METRIC_KEYS = [
    "installs", "cost", "all_revenue", "gross_profit",
    "ecpi_all", "ecpi", "daus",
    "roas_d0", "roas_d1", "roas_d7",
    "time_spent_d0", "time_spent_d1", "time_spent_d7",
    "time_spent_per_user_d0", "time_spent_per_user_d1", "time_spent_per_user_d7",
]

# Display metric names (row labels in the final table)
METRIC_LABELS = [
    "Revenue", "Spend", "Gross Profit",
    "Installs", "eCPI (all)", "eCPI (paid)",
    "DAUs",
    "ROAS D0", "ROAS D1", "ROAS D7",
    "Time Spent D0", "Time Spent D1", "Time Spent D7",
    "Time/User D0", "Time/User D1", "Time/User D7",
    "Impr. INTER", "Impr. BANNER", "Impr. REWARD", "Impr. Total",
    "ImpDAU Total", "ImpDAU INTER", "ImpDAU BANNER", "ImpDAU REWARD",
]


# =========================
# ADJUST API
# =========================
def fetch_adjust(date_from, date_to, dimension="week"):
    """
    Fetch data from Adjust Pivot Report API.
    dimension: "week" or "day"
    """
    url = "https://automate.adjust.com/reports-service/pivot_report"

    params = {
        "app_token__in": APP_TOKEN,
        "dimensions": dimension,
        "metrics": ADJUST_METRICS,
        "date_period": f"{date_from}:{date_to}",
        "ad_spend_mode": "network",
        "format_dates": "true",
        "index": dimension,
        "cohort_maturity": "immature"
    }

    headers = {
        "Authorization": f"Bearer {ADJUST_API_TOKEN}"
    }

    res = requests.get(url, params=params, headers=headers)
    data = res.json()

    rows = []
    for item in data.get("rows", []):
        for period_key, val in item.items():
            row = {"period": period_key}
            for metric in METRIC_KEYS:
                row[metric] = float(val.get(metric, 0))
            rows.append(row)

    df = pd.DataFrame(rows)

    if df.empty:
        print(f"Adjust API returned no rows. Response data:", data)
        return pd.DataFrame()

    df = df.groupby("period", as_index=False).sum()
    return df


# =========================
# MAX IMPRESSIONS API
# =========================
def fetch_max_impressions(date_from, date_to):
    """
    Fetch impressions by ad_format from AppLovin MAX Report API.
    Returns daily-level data with columns: day, ad_format, impressions
    """
    url = "https://r.applovin.com/maxReport"

    params = {
        "api_key": MAX_API_KEY,
        "start": date_from,
        "end": date_to,
        "columns": "day,ad_format,impressions",
        "format": "csv"
    }

    res = requests.get(url, params=params)

    df = pd.read_csv(pd.io.common.StringIO(res.text))
    df.columns = df.columns.str.lower().str.strip()

    if "day" not in df.columns or "ad_format" not in df.columns:
        print("Max Report API error. Response:", res.text[:200])
        return pd.DataFrame()

    df["impressions"] = pd.to_numeric(df["impressions"], errors="coerce").fillna(0).astype(int)
    return df


def aggregate_max_impressions_weekly(df):
    """Aggregate daily MAX impressions data into weekly totals."""
    if df.empty:
        return pd.DataFrame(columns=["period", "impressions_inter", "impressions_banner",
                                     "impressions_reward", "impressions_total", "days_in_week"])

    df = df.copy()
    df["period"] = pd.to_datetime(df["day"]).dt.to_period("W").astype(str).str.replace("/", " - ")

    days_per_week = df.groupby("period")["day"].nunique().reset_index()
    days_per_week.rename(columns={"day": "days_in_week"}, inplace=True)

    pivot = df.pivot_table(index="period", columns="ad_format", values="impressions", aggfunc="sum", fill_value=0)
    pivot = pivot.reset_index()

    result = pd.DataFrame({"period": pivot["period"]})
    result["impressions_inter"] = pivot.get("INTER", 0)
    result["impressions_banner"] = pivot.get("BANNER", 0)
    result["impressions_reward"] = pivot.get("REWARD", 0)
    result["impressions_total"] = result["impressions_inter"] + result["impressions_banner"] + result["impressions_reward"]

    result = result.merge(days_per_week, on="period", how="left")
    result["days_in_week"] = result["days_in_week"].fillna(7).astype(int)

    return result


def aggregate_max_impressions_daily(df):
    """Aggregate daily MAX impressions data per day (pivot ad_format)."""
    if df.empty:
        return pd.DataFrame(columns=["period", "impressions_inter", "impressions_banner",
                                     "impressions_reward", "impressions_total"])

    df = df.copy()
    df["period"] = df["day"]

    pivot = df.pivot_table(index="period", columns="ad_format", values="impressions", aggfunc="sum", fill_value=0)
    pivot = pivot.reset_index()

    result = pd.DataFrame({"period": pivot["period"]})
    result["impressions_inter"] = pivot.get("INTER", 0)
    result["impressions_banner"] = pivot.get("BANNER", 0)
    result["impressions_reward"] = pivot.get("REWARD", 0)
    result["impressions_total"] = result["impressions_inter"] + result["impressions_banner"] + result["impressions_reward"]

    return result


# =========================
# MAX REVENUE REPORTING API
# =========================
def fetch_max_revenue_by_network(date_from, date_to):
    """
    Fetch daily revenue by ad network from AppLovin MAX Revenue Reporting API.
    Returns DataFrame with columns: day, network, revenue

    API reference: https://support.applovin.com/en/max/reporting-apis/revenue-reporting-api
    """
    url = "https://r.applovin.com/report"

    params = {
        "api_key": MAX_API_KEY,
        "start": date_from,
        "end": date_to,
        "columns": "day,network,revenue",
        "format": "csv",
    }

    res = requests.get(url, params=params)

    df = pd.read_csv(pd.io.common.StringIO(res.text))
    df.columns = df.columns.str.lower().str.strip()

    if "day" not in df.columns or "network" not in df.columns:
        print("MAX Revenue API error. Response:", res.text[:200])
        return pd.DataFrame()

    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").fillna(0.0)
    return df


# =========================
# TRANSFORM (shared logic)
# =========================
def build_report_table(adj_df, imp_df, is_weekly=True):
    """
    Merge Adjust + MAX data and compute ImpDAU metrics.
    Returns a DataFrame with metrics as rows and periods as columns.
    """
    if adj_df.empty:
        return pd.DataFrame()

    df = adj_df.copy()

    if not imp_df.empty:
        df = df.merge(imp_df, on="period", how="left")

    # Ensure impression columns exist
    for col in ["impressions_inter", "impressions_banner", "impressions_reward", "impressions_total"]:
        if col not in df.columns:
            df[col] = 0

    if is_weekly and "days_in_week" not in df.columns:
        df["days_in_week"] = 7

    df = df.fillna(0)
    df = df.sort_values("period")

    # Calculate ImpDAU
    safe_daus = df["daus"].replace(0, 1)

    if is_weekly:
        safe_days = df["days_in_week"].replace(0, 1)
        df["impdau_total"]  = (df["impressions_total"]  / safe_days) / safe_daus
        df["impdau_inter"]  = (df["impressions_inter"]  / safe_days) / safe_daus
        df["impdau_banner"] = (df["impressions_banner"] / safe_days) / safe_daus
        df["impdau_reward"] = (df["impressions_reward"] / safe_days) / safe_daus
    else:
        # Daily: impressions are already for 1 day
        df["impdau_total"]  = df["impressions_total"]  / safe_daus
        df["impdau_inter"]  = df["impressions_inter"]  / safe_daus
        df["impdau_banner"] = df["impressions_banner"] / safe_daus
        df["impdau_reward"] = df["impressions_reward"] / safe_daus

    # Build final display table
    metrics_map = {
        "Revenue":           df["all_revenue"].values,
        "Spend":             df["cost"].values,
        "Gross Profit":      df["gross_profit"].values,
        "Installs":          df["installs"].values,
        "eCPI (all)":        df["ecpi_all"].values,
        "eCPI (paid)":       df["ecpi"].values,
        "DAUs":              df["daus"].values,
        "ROAS D0":           df["roas_d0"].values,
        "ROAS D1":           df["roas_d1"].values,
        "ROAS D7":           df["roas_d7"].values,
        "Time Spent D0":     df["time_spent_d0"].values,
        "Time Spent D1":     df["time_spent_d1"].values,
        "Time Spent D7":     df["time_spent_d7"].values,
        "Time/User D0":      df["time_spent_per_user_d0"].values,
        "Time/User D1":      df["time_spent_per_user_d1"].values,
        "Time/User D7":      df["time_spent_per_user_d7"].values,
        "Impr. INTER":       df["impressions_inter"].values,
        "Impr. BANNER":      df["impressions_banner"].values,
        "Impr. REWARD":      df["impressions_reward"].values,
        "Impr. Total":       df["impressions_total"].values,
        "ImpDAU Total":      df["impdau_total"].values,
        "ImpDAU INTER":      df["impdau_inter"].values,
        "ImpDAU BANNER":     df["impdau_banner"].values,
        "ImpDAU REWARD":     df["impdau_reward"].values,
    }

    final_df = pd.DataFrame(metrics_map, index=df["period"].values).T
    return final_df
