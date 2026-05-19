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
    # Col 18 = commission
    # Col 19 = swap
    # Col 20 = profit     (may use space as thousands sep: "6 591.00")
    # Files with no closed trades have only 15 columns — skip gracefully.

    if df.shape[1] < 21:
        return []  # no closed-position columns present

    has_swap = df.shape[1] >= 20

    DATE_PAT = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})")
    by_date: dict[date, float] = {}

    def _to_float(val: str) -> float:
        clean = str(val).replace(" ", "").replace(",", "")
        try:
            return float(clean)
        except ValueError:
            return 0.0

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

        profit = _to_float(profit_str)
        if profit == 0.0 and profit_str.strip() in ("", "nan"):
            continue

        # Include swap (col 19) in daily P/L
        swap = _to_float(str(row.iloc[19])) if has_swap else 0.0

        total = profit + swap

        if is_cent:
            total /= 100.0

        by_date[close_date] = round(by_date.get(close_date, 0.0) + total, 2)

    # ── Balance / Deposit / Withdrawal rows (Deals section) ─────────────────
    dw_by_date: dict[date, tuple[float, float]] = {}   # date -> (dep, wd)
    deals_start = None
    for i in range(len(df)):
        vals = [str(v) for v in df.iloc[i]]
        if "Deal" in vals and "Balance" in vals:
            deals_start = i
            break

    if deals_start is not None:
        for idx in range(deals_start + 1, len(df)):
            row       = df.iloc[idx]
            time_str  = str(row.iloc[0])
            type_str  = str(row.iloc[3]).lower().strip()
            if not DATE_PAT.match(time_str):
                continue
            if type_str != "balance":          # skip 'credit', 'buy', 'sell' etc.
                continue
            dm = DATE_PAT.match(time_str)
            try:
                d = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
            except ValueError:
                continue
            amt = _to_float(str(row.iloc[12]))
            if amt == 0.0:
                continue
            if is_cent:
                amt = round(amt / 100.0, 2)
            dep_cur, wd_cur = dw_by_date.get(d, (0.0, 0.0))
            if amt > 0:
                dw_by_date[d] = (round(dep_cur + amt, 2), wd_cur)
            else:
                dw_by_date[d] = (dep_cur, round(wd_cur + amt, 2))

    # ── Merge trades + dep/wd ────────────────────────────────────────────────
    all_dates = set(by_date.keys()) | set(dw_by_date.keys())
    result = []
    for d in sorted(all_dates):
        pl          = by_date.get(d, 0.0)
        dep, wd     = dw_by_date.get(d, (0.0, 0.0))
        dw          = round(dep + wd, 2)
        result.append(DailyRecord(
            broker             = broker,
            account            = account,
            date               = d,
            closed_pl          = pl,
            deposit_withdrawal = dw,
            deposit            = dep,
            withdrawal         = wd,
            balance            = 0.0,
            equity             = 0.0,
        ))
    return result
