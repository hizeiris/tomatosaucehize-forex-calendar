"""
Forex P/L Calendar — Main Entry Point

Two modes:
  LOCAL  (history/ files present) — reads MT5+CSV+email, saves frozen snapshot
  ACTIONS (no history/ files)     — loads frozen snapshot + fetches only new emails

Usage:
  py main.py               # use cached email data, regenerate calendar
  py main.py --refresh     # re-fetch emails from Gmail, regenerate calendar
  py main.py --freeze      # force-rebuild frozen snapshot from local files
"""

import json
import math
import os
import sys
from datetime import date, datetime
from pathlib import Path

from gmail_client import get_gmail_service, search_emails, get_email_body
from parsers import ALL_PARSERS
from parsers.base import DailyRecord
from parsers.mt5_history import load_mt5_history
from parsers.myfxbook_csv import load_myfxbook_csv
from calendar_generator import generate_calendar_html
from charts_generator import generate_charts_html

DATA_FILE    = Path("data/trades.json")
FROZEN_FILE  = Path("data/history_frozen.json")
OUTPUT_FILE  = Path("output/calendar.html")
ACCOUNTS_CFG = Path("config/accounts.json")

MONTHS_BACK         = 60   # full history search (local mode)
FREEZE_BUFFER_DAYS  = 14   # extra days buffer when fetching emails in Actions mode


# ── Account config ────────────────────────────────────────────────────────────

def load_account_config() -> dict:
    if not ACCOUNTS_CFG.exists():
        return {}
    with open(ACCOUNTS_CFG) as f:
        data = json.load(f)
    return data.get("accounts", {})


def active_accounts(cfg: dict) -> set[str]:
    if not cfg:
        return set()
    return {acct for acct, info in cfg.items() if info.get("active", False)}


def print_account_summary(cfg: dict):
    if not cfg:
        return
    active   = [a for a, v in cfg.items() if v.get("active")]
    inactive = [a for a, v in cfg.items() if not v.get("active")]
    print(f"\nAccount config loaded ({ACCOUNTS_CFG}):")
    for a in active:
        label = cfg[a].get("label", "")
        note  = f"  [{label}]" if label else ""
        print(f"  [ACTIVE]   {cfg[a]['broker']} #{a}{note}")
    print(f"  [inactive] {len(inactive)} account(s) — email fetch skipped")


# ── Email cache (data/trades.json) ────────────────────────────────────────────

def _records_from_list(raw: list) -> list[DailyRecord]:
    records = []
    for item in raw:
        dw  = item.get("deposit_withdrawal", 0.0)
        dep = item.get("deposit",    0.0)
        wd  = item.get("withdrawal", 0.0)
        # If deposit/withdrawal were saved as 0 but dw is non-zero, derive them
        if dep == 0.0 and wd == 0.0 and dw != 0.0:
            dep = max(0.0, dw)
            wd  = min(0.0, dw)
        records.append(DailyRecord(
            broker             = item["broker"],
            account            = item["account"],
            date               = date.fromisoformat(item["date"]),
            closed_pl          = item["closed_pl"],
            deposit_withdrawal = dw,
            balance            = item["balance"],
            equity             = item["equity"],
            floating_pl        = item.get("floating_pl", 0.0),
            statement_type     = item.get("statement_type", "daily"),
            deposit            = dep,
            withdrawal         = wd,
        ))
    return records


def _records_to_list(records: list[DailyRecord]) -> list:
    return [
        {
            "broker":              r.broker,
            "account":             r.account,
            "date":                r.date.isoformat(),
            "closed_pl":           r.closed_pl,
            "deposit_withdrawal":  r.deposit_withdrawal,
            "deposit":             r.deposit,
            "withdrawal":          r.withdrawal,
            "balance":             r.balance,
            "equity":              r.equity,
            "floating_pl":         r.floating_pl,
            "statement_type":      r.statement_type,
        }
        for r in records
    ]


def load_cached_records() -> list[DailyRecord]:
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE) as f:
        return _records_from_list(json.load(f))


def save_records(records: list[DailyRecord]):
    DATA_FILE.parent.mkdir(exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(_records_to_list(records), f, indent=2)


# ── Frozen snapshot (data/history_frozen.json) ────────────────────────────────

def load_frozen_records() -> list[DailyRecord]:
    if not FROZEN_FILE.exists():
        return []
    with open(FROZEN_FILE) as f:
        data = json.load(f)
    return _records_from_list(data.get("records", []))


def save_frozen_records(records: list[DailyRecord]):
    FROZEN_FILE.parent.mkdir(exist_ok=True)
    payload = {
        "frozen_date":   date.today().isoformat(),
        "record_count":  len(records),
        "records":       _records_to_list(records),
    }
    with open(FROZEN_FILE, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"  Frozen snapshot saved: {len(records)} records -> {FROZEN_FILE}")


def merge_frozen_with_email(frozen: list[DailyRecord],
                            email_records: list[DailyRecord]) -> list[DailyRecord]:
    """
    Frozen records are authoritative (from MT5+CSV).
    Email records fill only dates NOT already in frozen.
    """
    result = {(r.broker, r.account, r.date.isoformat()): r for r in frozen}
    for r in email_records:
        key = (r.broker, r.account, r.date.isoformat())
        if key not in result:
            result[key] = r
    return sorted(result.values(), key=lambda r: r.date)


# ── Deduplication ─────────────────────────────────────────────────────────────

def deduplicate(mt5_records: list[DailyRecord],
                csv_records: list[DailyRecord],
                email_records: list[DailyRecord]) -> list[DailyRecord]:
    """Priority: MT5 > CSV > Email. MT5 borrows dep/wd from CSV when missing."""
    seen: dict[tuple, DailyRecord] = {}

    for r in email_records:
        key = (r.broker, r.account, r.date.isoformat())
        if key not in seen or abs(r.closed_pl) > abs(seen[key].closed_pl):
            seen[key] = r

    csv_seen: dict[tuple, DailyRecord] = {}
    for r in csv_records:
        key = (r.broker, r.account, r.date.isoformat())
        if key not in csv_seen or abs(r.closed_pl) > abs(csv_seen[key].closed_pl):
            csv_seen[key] = r
    seen.update(csv_seen)

    for r in mt5_records:
        key = (r.broker, r.account, r.date.isoformat())
        existing = seen.get(key)
        if (existing and r.deposit == 0.0 and r.withdrawal == 0.0
                and (existing.deposit != 0.0 or existing.withdrawal != 0.0)):
            from dataclasses import replace as dc_replace
            seen[key] = dc_replace(r,
                deposit            = existing.deposit,
                withdrawal         = existing.withdrawal,
                deposit_withdrawal = existing.deposit_withdrawal)
        else:
            seen[key] = r

    return sorted(seen.values(), key=lambda r: r.date)


# ── Email fetch ───────────────────────────────────────────────────────────────

def fetch_new_records(existing: list[DailyRecord],
                      active_accts: set[str],
                      since_date: date = None) -> list[DailyRecord]:
    """
    Fetch email records from Gmail.
    since_date: if set, only search emails newer than this date (+ buffer).
    active_accts: only keep emails from these accounts (skip inactive).
    """
    print("Connecting to Gmail...")
    service = get_gmail_service()
    existing_keys = {(r.broker, r.account, r.date.isoformat()) for r in existing}

    # Determine search window
    if since_date:
        days_back    = (date.today() - since_date).days + FREEZE_BUFFER_DAYS
        months_back  = max(1, math.ceil(days_back / 30))
        months_query = f"newer_than:{months_back}m"
        print(f"\nActions mode: fetching emails newer than {since_date} "
              f"(~{months_back} month(s) back)")
    else:
        months_query = f"newer_than:{MONTHS_BACK}m"

    new_records: list[DailyRecord] = []

    for parser in ALL_PARSERS:
        query = f"{parser.gmail_query} {months_query}"
        print(f"\n[{parser.broker_name}] Searching: {query}")
        messages = search_emails(service, query, max_results=5000)
        print(f"  Found {len(messages)} emails")

        fetched = skipped = 0
        for msg in messages:
            try:
                subject, date_header, html_body, plain_body = get_email_body(
                    service, msg["id"])
                record = parser.parse(subject, date_header, html_body, plain_body)
                if record is None:
                    continue

                if active_accts and record.account not in active_accts:
                    skipped += 1
                    continue

                key = (record.broker, record.account, record.date.isoformat())
                if key in existing_keys:
                    continue
                new_records.append(record)
                existing_keys.add(key)
                fetched += 1
                print(f"  + {record.date} | {record.broker} #{record.account} "
                      f"| P/L: ${record.closed_pl:+.2f}")
            except Exception as e:
                print(f"  ! Error parsing msg {msg['id']}: {e}")

        if skipped:
            print(f"  Skipped {skipped} emails from inactive accounts")

    return new_records


# ── Main ──────────────────────────────────────────────────────────────────────

def main(refresh: bool = False, freeze: bool = False):
    print("=" * 50)
    print("  Forex P/L Calendar")
    print("=" * 50)

    cfg          = load_account_config()
    active_accts = active_accounts(cfg)
    print_account_summary(cfg)

    # ── Detect mode ───────────────────────────────────────────────────────────
    print("\nLoading MT5 history files from history/ ...")
    mt5_records = load_mt5_history()
    print(f"  {len(mt5_records)} MT5 day-records loaded")

    print("\nLoading Myfxbook CSV files from history/ ...")
    myfxbook_records = load_myfxbook_csv()
    print(f"  {len(myfxbook_records)} Myfxbook day-records loaded")

    has_local_data = len(mt5_records) > 0 or len(myfxbook_records) > 0

    # ── Load frozen snapshot ──────────────────────────────────────────────────
    frozen_records = load_frozen_records()
    if frozen_records:
        freeze_date = max(r.date for r in frozen_records)
        print(f"\nLoaded frozen snapshot: {len(frozen_records)} records "
              f"(up to {freeze_date})")
    else:
        freeze_date = None
        print("\nNo frozen snapshot found.")

    # ── Load email cache ──────────────────────────────────────────────────────
    cached = load_cached_records()
    print(f"Loaded {len(cached)} cached email records from {DATA_FILE}")

    # ── LOCAL MODE: has MT5/CSV files ─────────────────────────────────────────
    if has_local_data:
        print("\n[ LOCAL MODE — using MT5 + CSV + email ]")

        if refresh or freeze or not cached:
            new = fetch_new_records(cached, active_accts)
            email_records = deduplicate([], [], cached + new)
            save_records(email_records)
            print(f"\nSaved {len(email_records)} email records to {DATA_FILE}")
        else:
            email_records = cached
            print("Using cached email data. Run with --refresh to re-fetch.")

        all_records = deduplicate(mt5_records, myfxbook_records, email_records)

        # Auto-update frozen snapshot
        print("\nUpdating frozen snapshot...")
        save_frozen_records(all_records)

    # ── ACTIONS MODE: no local files, use frozen + new emails ─────────────────
    else:
        print("\n[ ACTIONS MODE — using frozen snapshot + new emails ]")

        if not frozen_records:
            print("\nERROR: No frozen snapshot and no local history files found.")
            print("Run locally first: py main.py --freeze")
            sys.exit(1)

        if refresh or not cached:
            new = fetch_new_records(cached, active_accts, since_date=freeze_date)
            email_records = deduplicate([], [], cached + new)
            save_records(email_records)
            print(f"\nSaved {len(email_records)} new email records to {DATA_FILE}")
        else:
            email_records = cached
            print("Using cached email data.")

        all_records = merge_frozen_with_email(frozen_records, email_records)
        print(f"\nMerged: {len(frozen_records)} frozen + "
              f"{len(email_records)} email = {len(all_records)} total records")

    if not all_records:
        print("\nNo records found.")
        sys.exit(1)

    # ── Generate output ───────────────────────────────────────────────────────
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    print(f"\nGenerating calendar with {len(all_records)} records...")
    generate_calendar_html(all_records, str(OUTPUT_FILE), account_cfg=cfg)

    CHARTS_FILE = OUTPUT_FILE.parent / "charts.html"
    generate_charts_html(all_records, str(CHARTS_FILE))

    # ── Sync docs/ (GitHub Pages) ─────────────────────────────────────────────
    import shutil
    docs_dir = Path("docs")
    if docs_dir.exists():
        shutil.copy(OUTPUT_FILE, docs_dir / "calendar.html")
        shutil.copy(CHARTS_FILE, docs_dir / "charts.html")
        print(f"  docs/ synced")

    print(f"\nDone! Open this file in your browser:")
    print(f"  {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    refresh_flag = "--refresh" in sys.argv or "-r" in sys.argv
    freeze_flag  = "--freeze"  in sys.argv or "-f" in sys.argv
    main(refresh=refresh_flag, freeze=freeze_flag)
