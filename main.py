"""
Forex P/L Calendar — Main Entry Point
Fetches daily/monthly statement emails from Gmail, parses P/L data,
and generates an HTML calendar dashboard.
"""

import json
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
OUTPUT_FILE  = Path("output/calendar.html")
ACCOUNTS_CFG = Path("config/accounts.json")

# How many months back to search
MONTHS_BACK = 60  # 5 years


# ── Account config ────────────────────────────────────────────────────────────

def load_account_config() -> dict:
    """
    Returns {account: {broker, active, label}} from config/accounts.json.
    If the file doesn't exist, returns an empty dict (all accounts treated as active).
    """
    if not ACCOUNTS_CFG.exists():
        return {}
    with open(ACCOUNTS_CFG) as f:
        data = json.load(f)
    return data.get("accounts", {})


def active_accounts(cfg: dict) -> set[str]:
    """Return set of account numbers with active=true."""
    if not cfg:
        return set()  # empty = no filter applied
    return {acct for acct, info in cfg.items() if info.get("active", False)}


def print_account_summary(cfg: dict):
    if not cfg:
        return
    active = [a for a, v in cfg.items() if v.get("active")]
    inactive = [a for a, v in cfg.items() if not v.get("active")]
    print(f"\nAccount config loaded ({ACCOUNTS_CFG}):")
    for a in active:
        label = cfg[a].get("label", "")
        note  = f"  [{label}]" if label else ""
        print(f"  [ACTIVE]   {cfg[a]['broker']} #{a}{note}")
    print(f"  [inactive] {len(inactive)} account(s) — email fetch skipped")


# ── Cache ─────────────────────────────────────────────────────────────────────

def load_cached_records() -> list[DailyRecord]:
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE, "r") as f:
        raw = json.load(f)
    records = []
    for item in raw:
        dw = item.get("deposit_withdrawal", 0.0)
        records.append(DailyRecord(
            broker=item["broker"],
            account=item["account"],
            date=date.fromisoformat(item["date"]),
            closed_pl=item["closed_pl"],
            deposit_withdrawal=dw,
            balance=item["balance"],
            equity=item["equity"],
            floating_pl=item.get("floating_pl", 0.0),
            statement_type=item.get("statement_type", "daily"),
            deposit=item.get("deposit", max(0.0, dw)),
            withdrawal=item.get("withdrawal", min(0.0, dw)),
        ))
    return records


def save_records(records: list[DailyRecord]):
    DATA_FILE.parent.mkdir(exist_ok=True)
    data = [
        {
            "broker": r.broker,
            "account": r.account,
            "date": r.date.isoformat(),
            "closed_pl": r.closed_pl,
            "deposit_withdrawal": r.deposit_withdrawal,
            "deposit": r.deposit,
            "withdrawal": r.withdrawal,
            "balance": r.balance,
            "equity": r.equity,
            "floating_pl": r.floating_pl,
            "statement_type": r.statement_type,
        }
        for r in records
    ]
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Deduplication ─────────────────────────────────────────────────────────────

def deduplicate(mt5_records: list[DailyRecord],
                csv_records: list[DailyRecord],
                email_records: list[DailyRecord]) -> list[DailyRecord]:
    """
    Priority order (highest wins): MT5 > Myfxbook CSV > Email.
    MT5 is direct from broker server — always authoritative.
    CSV fills dates not in MT5. Email fills dates not in either local file.
    Within each tier, higher |closed_pl| wins.
    MT5 preserves dep/wd from CSV when MT5 has none (MT5 files never include dep/wd).
    """
    seen: dict[tuple, DailyRecord] = {}

    # Tier 3 — email (lowest priority)
    for r in email_records:
        key = (r.broker, r.account, r.date.isoformat())
        if key not in seen or abs(r.closed_pl) > abs(seen[key].closed_pl):
            seen[key] = r

    # Tier 2 — Myfxbook CSV overrides email
    csv_seen: dict[tuple, DailyRecord] = {}
    for r in csv_records:
        key = (r.broker, r.account, r.date.isoformat())
        if key not in csv_seen or abs(r.closed_pl) > abs(csv_seen[key].closed_pl):
            csv_seen[key] = r
    seen.update(csv_seen)

    # Tier 1 — MT5 always wins for P/L; carry dep/wd from CSV when MT5 has none
    for r in mt5_records:
        key = (r.broker, r.account, r.date.isoformat())
        existing = seen.get(key)
        if existing and r.deposit == 0.0 and r.withdrawal == 0.0 and (existing.deposit != 0.0 or existing.withdrawal != 0.0):
            from dataclasses import replace as dc_replace
            seen[key] = dc_replace(r,
                deposit=existing.deposit,
                withdrawal=existing.withdrawal,
                deposit_withdrawal=existing.deposit_withdrawal)
        else:
            seen[key] = r

    return sorted(seen.values(), key=lambda r: r.date)


# ── Email fetch ───────────────────────────────────────────────────────────────

def fetch_new_records(existing: list[DailyRecord],
                      active_accts: set[str]) -> list[DailyRecord]:
    """
    Fetch new email records from Gmail.
    Only saves records whose account number is in active_accts.
    If active_accts is empty (no config), fetches all accounts.
    """
    print("Connecting to Gmail...")
    service = get_gmail_service()
    existing_keys = {(r.broker, r.account, r.date.isoformat()) for r in existing}

    new_records: list[DailyRecord] = []
    months_query = f"newer_than:{MONTHS_BACK}m"

    for parser in ALL_PARSERS:
        query = f"{parser.gmail_query} {months_query}"
        print(f"\n[{parser.broker_name}] Searching: {query}")
        messages = search_emails(service, query, max_results=5000)
        print(f"  Found {len(messages)} emails")

        fetched = skipped = 0
        for msg in messages:
            try:
                subject, date_header, html_body, plain_body = get_email_body(service, msg["id"])
                record = parser.parse(subject, date_header, html_body, plain_body)
                if record is None:
                    continue

                # Skip inactive accounts (when config is present)
                if active_accts and record.account not in active_accts:
                    skipped += 1
                    continue

                key = (record.broker, record.account, record.date.isoformat())
                if key in existing_keys:
                    continue  # already cached
                new_records.append(record)
                existing_keys.add(key)
                fetched += 1
                print(f"  + {record.date} | {record.broker} #{record.account} | P/L: ${record.closed_pl:+.2f}")
            except Exception as e:
                print(f"  ! Error parsing msg {msg['id']}: {e}")

        if skipped:
            print(f"  Skipped {skipped} emails from inactive accounts")

    return new_records


# ── Main ──────────────────────────────────────────────────────────────────────

def main(refresh: bool = False):
    print("=" * 50)
    print("  Forex P/L Calendar")
    print("=" * 50)

    # Load account config
    cfg          = load_account_config()
    active_accts = active_accounts(cfg)
    print_account_summary(cfg)

    # Load cache
    cached = load_cached_records()
    print(f"\nLoaded {len(cached)} cached records from {DATA_FILE}")

    # Local history files are always re-read (fast, no network needed)
    print("\nLoading MT5 history files from history/ ...")
    mt5_records = load_mt5_history()
    print(f"  {len(mt5_records)} MT5 day-records loaded")

    print("\nLoading Myfxbook CSV files from history/ ...")
    myfxbook_records = load_myfxbook_csv()
    print(f"  {len(myfxbook_records)} Myfxbook day-records loaded")

    # Email records only go into the cache — local file records are always re-read fresh
    if refresh or not cached:
        new = fetch_new_records(cached, active_accts)
        email_records_deduped = deduplicate([], [], cached + new)
        save_records(email_records_deduped)
        print(f"\nSaved {len(email_records_deduped)} email records to {DATA_FILE}")
        email_records = email_records_deduped
    else:
        email_records = cached
        print("Using cached email data. Run with --refresh to re-fetch emails.")

    # Merge: MT5 > Myfxbook CSV > Email
    all_records = deduplicate(mt5_records, myfxbook_records, email_records)

    if not all_records:
        print("\nNo records found. Check your Gmail credentials and broker email queries.")
        sys.exit(1)

    # Generate calendar
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    print(f"\nGenerating calendar with {len(all_records)} records...")
    generate_calendar_html(all_records, str(OUTPUT_FILE), account_cfg=cfg)

    CHARTS_FILE = OUTPUT_FILE.parent / "charts.html"
    generate_charts_html(all_records, str(CHARTS_FILE))

    print(f"\nDone! Open this file in your browser:")
    print(f"  {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    refresh_flag = "--refresh" in sys.argv or "-r" in sys.argv
    main(refresh=refresh_flag)
