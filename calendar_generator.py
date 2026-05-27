import json
import calendar
from datetime import date, datetime
from collections import defaultdict
from typing import List, Dict
from parsers.base import DailyRecord

BROKER_COLORS = {
    "Vantage":   "#2563eb",
    "Hantec":    "#7c3aed",
    "AxiTrader": "#0891b2",
    "XM":        "#d97706",
}


def _broker_color(broker: str) -> str:
    return BROKER_COLORS.get(broker, "#666")


def _mask_acct(account: str) -> str:
    """Show only last 4 digits: 11501530 → ****1530"""
    if len(account) <= 4:
        return account
    return "****" + account[-4:]


def generate_calendar_html(records: List[DailyRecord], output_path: str = "output/calendar.html",
                           account_cfg: dict = None):
    if not records:
        print("No records to display.")
        return

    # Build days_data with per-broker, per-account breakdown
    day_map: Dict[date, List[DailyRecord]] = defaultdict(list)
    for r in records:
        day_map[r.date].append(r)

    all_dates = sorted(day_map.keys())
    brokers = sorted({r.broker for r in records})

    # broker -> sorted list of accounts
    broker_accounts: Dict[str, List[str]] = {}
    for b in brokers:
        accts = sorted({r.account for r in records if r.broker == b})
        broker_accounts[b] = accts

    days_data = {}
    for d, recs in day_map.items():
        total_pl  = sum(r.closed_pl for r in recs)
        total_dep = sum(r.deposit for r in recs)
        total_wd  = sum(r.withdrawal for r in recs)
        brokers_d = {}
        for r in recs:
            if r.broker not in brokers_d:
                brokers_d[r.broker] = {"pl": 0.0, "dep": 0.0, "wd": 0.0, "accounts": {}}
            brokers_d[r.broker]["pl"]  += r.closed_pl
            brokers_d[r.broker]["dep"] += r.deposit
            brokers_d[r.broker]["wd"]  += r.withdrawal
            brokers_d[r.broker]["accounts"][r.account] = {
                "pl": r.closed_pl,
                "dep": r.deposit,
                "wd": r.withdrawal,
                "balance": r.balance,
                "equity": r.equity,
            }
        days_data[d.isoformat()] = {
            "total": total_pl,
            "dep": round(total_dep, 2),
            "wd":  round(total_wd, 2),
            "brokers": brokers_d,
        }

    # Stats
    all_pl = [v["total"] for v in days_data.values()]
    total_pl_all = sum(all_pl)
    win_days  = sum(1 for p in all_pl if p > 0)
    loss_days = sum(1 for p in all_pl if p < 0)
    flat_days = sum(1 for p in all_pl if p == 0)
    best_day  = max(days_data.items(), key=lambda x: x[1]["total"]) if days_data else None
    worst_day = min(days_data.items(), key=lambda x: x[1]["total"]) if days_data else None
    win_rate  = (win_days / (win_days + loss_days) * 100) if (win_days + loss_days) > 0 else 0
    total_pl_class = "green" if total_pl_all >= 0 else "red"
    months_set = sorted({(d.year, d.month) for d in all_dates}, reverse=True)

    # Precompute sidebar snippets
    best_day_html = ""
    if best_day:
        best_day_html = (
            '<div class="stat-row"><span class="stat-label">Best Day</span>'
            f'<span class="stat-value green">${best_day[1]["total"]:+,.2f}'
            f'<br><small style="font-weight:normal;font-size:11px">{best_day[0]}</small></span></div>'
        )
    worst_day_html = ""
    if worst_day:
        worst_day_html = (
            '<div class="stat-row"><span class="stat-label">Worst Day</span>'
            f'<span class="stat-value red">${worst_day[1]["total"]:+,.2f}'
            f'<br><small style="font-weight:normal;font-size:11px">{worst_day[0]}</small></span></div>'
        )

    broker_stats_html = ""
    for b in brokers:
        b_total = sum(r.closed_pl for r in records if r.broker == b)
        b_class = "green" if b_total >= 0 else "red"
        color   = _broker_color(b)
        acct_rows = ""
        for a in broker_accounts[b]:
            a_recs  = [r for r in records if r.broker == b and r.account == a]
            a_total = sum(r.closed_pl  for r in a_recs)
            a_dep   = sum(r.deposit    for r in a_recs)
            a_wd    = sum(r.withdrawal for r in a_recs)
            a_net   = round(a_dep + a_wd, 2)
            a_class = "green" if a_total >= 0 else "red"
            has_dw  = a_dep != 0 or a_wd != 0

            # Dep/Wd sub-panel rows
            dw_panel = ""
            if a_dep != 0:
                dw_panel += (
                    f'<div class="acct-dw-row">'
                    f'<span style="color:var(--muted)">Dep</span>'
                    f'<span style="color:#ef4444">-${a_dep:,.2f}</span>'
                    f'</div>'
                )
            if a_wd != 0:
                dw_panel += (
                    f'<div class="acct-dw-row">'
                    f'<span style="color:var(--muted)">Wd</span>'
                    f'<span style="color:#60a5fa">+${abs(a_wd):,.2f}</span>'
                    f'</div>'
                )
            if a_dep != 0 and a_wd != 0:
                net_col = "#ef4444" if a_net > 0 else "#60a5fa"
                net_str = f'-${a_net:,.2f}' if a_net > 0 else f'+${abs(a_net):,.2f}'
                dw_panel += (
                    f'<div class="acct-dw-row" style="border-top:1px solid var(--border);margin-top:2px;padding-top:3px">'
                    f'<span style="color:var(--muted)">Net</span>'
                    f'<span style="color:{net_col}">{net_str}</span>'
                    f'</div>'
                )

            toggle_btn = (
                f'<span class="acct-dw-toggle" id="dw-arrow-{b}-{a}" '
                f'onclick="event.stopPropagation();toggleAcctDW(\'{b}\',\'{a}\')" '
                f'title="Dep / Wd">⊕</span>'
            ) if has_dw else ""

            # Auto-detect active/inactive: Green if Dep/Wd within last 30 days
            today = date.today()
            dw_dates = [r.date for r in a_recs if r.deposit != 0 or r.withdrawal != 0]
            if dw_dates:
                last_dw   = max(dw_dates)
                days_ago  = (today - last_dw).days
                dot_color = "#22c55e" if days_ago <= 60 else "#ef4444"
                dot_title = f"{'Active' if days_ago <= 60 else 'Inactive'} — last Dep/Wd: {last_dw} ({days_ago}d ago)"
            else:
                dot_color = "#ef4444"
                dot_title = "Inactive — no Dep/Wd found"
            status_dot = f'<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:{dot_color};margin-right:4px;vertical-align:middle" title="{dot_title}"></span>'

            acct_rows += (
                f'<div class="acct-row">'
                f'  <label class="acct-label" title="Show/hide on calendar">'
                f'    <input type="checkbox" class="acct-cb" data-broker="{b}" data-account="{a}" '
                f'           onchange="onAcctCheck(\'{b}\',\'{a}\',this.checked)" checked>'
                f'    <span class="stat-label" style="font-size:11px">{status_dot}#{_mask_acct(a)}{toggle_btn}</span>'
                f'  </label>'
                f'  <span class="stat-value {a_class}" style="font-size:12px">${a_total:+,.2f}</span>'
                f'</div>'
            )
            if has_dw:
                acct_rows += (
                    f'<div class="acct-dw-panel" id="dw-panel-{b}-{a}" style="display:none">'
                    f'{dw_panel}'
                    f'</div>'
                )

        broker_stats_html += (
            f'<div class="broker-group">'
            f'<div class="stat-row broker-toggle" onclick="toggleBrokerAccounts(\'{b}\')" style="cursor:pointer">'
            f'<span class="stat-label">'
            f'<span class="broker-dot" style="background:{color}"></span>{b}'
            f'<span class="toggle-arrow" id="arrow-{b}" style="margin-left:6px;font-size:10px;color:var(--muted)">▶</span>'
            f'</span>'
            f'<span class="stat-value {b_class}">${b_total:+,.2f}</span>'
            f'</div>'
            f'<div class="broker-accts" id="broker-accts-{b}" style="display:none">{acct_rows}</div>'
            f'</div>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Forex P/L Calendar</title>
<style>
  :root {{
    --bg:#0f172a;--surface:#1e293b;--border:#334155;
    --text:#f1f5f9;--muted:#94a3b8;
    --green:#22c55e;--red:#ef4444;--flat:#475569;
    --green-bg:#14532d;--red-bg:#7f1d1d;--flat-bg:#1e293b;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh}}
  .header{{background:var(--surface);border-bottom:1px solid var(--border);padding:20px 32px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}}
  .header h1{{font-size:22px;font-weight:700;letter-spacing:-.5px}}
  .header h1 span{{color:#22c55e}}
  .updated{{font-size:12px;color:var(--muted)}}
  .header-btns{{display:flex;gap:8px}}
  .header-btn{{background:transparent;border:1px solid var(--border);border-radius:8px;color:var(--muted);padding:7px 14px;font-size:13px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:6px}}
  .header-btn:hover{{border-color:var(--text);color:var(--text)}}
  .header-btn.active{{border-color:#22c55e;color:#22c55e}}
  .layout{{display:grid;grid-template-columns:270px 1fr;gap:24px;padding:24px 32px;max-width:1400px;margin:0 auto}}
  .sidebar{{display:flex;flex-direction:column;gap:16px}}
  .card{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px}}
  .card-title{{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:12px}}
  .stat-row{{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border)}}
  .stat-row:last-child{{border-bottom:none}}
  .stat-label{{font-size:13px;color:var(--muted)}}
  .stat-value{{font-size:14px;font-weight:600}}
  .green{{color:var(--green)}}.red{{color:var(--red)}}
  .broker-dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}}
  /* Broker account rows */
  .broker-group{{border-bottom:1px solid var(--border)}}
  .broker-group:last-child{{border-bottom:none}}
  .broker-toggle{{border-bottom:none!important;padding:6px 0}}
  .broker-toggle:hover{{background:rgba(255,255,255,.03);border-radius:6px}}
  .broker-accts{{background:rgba(0,0,0,.2);border-radius:6px;margin-bottom:4px;padding:2px 0}}
  .acct-row{{display:flex;justify-content:space-between;align-items:center;padding:4px 8px}}
  .acct-row:hover{{background:rgba(255,255,255,.04);border-radius:4px}}
  .acct-label{{display:flex;align-items:center;flex:1;cursor:pointer;gap:6px;min-width:0}}
  .acct-cb{{accent-color:#22c55e;cursor:pointer;flex-shrink:0}}
  .filter-btn{{flex:1;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:6px 8px;font-size:12px;cursor:pointer}}
  .filter-btn:hover{{border-color:#22c55e;color:#22c55e}}
  .acct-dw-toggle{{margin-left:5px;font-size:11px;color:var(--muted);cursor:pointer;user-select:none;vertical-align:middle}}
  .acct-dw-toggle:hover{{color:var(--text)}}
  .acct-dw-panel{{background:rgba(0,0,0,.25);border-radius:5px;margin:0 8px 4px 24px;padding:4px 8px}}
  .acct-dw-row{{display:flex;justify-content:space-between;font-size:11px;padding:2px 0}}
  /* Filter dropdowns */
  .filter-select{{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:8px 10px;font-size:13px;cursor:pointer;margin-bottom:8px;outline:none}}
  .filter-select:focus{{border-color:#22c55e}}
  .acct-select{{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:8px 10px;font-size:12px;cursor:pointer;outline:none}}
  .acct-select:focus{{border-color:#22c55e}}
  .acct-group{{margin-top:4px}}
  /* Calendar */
  .calendar-wrap{{display:flex;flex-direction:column;gap:32px}}
  .month-block{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px}}
  .month-title{{font-size:16px;font-weight:700;margin-bottom:8px;color:var(--text)}}
  .month-summary{{display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap}}
  .month-stat{{font-size:12px;color:var(--muted)}}
  .month-stat strong{{color:var(--text)}}
  .cal-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}}
  .day-header{{text-align:center;font-size:11px;font-weight:600;color:var(--muted);padding:4px 0;text-transform:uppercase}}
  .day-cell{{border-radius:8px;min-height:68px;padding:6px 8px;cursor:pointer;border:1px solid transparent;transition:all .15s;position:relative}}
  .day-cell:hover{{border-color:var(--muted);transform:scale(1.02);z-index:2}}
  .day-cell.profit{{background:var(--green-bg);border-color:#166534}}
  .day-cell.loss{{background:var(--red-bg);border-color:#991b1b}}
  .day-cell.flat{{background:var(--flat-bg);border-color:var(--border)}}
  .day-cell.empty{{background:transparent;border-color:transparent;cursor:default}}
  .day-cell.empty:hover{{transform:none}}
  .day-num{{font-size:11px;color:var(--muted);margin-bottom:4px}}
  .day-pl{{font-size:13px;font-weight:700}}
  .day-cell.profit .day-pl{{color:var(--green)}}
  .day-cell.loss .day-pl{{color:var(--red)}}
  .day-cell.flat .day-pl{{color:var(--flat)}}
  .day-brokers{{display:flex;flex-wrap:wrap;gap:2px;margin-top:3px}}
  .day-broker-dot{{width:6px;height:6px;border-radius:50%;display:inline-block}}
  .dep-icon{{position:absolute;right:5px;bottom:5px;font-size:11px;font-weight:800;color:#ef4444;background:rgba(239,68,68,.22);border-radius:3px;width:15px;height:15px;display:flex;align-items:center;justify-content:center;line-height:1;pointer-events:none}}
  .wd-icon{{position:absolute;right:5px;top:5px;font-size:11px;font-weight:800;color:#22c55e;background:rgba(34,197,94,.22);border-radius:3px;width:15px;height:15px;display:flex;align-items:center;justify-content:center;line-height:1;pointer-events:none}}
  /* Tooltip */
  .tooltip{{display:none;position:fixed;background:#1e293b;border:1px solid #334155;border-radius:10px;padding:12px 16px;z-index:1000;box-shadow:0 8px 32px rgba(0,0,0,.6);min-width:240px;pointer-events:none}}
  .tooltip.visible{{display:block}}
  .tooltip-date{{font-size:12px;color:var(--muted);margin-bottom:8px}}
  .tooltip-total{{font-size:18px;font-weight:700;margin-bottom:8px}}
  .tooltip-broker{{font-size:12px;padding:4px 0;border-top:1px solid var(--border)}}
  .tooltip-broker:first-of-type{{border-top:none}}
  .tooltip-acct{{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);padding:1px 0 1px 14px}}
  /* ── Mobile ──────────────────────────────────────────────────────────────── */
  .mobile-toggle{{
    display:none;width:calc(100% - 32px);margin:12px 16px 0;
    background:var(--surface);border:1px solid var(--border);border-radius:10px;
    color:var(--text);padding:12px 16px;font-size:14px;font-weight:600;
    text-align:left;cursor:pointer;align-items:center;justify-content:space-between;
  }}
  .mobile-toggle:active{{opacity:.8}}
  .tooltip-backdrop{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:999}}
  .tooltip-backdrop.visible{{display:block}}
  @media(max-width:768px){{
    .mobile-toggle{{display:flex}}
    .layout{{grid-template-columns:1fr;padding:12px 16px;gap:12px}}
    #sidebar{{display:none}}
    #sidebar.mobile-open{{display:flex}}
    .header{{padding:12px 16px;flex-wrap:wrap;gap:6px}}
    .header h1{{font-size:18px}}
    .updated{{width:100%;font-size:11px}}
    .month-block{{padding:12px 8px}}
    .month-title{{font-size:14px}}
    .month-stat{{font-size:11px}}
    .cal-grid{{gap:2px}}
    .day-cell{{min-height:50px;padding:4px 3px}}
    .day-num{{font-size:10px;margin-bottom:2px}}
    .day-pl{{font-size:10px}}
    .day-dw{{font-size:8px}}
    .day-brokers{{gap:1px;margin-top:1px}}
    .day-broker-dot{{width:5px;height:5px}}
    .day-header{{font-size:9px;padding:3px 0;letter-spacing:0}}
    .tooltip{{
      position:fixed!important;
      left:50%!important;top:50%!important;
      transform:translate(-50%,-50%)!important;
      width:calc(100vw - 40px)!important;max-width:320px;
      max-height:80vh;overflow-y:auto;z-index:1000;
      pointer-events:auto;
    }}
  }}
  @media(max-width:400px){{
    .layout{{padding:8px 10px}}
    .month-block{{padding:10px 6px}}
    .day-pl{{font-size:9px}}
    .cal-grid{{gap:1px}}
  }}
</style>
</head>
<body>
<div class="header">
  <h1>Forex P/L <span>Calendar</span></h1>
  <div class="header-btns">
    <button class="header-btn" id="viewToggle" onclick="toggleView()">💳 Dep/Wd</button>
    <a class="header-btn" href="charts.html">📊 Charts</a>
    <button class="header-btn" id="updateBtn" onclick="triggerUpdate()" title="Trigger GitHub Actions workflow directly">🔄 Update</button>
  </div>
  <span class="updated">Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
</div>

<button class="mobile-toggle" id="sidebarToggle" onclick="toggleSidebar()">
  Summary &amp; Stats <span id="sidebarArrow">▼</span>
</button>
<div class="layout">
  <aside class="sidebar" id="sidebar">
    <div class="card">
      <div class="card-title">Overall Summary</div>
      <div class="stat-row"><span class="stat-label">Total P/L</span>
        <span class="stat-value {total_pl_class}">${total_pl_all:+,.2f}</span></div>
      <div class="stat-row"><span class="stat-label">Win Days</span>
        <span class="stat-value green">{win_days}</span></div>
      <div class="stat-row"><span class="stat-label">Loss Days</span>
        <span class="stat-value red">{loss_days}</span></div>
      <div class="stat-row"><span class="stat-label">Flat Days</span>
        <span class="stat-value" style="color:var(--muted)">{flat_days}</span></div>
      <div class="stat-row"><span class="stat-label">Win Rate</span>
        <span class="stat-value">{win_rate:.0f}%</span></div>
      {best_day_html}
      {worst_day_html}
    </div>

    <div class="card">
      <div class="card-title">Brokers</div>
      {broker_stats_html}
    </div>

    <div class="card">
      <div class="card-title">Filter</div>
      <div style="font-size:11px;color:var(--muted);margin-bottom:8px">
        Check accounts in the Brokers list above to show/hide them.
      </div>
      <div style="display:flex;gap:6px">
        <button class="filter-btn" onclick="selectAllAccts(true)">Select All</button>
        <button class="filter-btn" onclick="selectAllAccts(false)">None</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Legend</div>
      <div style="display:flex;flex-direction:column;gap:8px;font-size:12px">
        <span><span style="display:inline-block;width:12px;height:12px;background:#14532d;border-radius:3px;margin-right:6px"></span>Profit day</span>
        <span><span style="display:inline-block;width:12px;height:12px;background:#7f1d1d;border-radius:3px;margin-right:6px"></span>Loss day</span>
        <span><span style="display:inline-block;width:12px;height:12px;background:#1e293b;border:1px solid #334155;border-radius:3px;margin-right:6px"></span>No trades</span>
      </div>
    </div>
  </aside>

  <main class="calendar-wrap" id="calendarMain">
"""

    day_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

    for year, month in months_set:
        cal = calendar.monthcalendar(year, month)
        month_name = date(year, month, 1).strftime("%B %Y")
        month_records = [r for r in records if r.date.year == year and r.date.month == month]
        month_total = sum(r.closed_pl for r in month_records)
        month_dep   = sum(r.deposit    for r in month_records)
        month_wd    = sum(r.withdrawal for r in month_records)
        month_net   = round(month_dep + month_wd, 2)
        prefix = f"{year:04d}-{month:02d}"
        month_wins   = sum(1 for d, v in days_data.items() if d.startswith(prefix) and v["total"] > 0)
        month_losses = sum(1 for d, v in days_data.items() if d.startswith(prefix) and v["total"] < 0)
        month_cls    = "green" if month_total >= 0 else "red"

        dw_parts = []
        if month_dep != 0:
            dw_parts.append(f'<span class="month-stat">Dep: <strong style="color:#ef4444">-${month_dep:,.2f}</strong></span>')
        if month_wd != 0:
            dw_parts.append(f'<span class="month-stat">Wd: <strong style="color:#60a5fa">+${abs(month_wd):,.2f}</strong></span>')
        if month_dep != 0 and month_wd != 0:
            if month_net > 0:
                net_cls, net_str = "#ef4444", f'-${month_net:,.2f}'
            else:
                net_cls, net_str = "#60a5fa", f'+${abs(month_net):,.2f}'
            dw_parts.append(f'<span class="month-stat">Net: <strong style="color:{net_cls}">{net_str}</strong></span>')
        dw_summary = "".join(dw_parts)

        html += (
            f'    <div class="month-block" data-month="{year}-{month:02d}">\n'
            f'      <div class="month-title">{month_name}</div>\n'
            f'      <div class="month-summary">'
            f'<span class="month-stat">Total: <strong class="{month_cls}">${month_total:+,.2f}</strong></span>'
            f'<span class="month-stat">Wins: <strong class="green">{month_wins}</strong></span>'
            f'<span class="month-stat">Losses: <strong class="red">{month_losses}</strong></span>'
            f'{dw_summary}'
            f'</div>\n'
            f'      <div class="cal-grid">\n'
        )

        for dn in day_names:
            html += f'        <div class="day-header">{dn}</div>\n'

        for week in cal:
            for day_num in week:
                if day_num == 0:
                    html += '        <div class="day-cell empty"></div>\n'
                else:
                    d   = date(year, month, day_num)
                    iso = d.isoformat()
                    if iso in days_data:
                        info    = days_data[iso]
                        total   = info["total"]
                        css     = "profit" if total > 0 else ("loss" if total < 0 else "flat")
                        dots    = "".join(
                            '<span class="day-broker-dot" style="background:' + _broker_color(b) + '" title="' + b + '"></span>'
                            for b, binfo in info["brokers"].items()
                            if binfo["pl"] != 0.0
                        )
                        dep      = info.get("dep", 0.0)
                        wd       = info.get("wd", 0.0)
                        dep_icon = f'<span class="dep-icon" title="Deposit: -${dep:,.2f}">↓</span>' if dep != 0 else ""
                        wd_icon  = f'<span class="wd-icon" title="Withdrawal: +${abs(wd):,.2f}">↑</span>' if wd != 0 else ""
                        html += (
                            f'        <div class="day-cell {css}" onclick="showTooltip(event,\'{iso}\')" data-date="{iso}" data-dep="{dep}" data-wd="{wd}">\n'
                            f'          <div class="day-num">{day_num}</div>\n'
                            f'          <div class="day-pl">${total:+,.2f}</div>\n'
                            f'          <div class="day-brokers">{dots}</div>\n'
                            f'          {dep_icon}{wd_icon}\n'
                            f'        </div>\n'
                        )
                    else:
                        html += (
                            f'        <div class="day-cell empty">'
                            f'<div class="day-num" style="color:#334155">{day_num}</div>'
                            f'</div>\n'
                        )

        html += "      </div>\n    </div>\n"

    html += f"""  </main>
</div>
<div class="tooltip" id="tooltip"></div>
<div class="tooltip-backdrop" id="tooltipBackdrop" onclick="closeTooltip()"></div>

<script>
const daysData = {json.dumps(days_data, default=str)};
const brokerColors = {json.dumps(BROKER_COLORS)};
const brokerAccounts = {json.dumps(broker_accounts)};

function maskAcct(a) {{
  return a.length <= 4 ? a : '****' + a.slice(-4);
}}

let selectedAccounts = new Set();   // keys: "broker|account"
let viewMode         = 'pl';        // 'pl' or 'dw'

// ── Account checkbox selection ──────────────────────────────────────────────
function acctKey(broker, account) {{ return broker + '|' + account; }}

function loadSelection() {{
  const saved = localStorage.getItem('selectedAccounts');
  if (saved) {{
    try {{ selectedAccounts = new Set(JSON.parse(saved)); }} catch(e) {{ selectedAccounts = new Set(); }}
  }} else {{
    // Default: all accounts checked
    document.querySelectorAll('.acct-cb').forEach(cb => {{
      selectedAccounts.add(acctKey(cb.dataset.broker, cb.dataset.account));
    }});
  }}
  // Apply state to checkboxes
  document.querySelectorAll('.acct-cb').forEach(cb => {{
    cb.checked = selectedAccounts.has(acctKey(cb.dataset.broker, cb.dataset.account));
  }});
}}

function saveSelection() {{
  localStorage.setItem('selectedAccounts', JSON.stringify([...selectedAccounts]));
}}

function onAcctCheck(broker, account, checked) {{
  const key = acctKey(broker, account);
  if (checked) selectedAccounts.add(key);
  else selectedAccounts.delete(key);
  saveSelection();
  updateCalendar();
}}

function selectAllAccts(checked) {{
  document.querySelectorAll('.acct-cb').forEach(cb => {{
    cb.checked = checked;
    const key = acctKey(cb.dataset.broker, cb.dataset.account);
    if (checked) selectedAccounts.add(key);
    else selectedAccounts.delete(key);
  }});
  saveSelection();
  updateCalendar();
}}

// ── View toggle (P/L ↔ Dep/Wd) ───────────────────────────────────────────────
function toggleView() {{
  viewMode = viewMode === 'pl' ? 'dw' : 'pl';
  const btn = document.getElementById('viewToggle');
  if (viewMode === 'dw') {{
    btn.textContent = '📊 P/L';
    btn.classList.add('active');
  }} else {{
    btn.textContent = '💳 Dep/Wd';
    btn.classList.remove('active');
  }}
  updateCalendar();
}}

// ── One-click trigger of GitHub Actions workflow ────────────────────────────
async function triggerUpdate() {{
  const btn = document.getElementById('updateBtn');
  const REPO = 'hizeiris/tomatosaucehize-forex-calendar';
  const WORKFLOW = 'update-calendar.yml';

  // Get token from localStorage (or prompt user to set it once)
  let token = localStorage.getItem('gh_pat');
  if (!token) {{
    token = prompt(
      'One-time setup: Paste your GitHub Personal Access Token\\n\\n' +
      'How to create one:\\n' +
      '1. github.com/settings/tokens → Generate new token (classic)\\n' +
      '2. Check the "workflow" scope only\\n' +
      '3. Copy and paste here\\n\\n' +
      'Token stays in YOUR browser only (localStorage).'
    );
    if (!token) return;
    localStorage.setItem('gh_pat', token.trim());
  }}

  btn.textContent = '⏳ Triggering...';
  btn.disabled = true;

  try {{
    const res = await fetch(`https://api.github.com/repos/${{REPO}}/actions/workflows/${{WORKFLOW}}/dispatches`, {{
      method: 'POST',
      headers: {{
        'Accept':        'application/vnd.github+json',
        'Authorization': `Bearer ${{token}}`,
        'X-GitHub-Api-Version': '2022-11-28',
      }},
      body: JSON.stringify({{ ref: 'main' }}),
    }});

    if (res.status === 204) {{
      btn.textContent = '✅ Started! Wait ~30s';
      setTimeout(() => {{ btn.textContent = '🔄 Update'; btn.disabled = false; }}, 4000);
      // Auto-reload after 45s to show fresh calendar
      setTimeout(() => location.reload(), 45000);
    }} else if (res.status === 401) {{
      localStorage.removeItem('gh_pat');
      btn.textContent = '❌ Bad token';
      alert('Invalid token. Clear and try again.');
      setTimeout(() => {{ btn.textContent = '🔄 Update'; btn.disabled = false; }}, 3000);
    }} else {{
      const err = await res.text();
      btn.textContent = '❌ Error';
      alert(`GitHub API error ${{res.status}}: ${{err}}`);
      setTimeout(() => {{ btn.textContent = '🔄 Update'; btn.disabled = false; }}, 3000);
    }}
  }} catch (e) {{
    btn.textContent = '❌ Network';
    alert('Network error: ' + e.message);
    setTimeout(() => {{ btn.textContent = '🔄 Update'; btn.disabled = false; }}, 3000);
  }}
}}

// ── Mobile sidebar toggle ────────────────────────────────────────────────────
function toggleSidebar() {{
  const s = document.getElementById('sidebar');
  const a = document.getElementById('sidebarArrow');
  const open = s.classList.toggle('mobile-open');
  a.textContent = open ? '▲' : '▼';
}}

// ── Tooltip close ────────────────────────────────────────────────────────────
function closeTooltip() {{
  document.getElementById('tooltip').classList.remove('visible');
  document.getElementById('tooltipBackdrop').classList.remove('visible');
}}

// ── Account Dep/Wd panel toggle ──────────────────────────────────────────────
function toggleAcctDW(broker, account) {{
  const panel = document.getElementById('dw-panel-' + broker + '-' + account);
  const arrow = document.getElementById('dw-arrow-' + broker + '-' + account);
  if (!panel) return;
  if (panel.style.display === 'none') {{
    panel.style.display = 'block';
    arrow.textContent = '⊖';
  }} else {{
    panel.style.display = 'none';
    arrow.textContent = '⊕';
  }}
}}

// ── Broker accounts toggle ───────────────────────────────────────────────────
function toggleBrokerAccounts(broker) {{
  const el    = document.getElementById('broker-accts-' + broker);
  const arrow = document.getElementById('arrow-' + broker);
  if (el.style.display === 'none') {{
    el.style.display = 'block';
    arrow.textContent = '▼';
  }} else {{
    el.style.display = 'none';
    arrow.textContent = '▶';
  }}
}}

// ── Calendar update — aggregates over only the checked accounts ─────────────
function aggregateForDay(d) {{
  let pl = 0, dep = 0, wd = 0, hasAny = false;
  for (const [broker, binfo] of Object.entries(d.brokers || {{}})) {{
    for (const [acct, ainfo] of Object.entries(binfo.accounts || {{}})) {{
      if (!selectedAccounts.has(acctKey(broker, acct))) continue;
      pl  += ainfo.pl  || 0;
      dep += ainfo.dep || 0;
      wd  += ainfo.wd  || 0;
      hasAny = true;
    }}
  }}
  return {{ pl: hasAny ? pl : null, dep, wd, hasAny }};
}}

function updateCalendar() {{
  document.querySelectorAll('.day-cell[data-date]').forEach(cell => {{
    const iso = cell.dataset.date;
    const d   = daysData[iso];
    if (!d) return;
    const plEl = cell.querySelector('.day-pl');

    const agg = aggregateForDay(d);

    if (viewMode === 'dw') {{
      // ── Dep/Wd mode ──────────────────────────────────────────────────────
      const dep = agg.dep, wd = agg.wd;
      if (dep !== 0 || wd !== 0) {{
        const net = dep + wd;
        plEl.textContent = (net > 0 ? '-$' : '+$') + Math.abs(net).toFixed(2);
        cell.className   = 'day-cell ' + (dep !== 0 && wd === 0 ? 'loss' : wd !== 0 && dep === 0 ? 'profit' : net > 0 ? 'loss' : 'profit');
      }} else {{
        plEl.textContent = '-';
        cell.className   = 'day-cell flat';
      }}
    }} else {{
      // ── P/L mode ─────────────────────────────────────────────────────────
      if (agg.pl === null) {{
        plEl.textContent = '-';
        cell.className   = 'day-cell flat';
      }} else {{
        const pl = agg.pl;
        plEl.textContent = '$' + (pl >= 0 ? '+' : '') + pl.toFixed(2);
        cell.className   = 'day-cell ' + (pl > 0 ? 'profit' : pl < 0 ? 'loss' : 'flat');
      }}
    }}
  }});
}}

// ── Tooltip ──────────────────────────────────────────────────────────────────
function showTooltip(e, iso) {{
  const d = daysData[iso];
  if (!d) return;
  const tip  = document.getElementById('tooltip');
  const dt   = new Date(iso + 'T00:00:00');
  const label = dt.toLocaleDateString('en-US', {{weekday:'long', year:'numeric', month:'long', day:'numeric'}});

  let html = '<div class="tooltip-date">' + label + '</div>';
  const tc = d.total >= 0 ? 'green' : 'red';
  const ts = d.total >= 0 ? '+' : '';
  html += '<div class="tooltip-total ' + tc + '">P/L: $' + ts + d.total.toFixed(2) + '</div>';
  if (d.dep && d.dep !== 0) {{
    html += '<div style="font-size:12px;color:#ef4444;margin-bottom:2px">Dep: -$' + d.dep.toFixed(2) + '</div>';
  }}
  if (d.wd && d.wd !== 0) {{
    html += '<div style="font-size:12px;color:#60a5fa;margin-bottom:2px">Wd: +$' + Math.abs(d.wd).toFixed(2) + '</div>';
  }}
  if (d.dep && d.dep !== 0 && d.wd && d.wd !== 0) {{
    const net = d.dep + d.wd;
    const nc  = net > 0 ? '#ef4444' : '#60a5fa';
    const ns  = net > 0 ? '-$' + net.toFixed(2) : '+$' + Math.abs(net).toFixed(2);
    html += '<div style="font-size:12px;color:' + nc + ';margin-bottom:6px">Net: ' + ns + '</div>';
  }}

  // Only show brokers/accounts that are currently checked
  for (const [broker, binfo] of Object.entries(d.brokers)) {{
    const visibleAccts = Object.entries(binfo.accounts).filter(([acct]) =>
      selectedAccounts.has(acctKey(broker, acct))
    );
    if (visibleAccts.length === 0) continue;

    const bpl = visibleAccts.reduce((s, [, a]) => s + (a.pl || 0), 0);
    const color = brokerColors[broker] || '#888';
    const bc    = bpl >= 0 ? 'green' : 'red';
    const bs    = bpl >= 0 ? '+' : '';
    html += '<div class="tooltip-broker">'
      + '<span style="display:inline-flex;align-items:center;gap:5px">'
      + '<span style="width:8px;height:8px;border-radius:50%;background:' + color + ';display:inline-block"></span>'
      + '<strong>' + broker + '</strong></span>'
      + '<span class="' + bc + '">$' + bs + bpl.toFixed(2) + '</span></div>';

    for (const [acct, ainfo] of visibleAccts) {{
      const apl = ainfo.pl;
      const hasDW = (ainfo.dep && ainfo.dep !== 0) || (ainfo.wd && ainfo.wd !== 0);
      if (apl === 0 && !hasDW) continue;
      const ac  = apl >= 0 ? 'green' : 'red';
      const as_ = apl >= 0 ? '+' : '';
      let acctLine = '';
      if (apl !== 0) {{
        acctLine += '<div class="tooltip-acct"><span>#' + maskAcct(acct) + '</span>'
          + '<span class="' + ac + '">$' + as_ + apl.toFixed(2) + '</span></div>';
      }}
      if (ainfo.dep && ainfo.dep !== 0) {{
        acctLine += '<div class="tooltip-acct" style="color:#ef4444"><span>#' + maskAcct(acct) + ' Dep</span><span>-$' + ainfo.dep.toFixed(2) + '</span></div>';
      }}
      if (ainfo.wd && ainfo.wd !== 0) {{
        acctLine += '<div class="tooltip-acct" style="color:#60a5fa"><span>#' + maskAcct(acct) + ' Wd</span><span>+$' + Math.abs(ainfo.wd).toFixed(2) + '</span></div>';
      }}
      html += acctLine;
    }}
  }}

  tip.innerHTML = html;
  tip.classList.add('visible');
  document.getElementById('tooltipBackdrop').classList.add('visible');
  if (window.innerWidth > 768) {{
    const rect = e.currentTarget.getBoundingClientRect();
    let left = rect.right + 8;
    let top  = rect.top;
    if (left + 260 > window.innerWidth)  left = rect.left - 268;
    if (top  + 250 > window.innerHeight) top  = window.innerHeight - 260;
    tip.style.left = left + 'px';
    tip.style.top  = top  + 'px';
    tip.style.transform = '';
  }}
}}

document.addEventListener('click', e => {{
  if (!e.target.closest('.day-cell[data-date]'))
    closeTooltip();
}});

// ── Initialize from saved selection ─────────────────────────────────────────
loadSelection();
updateCalendar();
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Calendar saved to: {output_path}")
