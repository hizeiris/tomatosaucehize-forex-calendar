"""
MT5 History Parser — reads ReportHistory-*.html files from the history/ folder.
Each file is one account's full trade history exported from MetaTrader 5.
Trades are grouped by close date; profits summed per day.
Cent accounts (USC) are converted from cents to USD.
"""

import re
import glob
from datetime import date
from pathlib import Path

import pandas as pd

from .base import DailyRecord


def load_mt5_history(history_dir: str = "history") -> list[DailyRecord]:
    files = (
        glob.glob(f"{history_dir}/*.html")
        + glob.glob(f"{history_dir}/*.xlsx")
    )
    if not files:
        return []

    all_records: list[DailyRecord] = []
    for fpath in files:
        try:
            recs = _parse_file(fpath)
            all_records.extend(recs)
            account = recs[0].account if recs else "?"
            print(f"  [MT5] {Path(fpath).name}  account={account}  {len(recs)} day(s)")
        except Exception as exc:
            print(f"  ! MT5 parse error {fpath}: {exc}")

    return all_records


def _parse_file(fpath: str) -> list[DailyRecord]:
    if fpath.endswith(".html"):
        df = pd.read_html(fpath, header=None)[0]
    else:
        df = pd.read_excel(fpath, header=None)

    # ── Metadata (rows 0-4) ──────────────────────────────────────────────
    account_str = str(df.iloc[2, 4]).replace("\xa0", " ")
    company_str = str(df.iloc[3, 4]).replace("\xa0", " ")

    # Account number (first run of digits)
    acct_m = re.match(r"(\d+)", account_str)
    account = acct_m.group(1) if acct_m else "unknown"

    # Cent account? "USC" in the account cell
    is_cent = "USC" in account_str

    # Broker: first word of company name
    broker = company_str.split()[0] if company_str.lower() != "nan" else "MT5"

    # ── Trade rows start at row 8 ────────────────────────────────────────
    # Col 0  = open time  (YYYY.MM.DD HH:MM:SS)
    # Col 16 = close time (YYYY.MM.DD HH:MM:SS)
    # Col 20 = profit     (may use space as thousands sep: "6 591.00")
    # Files with no closed trades have only 15 columns — skip gracefully.

    if df.shape[1] < 21:
        return []  # no closed-position columns present

    DATE_PAT = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})")
    by_date: dict[date, float] = {}

    for idx in range(8, len(df)):
        row = df.iloc[idx]
        open_time  = str(row.iloc[0])
        close_time = str(row.iloc[16])
        profit_str = str(row.iloc[20])

        # Skip summary / stats rows at the bottom of the report
        if not DATE_PAT.match(open_time):
            continue

        dm = DATE_PAT.match(close_time)
        if not dm:
            continue

        try:
            close_date = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        except ValueError:
            continue

        # "6 591.00" → 6591.0,  "nan" or "" → skip
        profit_clean = profit_str.replace(" ", "").replace(",", "")
        try:
            profit = float(profit_clean)
        except ValueError:
            continue

        if is_cent:
            profit /= 100.0

        by_date[close_date] = round(by_date.get(close_date, 0.0) + profit, 2)

    return [
        DailyRecord(
            broker=broker,
            account=account,
            date=d,
            closed_pl=pl,
            deposit_withdrawal=0.0,
            balance=0.0,
            equity=0.0,
        )
        for d, pl in sorted(by_date.items())
    ]
