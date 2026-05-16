# Forex P/L Calendar

Reads daily/monthly statement emails from Gmail (Vantage, Hantec, AxiTrader, XM)
and generates a beautiful HTML P/L calendar dashboard.

---

## Quick Start

### Step 1 — Install Python dependencies

```
pip install -r requirements.txt
```

### Step 2 — Set up Gmail API credentials

1. Go to https://console.cloud.google.com/
2. Create a new project (e.g. "Forex Calendar")
3. Go to **APIs & Services → Library** and enable **Gmail API**
4. Go to **APIs & Services → Credentials**
5. Click **Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Name: anything
6. Download the JSON file and save it as `credentials.json` in this folder

### Step 3 — Run the app

```
python main.py
```

The first run will open a browser asking you to log in to Google and grant
read-only Gmail access. After that, a token is saved and no login is needed again.

The calendar will be saved to `output/calendar.html` — open it in any browser.

### Refresh data (fetch latest emails)

```
python main.py --refresh
```

---

## Supported Brokers

| Broker | Email type | P/L field extracted |
|---|---|---|
| Vantage | Daily Statement | Closed Trade P/L |
| Hantec Markets | Daily Confirmation | Closed P/L |
| AxiTrader | Daily Statement | Closed P/L |
| XM Global | Monthly Statement | Closed P/L |

---

## File structure

```
forex-pl-calendar/
├── main.py               # Entry point
├── gmail_client.py       # Gmail API connection
├── calendar_generator.py # HTML calendar output
├── parsers/
│   ├── vantage.py
│   ├── hantec.py
│   ├── axitrader.py
│   └── xm.py
├── data/
│   └── trades.json       # Cached data (auto-created)
├── output/
│   └── calendar.html     # Generated calendar (auto-created)
├── credentials.json      # YOUR Gmail API credentials (you download this)
└── requirements.txt
```

---

## Troubleshooting

**No emails found for a broker**
- Check that the Gmail search query in each parser matches your actual email sender.
- Try searching in Gmail manually for one of your broker emails, then update the
  `gmail_query` string in the relevant parser file.

**Wrong P/L values**
- The parsers use regex to find values in email HTML. If a broker changes their
  email template, the regex may need updating. Open the parser file and adjust
  the pattern.

**Add a new broker**
- Copy `parsers/vantage.py`, rename it, adjust `broker_name`, `gmail_query`,
  and the regex patterns. Then add it to `parsers/__init__.py`.
