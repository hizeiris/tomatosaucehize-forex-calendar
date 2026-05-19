"""
Myfxbook CSV Statement Parser.
Reads files matching history/statement*.csv (e.g. "statement - 1447393.csv").
Account number is extracted from the filename.
Trades are grouped by close date; deposits/withdrawals are skipped.
"""

import re
import csv
import glob
from datetime import date, datetime
from pathlib import Path

from .base import DailyRecord

DEFAULT_BROKER = "Vantage"


def _get_usc_accounts(history_dir: str) -> set[str]:
    """Return set of account numbers that use USC (cents) by reading MT5 HTML files."""
    import pandas as pd
    usc: set[str] = set()
    for fpath in glob.glob(f"{history_dir}/ReportHistory*.html") + glob.glob(f"{history_dir}/ReportHistory*.xlsx"):
        try:
            df = pd.read_html(fpath, header=None)[0] if fpath.endswith(".html") else pd.read_excel(fpath, header=None)
            account_str = str(df.iloc[2, 4]).replace("\xa0", " ")
            if "USC" in account_str:
                m = re.match(r"(\d+)", account_str)
                if m:
                    usc.add(m.group(1))
        except Exception:
            pass
    return usc


def _get_account_brokers(history_dir: str) -> dict[str, str]:
    """Return {account_number: broker_name} from MT5 HTML files."""
    import pandas as pd
    mapping: dict[str, str] = {}
    for fpath in glob.glob(f"{history_dir}/ReportHistory*.html") + glob.glob(f"{history_dir}/ReportHistory*.xlsx"):
        try:
            df = pd.read_html(fpath, header=None)[0] if fpath.endswith(".html") else pd.read_excel(fpath, header=None)
            account_str = str(df.iloc[2, 4]).replace("\xa0", " ")
            company_str = str(df.iloc[3, 4]).replace("\xa0", " ")
            acct_m = re.match(r"(\d+)", account_str)
            if acct_m and company_str.lower() != "nan":
                account = acct_m.group(1)
                broker = company_str.split()[0]
                mapping[account] = broker
        except Exception:
            pass
    return mapping


def load_myfxbook_csv(history_dir: str = "history") -> list[DailyRecord]:
    files = glob.glob(f"{history_dir}/statement*.csv")
    if not files:
        return []

    usc_accounts = _get_usc_accounts(history_dir)
    account_brokers = _get_account_brokers(history_dir)

    all_records: list[DailyRecord] = []
    for fpath in files:
        try:
            recs = _parse_file(fpath, usc_accounts, account_brokers)
            all_records.extend(recs)
            account = recs[0].account if recs else "?"
            print(f"  [Myfxbook CSV] {Path(fpath).name}  account={account}  {len(recs)} day(s)")
        except Exception as exc:
            print(f"  ! Myfxbook CSV parse error {fpath}: {exc}")

    return all_records


def _parse_file(fpath: str, usc_accounts: set[str] | None = None,
                account_brokers: dict[str, str] | None = None) -> list[DailyRecord]:
    # Extract account number from filename: "statement - 1447393.csv" → "1447393"
    stem = Path(fpath).stem  # e.g. "statement - 1447393"
    acct_m = re.search(r"(\d+)", stem)
    account = acct_m.group(1) if acct_m else "unknown"
    is_cent = usc_accounts is not None and account in usc_accounts
    broker = (account_brokers or {}).get(account, DEFAULT_BROKER)

    by_pl:  dict[date, float] = {}
    by_dep: dict[date, float] = {}  # broker → account (positive)
    by_wd:  dict[date, float] = {}  # account → broker (negative)

    with open(fpath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            action = (row.get("Action") or "").strip().lower()

            if action in ("", "action"):
                continue

            profit_str = (row.get("Profit") or "").strip()
            if not profit_str:
                continue

            try:
                amount = float(profit_str)
            except ValueError:
                continue

            if is_cent:
                amount /= 100.0

            if action in ("deposit", "withdrawal"):
                # Skip rebate transfers from the internal rebate account (143041)
                comment = (row.get("Comment") or "").strip()
                if "143041" in comment:
                    continue

                # Use open date for deposits/withdrawals (no close date)
                date_str = (row.get("Open Date") or "").strip()
                try:
                    d = datetime.strptime(date_str[:10], "%d/%m/%Y").date()
                except ValueError:
                    continue
                if action == "deposit":
                    by_dep[d] = round(by_dep.get(d, 0.0) + amount, 2)
                else:
                    by_wd[d] = round(by_wd.get(d, 0.0) + amount, 2)
            else:
                # Trade — use close date
                close_date_str = (row.get("Close Date") or "").strip()
                if not close_date_str:
                    continue
                try:
                    d = datetime.strptime(close_date_str[:10], "%d/%m/%Y").date()
                except ValueError:
                    continue
                by_pl[d] = round(by_pl.get(d, 0.0) + amount, 2)

    # Merge: all dates that have trades or deposits/withdrawals
    all_dates = sorted(set(by_pl) | set(by_dep) | set(by_wd))
    return [
        DailyRecord(
            broker=broker,
            account=account,
            date=d,
            closed_pl=by_pl.get(d, 0.0),
            deposit=by_dep.get(d, 0.0),
            withdrawal=by_wd.get(d, 0.0),
            deposit_withdrawal=round(by_dep.get(d, 0.0) + by_wd.get(d, 0.0), 2),
            balance=0.0,
            equity=0.0,
        )
        for d in all_dates
    ]
