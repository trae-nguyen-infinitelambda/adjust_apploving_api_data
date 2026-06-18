"""
Google Sheets helper for reading/writing report data.
Authenticates via GOOGLE_CREDENTIALS env var (JSON string) or local credentials.json file.
"""
import os
import json
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1RxUSB-W2gLSCLxUCSmN6l-Pgegb1kO9mcP8egHzT834"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_client():
    """Authenticate and return a gspread client."""
    creds_json = os.getenv("GOOGLE_CREDENTIALS")

    if creds_json:
        # From environment variable (GitHub Actions)
        creds_info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    else:
        # From local file
        creds_path = os.path.join(os.path.dirname(__file__), "credentials.json")
        if not os.path.exists(creds_path):
            raise FileNotFoundError(
                "No Google credentials found. Either set GOOGLE_CREDENTIALS env var "
                "or place a credentials.json file in the project directory."
            )
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)

    return gspread.authorize(creds)


def get_worksheet(tab_name):
    client = get_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    tab_name = tab_name.strip()

    sheets = [ws.title for ws in spreadsheet.worksheets()]
    print("Available sheets:", sheets)

    if tab_name not in sheets:
        raise ValueError(
            f"Worksheet '{tab_name}' not found or not accessible. "
            f"Make sure service account has access."
        )

    return spreadsheet.worksheet(tab_name)


def update_or_append_columns_incremental(worksheet, report_df):
    """
    Incremental update:
    - Update existing columns
    - Append new columns
    - Không rewrite toàn bộ sheet
    """

    metric_labels = report_df.index.tolist()
    new_periods = report_df.columns.tolist()

    # 1. Read header
    existing_data = worksheet.get_all_values()

    if not existing_data:
        # Sheet empty → write full
        header = ["Metric"] + new_periods
        rows = [header]

        for label in metric_labels:
            row = [label] + [
                round(float(report_df.loc[label, p]), 2)
                if p in report_df.columns else ""
                for p in new_periods
            ]
            rows.append(row)

        worksheet.update(rows)
        return

    header = existing_data[0]
    existing_periods = header[1:]

    # 2. Map period → column index
    period_to_col = {
        p: idx + 2  # +1 for 1-based, +1 for skipping Metric col
        for idx, p in enumerate(existing_periods)
    }

    # 3. Ensure metric rows match
    existing_metrics = [row[0] for row in existing_data[1:]]

    if existing_metrics != metric_labels:
        raise ValueError("Metric rows mismatch. Avoid incremental update.")

    # 4. Prepare batch updates
    updates = []

    for period in new_periods:
        col_values = []

        for label in metric_labels:
            val = report_df.loc[label, period]
            try:
                val = round(float(val), 2)
            except:
                val = 0
            col_values.append([val])  # column format

        if period in period_to_col:
            # 🔄 Update existing column
            col_idx = period_to_col[period]

            range_ = f"{gspread.utils.rowcol_to_a1(2, col_idx)}:{gspread.utils.rowcol_to_a1(len(metric_labels)+1, col_idx)}"

            updates.append({
                "range": range_,
                "values": col_values
            })

        else:
            # ➕ Append new column
            new_col_idx = len(existing_periods) + 2
            existing_periods.append(period)

            # update header
            worksheet.update_cell(1, new_col_idx, period)

            range_ = f"{gspread.utils.rowcol_to_a1(2, new_col_idx)}:{gspread.utils.rowcol_to_a1(len(metric_labels)+1, new_col_idx)}"

            updates.append({
                "range": range_,
                "values": col_values
            })

    # 5. Batch update (1 API call)
    if updates:
        worksheet.batch_update(updates)

    print(f"✅ Incremental update done: {len(new_periods)} periods")


def update_pivot_table(worksheet, pivot_df):
    """
    Update a pivot-shaped worksheet where rows are ad networks and columns are dates.

    - Row 1: header (date columns)
    - Column A: ad network names
    - Rest: revenue values

    First run: writes full table.
    Subsequent runs: adds new columns for new dates, updates existing ones.
    """
    networks = pivot_df.index.tolist()  # row labels (ad network names)
    dates = pivot_df.columns.tolist()    # column headers (date strings)

    existing_data = worksheet.get_all_values()

    if not existing_data:
        # Empty sheet — write everything
        header = ["Ad Network"] + dates
        rows = [header]

        for network in networks:
            row = [network] + [
                round(float(pivot_df.loc[network, d]), 2)
                if d in pivot_df.columns else 0.0
                for d in dates
            ]
            rows.append(row)

        worksheet.update(rows)
        return

    # Parse existing header (row 1)
    existing_header = existing_data[0]
    existing_dates = existing_header[1:]  # skip "Ad Network" cell

    # Map existing network names to their row indices (1-based, 2 = first data row)
    existing_networks = [row[0] for row in existing_data[1:]]
    network_to_row = {name: idx + 2 for idx, name in enumerate(existing_networks)}

    # Build batch updates
    updates = []
    header_updates = []  # separate header updates to avoid mixing with data

    for date in dates:
        col_idx = None

        if date in existing_dates:
            # ✓ Date column already exists — find its index
            col_idx = existing_dates.index(date) + 2  # +1 for 1-based, +1 for col A
        else:
            # ➕ New date column — append after the last existing date
            col_idx = len(existing_dates) + 2
            existing_dates.append(date)
            header_updates.append((1, col_idx, date))

        # Update each network row for this date column
        for network in networks:
            val = pivot_df.loc[network, date]
            try:
                val = round(float(val), 2)
            except (ValueError, TypeError):
                val = 0.0

            row_idx = network_to_row.get(network)
            if row_idx is None:
                # New network — will be added in a second pass
                continue

            cell_range = gspread.utils.rowcol_to_a1(row_idx, col_idx)
            updates.append({
                "range": cell_range,
                "values": [[val]]
            })

    # Apply header updates first
    for (row, col, val) in header_updates:
        worksheet.update_cell(row, col, val)

    # Apply data updates
    if updates:
        worksheet.batch_update(updates)

    # ── Check for new networks not yet in the sheet ──
    new_networks = [n for n in networks if n not in existing_networks]
    if new_networks:
        # Append rows at the bottom
        start_row = len(existing_data) + 1
        rows_to_add = []

        for network in new_networks:
            row = [network] + [
                round(float(pivot_df.loc[network, d]), 2)
                if d in pivot_df.columns else 0.0
                for d in existing_dates
            ]
            rows_to_add.append(row)

        range_start = gspread.utils.rowcol_to_a1(start_row, 1)
        range_end = gspread.utils.rowcol_to_a1(start_row + len(rows_to_add) - 1, len(existing_dates) + 1)
        worksheet.update(f"{range_start}:{range_end}", rows_to_add)

    print(f"✅ Pivot table updated: {len(dates)} date columns, {len(updates)} cell updates")
