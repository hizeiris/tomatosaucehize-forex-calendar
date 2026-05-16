import re
from datetime import date, datetime
from typing import Optional
from bs4 import BeautifulSoup
from .base import BaseParser, DailyRecord


class VantageParser(BaseParser):
    broker_name = "Vantage"
    gmail_query = 'from:(vantagemarkets OR vantage-fx.com OR vantagefx.com) subject:(daily OR confirmation) -subject:monthly'

    def can_parse(self, subject: str, sender: str) -> bool:
        return "vantage" in sender.lower() or "vantagemarkets" in sender.lower()

    def parse(self, subject: str, date_header: str, html_body: str, plain_body: str) -> Optional[DailyRecord]:
        body = html_body or plain_body
        if not body:
            return None

        soup = BeautifulSoup(body, "html.parser")
        text = soup.get_text(separator="\n")

        # Account number
        acct_m = re.search(r"(?:A/C\s*No|Login\s*ID)\s*[:\s]+(\d+)", text, re.IGNORECASE)
        account = acct_m.group(1).strip() if acct_m else "unknown"

        # Statement date
        d1 = re.search(r"(\d{4})[.\-\s](\d{2})[.\-\s](\d{2})", text)
        if d1:
            try:
                stmt_date = date(int(d1.group(1)), int(d1.group(2)), int(d1.group(3)))
            except ValueError:
                stmt_date = self._parse_date_header(date_header)
        else:
            stmt_date = self._parse_date_header(date_header)

        # Find A/C Summary section — all values read from there
        s = re.search(r"A/C\s*Summary", text, re.IGNORECASE)
        section = text[s.start():] if s else text

        closed_pl   = self._val(section, r"Closed\s+Trade\s+P/L")
        deposit_wd  = self._val(section, r"Deposit\s*/\s*Withdrawal")
        balance     = self._val(section, r"(?<!\w)Balance\s*:")
        prev_bal    = self._val(section, r"Previous\s+Ledger\s+Balance")
        equity      = self._val(section, r"(?<!\w)Equity\s*:")
        floating_pl = self._val(section, r"Floating\s+P/L")

        # True daily P/L = Balance − Previous Ledger Balance − Deposit/Withdrawal
        # This is always accurate and cross-checks against Closed Trade P/L
        if balance is not None and prev_bal is not None:
            true_pl = round(balance - prev_bal - deposit_wd, 2)
        else:
            true_pl = closed_pl  # fallback if balance fields missing

        return DailyRecord(
            broker=self.broker_name,
            account=account,
            date=stmt_date,
            closed_pl=true_pl,
            deposit_withdrawal=deposit_wd,
            balance=balance,
            equity=equity,
            floating_pl=floating_pl,
        )

    def _val(self, text: str, pattern: str) -> float:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            return 0.0
        snippet = text[m.end(): m.end() + 80].replace("\xa0", " ")
        num = re.search(r"([-]?\d[\d,\.]*)", snippet)
        if not num:
            return 0.0
        try:
            return float(num.group(1).replace(",", ""))
        except ValueError:
            return 0.0

    @staticmethod
    def _parse_date_header(date_header: str) -> date:
        from email.utils import parsedate_to_datetime
        try:
            return parsedate_to_datetime(date_header).date()
        except Exception:
            return date.today()
