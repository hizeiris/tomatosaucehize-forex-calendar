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
    if len(account) <= 4:
        return account
    return "****" + account[-4:]


def generate_charts_html(records: List[DailyRecord], output_path: str = "output/charts.html"):
    if not records:
        print("No records to display.")
        return

    # ── Build data structures ────────────────────────────────────────────────
    day_map: Dict[date, List[DailyRecord]] = defaultdict(list)
    for r in records:
        day_map[r.date].append(r)

    all_dates  = sorted(day_map.keys())
    brokers    = sorted({r.broker for r in records})

    broker_accounts: Dict[str, List[str]] = {}
    for b in brokers:
        broker_accounts[b] = sorted({r.account for r in records if r.broker == b})

    # days_data: {iso_date: {total, brokers: {broker: {pl, accounts: {acct: pl}}}}}
    days_data = {}
    for d, recs in day_map.items():
        brokers_d = {}
        for r in recs:
            if r.broker not in brokers_d:
                brokers_d[r.broker] = {"pl": 0.0, "accounts": {}}
            brokers_d[r.broker]["pl"]              += r.closed_pl
            brokers_d[r.broker]["accounts"][r.account] = r.closed_pl
        days_data[d.isoformat()] = {
            "total":   sum(r.closed_pl for r in recs),
            "brokers": brokers_d,
        }

    # ── Filter dropdown HTML ─────────────────────────────────────────────────
    filter_options = '<option value="ALL">All Accounts</option>'
    for b in brokers:
        color  = _broker_color(b)
        b_total = sum(r.closed_pl for r in records if r.broker == b)
        filter_options += (
            f'<optgroup label="── {b} (${b_total:+,.2f})">'
            f'<option value="broker:{b}">{b} — All</option>'
        )
        for a in broker_accounts[b]:
            a_total = sum(r.closed_pl for r in records if r.broker == b and r.account == a)
            filter_options += f'<option value="account:{b}:{a}">#{_mask_acct(a)} (${a_total:+,.2f})</option>'
        filter_options += '</optgroup>'

    updated = datetime.now().strftime('%Y-%m-%d %H:%M')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Forex P/L Charts</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:#0f172a;--surface:#1e293b;--border:#334155;
    --text:#f1f5f9;--muted:#94a3b8;
    --green:#22c55e;--red:#ef4444;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh}}
  .header{{background:var(--surface);border-bottom:1px solid var(--border);padding:16px 32px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}}
  .header-left{{display:flex;align-items:center;gap:16px}}
  .back-btn{{background:transparent;border:1px solid var(--border);border-radius:8px;color:var(--muted);padding:7px 14px;font-size:13px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:6px}}
  .back-btn:hover{{border-color:var(--text);color:var(--text)}}
  .header h1{{font-size:20px;font-weight:700}}
  .header h1 span{{color:#22c55e}}
  .updated{{font-size:12px;color:var(--muted)}}
  .controls{{display:flex;gap:12px;padding:20px 32px;flex-wrap:wrap;align-items:center}}
  .ctrl-label{{font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.5px}}
  .ctrl-select{{background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:8px 12px;font-size:13px;cursor:pointer;outline:none;min-width:140px;color-scheme:dark}}
  .ctrl-select:focus{{border-color:#22c55e}}
  .quick-btn{{background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--muted);padding:7px 10px;font-size:11px;cursor:pointer;height:38px}}
  .quick-btn:hover{{border-color:#22c55e;color:#22c55e}}
  .ctrl-group{{display:flex;flex-direction:column;gap:6px}}
  .chart-container{{margin:0 32px 32px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;position:relative}}
  .chart-title{{font-size:15px;font-weight:700;margin-bottom:4px}}
  .chart-subtitle{{font-size:12px;color:var(--muted);margin-bottom:20px}}
  .chart-wrap{{position:relative;height:420px}}
  .stats-row{{display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap}}
  .stat-chip{{background:rgba(255,255,255,.05);border:1px solid var(--border);border-radius:8px;padding:10px 16px;font-size:12px;color:var(--muted)}}
  .stat-chip strong{{display:block;font-size:16px;font-weight:700;color:var(--text);margin-top:2px}}
  .green{{color:var(--green)}} .red{{color:var(--red)}}
  @media(max-width:600px){{
    .header{{padding:12px 16px}}
    .controls{{padding:12px 16px;gap:10px}}
    .chart-container{{margin:0 12px 20px;padding:16px}}
    .chart-wrap{{height:280px}}
    .ctrl-select{{min-width:140px}}
  }}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <a class="back-btn" href="calendar.html">← Calendar</a>
    <h1>Forex P/L <span>Charts</span></h1>
  </div>
  <span class="updated">Updated: {updated}</span>
</div>

<div class="controls">
  <div class="ctrl-group">
    <span class="ctrl-label">Chart Type</span>
    <select class="ctrl-select" id="chartType" onchange="onChartTypeChange(this.value)">
      <option value="equity">Equity Curve</option>
      <option value="monthly">Monthly Bar</option>
    </select>
  </div>
  <div class="ctrl-group">
    <span class="ctrl-label">Filter</span>
    <select class="ctrl-select" id="filterSelect" onchange="onFilterChange(this.value)">
      {filter_options}
    </select>
  </div>
  <div class="ctrl-group">
    <span class="ctrl-label">From</span>
    <input type="date" class="ctrl-select" id="dateFrom" onchange="onDateChange()">
  </div>
  <div class="ctrl-group">
    <span class="ctrl-label">To</span>
    <input type="date" class="ctrl-select" id="dateTo" onchange="onDateChange()">
  </div>
  <div class="ctrl-group">
    <span class="ctrl-label">Quick</span>
    <div style="display:flex;gap:4px">
      <button class="quick-btn" onclick="setDateRange(7)">7d</button>
      <button class="quick-btn" onclick="setDateRange(30)">30d</button>
      <button class="quick-btn" onclick="setDateRange(90)">90d</button>
      <button class="quick-btn" onclick="setDateRange(0)">All</button>
    </div>
  </div>
</div>

<div class="chart-container">
  <div class="chart-title" id="chartTitle">Equity Curve</div>
  <div class="chart-subtitle" id="chartSubtitle">Cumulative P/L over time — All Accounts</div>
  <div class="stats-row" id="statsRow"></div>
  <div class="chart-wrap">
    <canvas id="mainChart"></canvas>
  </div>
</div>

<script>
const daysData       = {json.dumps(days_data, default=str)};
const brokerAccounts = {json.dumps(broker_accounts)};
const brokerColors   = {json.dumps(BROKER_COLORS)};

let chartInstance = null;
let currentType   = 'equity';
let currentFilter = 'ALL';
let dateFrom      = '';
let dateTo        = '';

// ── Date range ──────────────────────────────────────────────────────────────
function inDateRange(iso) {{
  if (dateFrom && iso < dateFrom) return false;
  if (dateTo   && iso > dateTo)   return false;
  return true;
}}

function loadDateRange() {{
  const saved = localStorage.getItem('dateRange');
  if (saved) {{
    try {{
      const obj = JSON.parse(saved);
      dateFrom = obj.from || '';
      dateTo   = obj.to   || '';
    }} catch(e) {{ dateFrom = ''; dateTo = ''; }}
  }}
  document.getElementById('dateFrom').value = dateFrom;
  document.getElementById('dateTo').value   = dateTo;
}}

function saveDateRange() {{
  localStorage.setItem('dateRange', JSON.stringify({{ from: dateFrom, to: dateTo }}));
}}

function onDateChange() {{
  dateFrom = document.getElementById('dateFrom').value;
  dateTo   = document.getElementById('dateTo').value;
  saveDateRange();
  renderChart();
}}

function setDateRange(days) {{
  if (days === 0) {{
    dateFrom = ''; dateTo = '';
  }} else {{
    const today = new Date();
    const from  = new Date(today);
    from.setDate(today.getDate() - days + 1);
    const fmt = d => d.toISOString().slice(0,10);
    dateFrom = fmt(from);
    dateTo   = fmt(today);
  }}
  document.getElementById('dateFrom').value = dateFrom;
  document.getElementById('dateTo').value   = dateTo;
  saveDateRange();
  renderChart();
}}

// ── Data helpers ──────────────────────────────────────────────────────────────
function getFilterLabel(f) {{
  if (f === 'ALL') return 'All Accounts';
  if (f.startsWith('broker:')) return f.slice(7) + ' — All';
  if (f.startsWith('account:')) {{
    const [,broker,acct] = f.split(':');
    return broker + ' #' + maskAcct(acct);
  }}
  return f;
}}

function maskAcct(a) {{
  return a.length <= 4 ? a : '****' + a.slice(-4);
}}

function getPlForDate(iso, filter) {{
  const d = daysData[iso];
  if (!d) return 0;
  if (filter === 'ALL') return d.total;
  if (filter.startsWith('broker:')) {{
    const b = filter.slice(7);
    return d.brokers[b] ? d.brokers[b].pl : 0;
  }}
  if (filter.startsWith('account:')) {{
    const [,broker,acct] = filter.split(':');
    const ba = d.brokers[broker];
    return (ba && ba.accounts[acct] !== undefined) ? ba.accounts[acct] : 0;
  }}
  return 0;
}}

function getAllDates() {{
  return Object.keys(daysData).filter(iso => inDateRange(iso)).sort();
}}

// ── Equity curve ──────────────────────────────────────────────────────────────
function buildEquityData(filter) {{
  const dates = getAllDates();
  let cum = 0;
  const labels = [];
  const values = [];
  dates.forEach(iso => {{
    const pl = getPlForDate(iso, filter);
    cum += pl;
    labels.push(iso);
    values.push(parseFloat(cum.toFixed(2)));
  }});
  return {{ labels, values }};
}}

// ── Monthly bar ───────────────────────────────────────────────────────────────
function buildMonthlyData(filter) {{
  const monthly = {{}};
  getAllDates().forEach(iso => {{
    const m = iso.slice(0, 7);
    monthly[m] = (monthly[m] || 0) + getPlForDate(iso, filter);
  }});
  const labels = Object.keys(monthly).sort();
  const values = labels.map(m => parseFloat(monthly[m].toFixed(2)));
  return {{ labels, values }};
}}

// ── Stats row ─────────────────────────────────────────────────────────────────
function renderStats(filter) {{
  const dates  = getAllDates();
  const pls    = dates.map(d => getPlForDate(d, filter));
  const total  = pls.reduce((a,b) => a+b, 0);
  const wins   = pls.filter(p => p > 0).length;
  const losses = pls.filter(p => p < 0).length;
  const best   = pls.length ? Math.max(...pls) : 0;
  const worst  = pls.length ? Math.min(...pls) : 0;
  const wr     = (wins + losses) > 0 ? (wins/(wins+losses)*100).toFixed(0) : 0;
  const tc     = total >= 0 ? 'green' : 'red';
  const ts     = total >= 0 ? '+' : '';

  document.getElementById('statsRow').innerHTML =
    `<div class="stat-chip">Total P/L<strong class="${{tc}}">${{ts}}$${{total.toLocaleString('en',{{minimumFractionDigits:2,maximumFractionDigits:2}})}}</strong></div>` +
    `<div class="stat-chip">Win Days<strong class="green">${{wins}}</strong></div>` +
    `<div class="stat-chip">Loss Days<strong class="red">${{losses}}</strong></div>` +
    `<div class="stat-chip">Win Rate<strong>${{wr}}%</strong></div>` +
    `<div class="stat-chip">Best Day<strong class="green">+$${{best.toFixed(2)}}</strong></div>` +
    `<div class="stat-chip">Worst Day<strong class="red">$${{worst.toFixed(2)}}</strong></div>`;
}}

// ── Chart render ──────────────────────────────────────────────────────────────
function renderChart() {{
  const type   = currentType;
  const filter = currentFilter;
  const label  = getFilterLabel(filter);

  // Titles
  if (type === 'equity') {{
    document.getElementById('chartTitle').textContent    = 'Equity Curve';
    document.getElementById('chartSubtitle').textContent = 'Cumulative P/L over time — ' + label;
  }} else {{
    document.getElementById('chartTitle').textContent    = 'Monthly P/L';
    document.getElementById('chartSubtitle').textContent = 'Total P/L per month — ' + label;
  }}

  renderStats(filter);

  const {{ labels, values }} = type === 'equity'
    ? buildEquityData(filter)
    : buildMonthlyData(filter);

  if (chartInstance) {{ chartInstance.destroy(); chartInstance = null; }}

  const ctx = document.getElementById('mainChart').getContext('2d');

  if (type === 'equity') {{
    // Line chart
    chartInstance = new Chart(ctx, {{
      type: 'line',
      data: {{
        labels,
        datasets: [{{
          label: 'Cumulative P/L',
          data: values,
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          fill: false,
          tension: 0.3,
          segment: {{
            borderColor: ctx => ctx.p1.parsed.y >= 0 ? '#22c55e' : '#ef4444',
          }},
        }},
        {{
          label: 'Zero line',
          data: labels.map(() => 0),
          borderColor: 'rgba(255,255,255,0.1)',
          borderWidth: 1,
          borderDash: [4,4],
          pointRadius: 0,
          fill: false,
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ intersect: false, mode: 'index' }},
        plugins: {{
          legend: {{ display: false }},
          tooltip: {{
            backgroundColor: '#1e293b',
            borderColor: '#334155',
            borderWidth: 1,
            titleColor: '#94a3b8',
            bodyColor: '#f1f5f9',
            callbacks: {{
              label: ctx => {{
                const v = ctx.parsed.y;
                return ' P/L: $' + (v >= 0 ? '+' : '') + v.toLocaleString('en', {{minimumFractionDigits:2}});
              }}
            }}
          }}
        }},
        scales: {{
          x: {{
            ticks: {{ color:'#64748b', maxTicksLimit:12, maxRotation:0 }},
            grid:  {{ color:'#1e293b' }},
          }},
          y: {{
            ticks: {{
              color:'#64748b',
              callback: v => '$' + v.toLocaleString('en', {{minimumFractionDigits:0}})
            }},
            grid: {{ color:'#334155' }},
          }}
        }}
      }}
    }});

  }} else {{
    // Bar chart
    const barColors = values.map(v => v >= 0 ? '#22c55e' : '#ef4444');
    chartInstance = new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels,
        datasets: [{{
          label: 'Monthly P/L',
          data: values,
          backgroundColor: barColors,
          borderRadius: 4,
          borderSkipped: false,
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ intersect: false, mode: 'index' }},
        plugins: {{
          legend: {{ display: false }},
          tooltip: {{
            backgroundColor: '#1e293b',
            borderColor: '#334155',
            borderWidth: 1,
            titleColor: '#94a3b8',
            bodyColor: '#f1f5f9',
            callbacks: {{
              label: ctx => {{
                const v = ctx.parsed.y;
                return ' P/L: $' + (v >= 0 ? '+' : '') + v.toLocaleString('en', {{minimumFractionDigits:2}});
              }}
            }}
          }}
        }},
        scales: {{
          x: {{
            ticks: {{ color:'#64748b', maxRotation:45 }},
            grid:  {{ color:'#1e293b' }},
          }},
          y: {{
            ticks: {{
              color:'#64748b',
              callback: v => '$' + v.toLocaleString('en', {{minimumFractionDigits:0}})
            }},
            grid: {{ color:'#334155' }},
          }}
        }}
      }}
    }});
  }}
}}

// ── Event handlers ────────────────────────────────────────────────────────────
function onChartTypeChange(val) {{
  currentType = val;
  renderChart();
}}

function onFilterChange(val) {{
  currentFilter = val;
  renderChart();
}}

// ── Init ──────────────────────────────────────────────────────────────────────
loadDateRange();
renderChart();
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Charts saved to: {output_path}")
