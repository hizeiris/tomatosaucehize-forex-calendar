import re
from datetime import date
from typing import Optional
from bs4 import BeautifulSoup
from .base import BaseParser, DailyRecord


class HantecParser(BaseParser):
    broker_name = "Hantec"
    gmail_query = 'from:(hantecmarkets.com OR hantec) newer_than:12m'

    def can_parse(self, subject: str, sender: str) -> bool:
        return "hantec" in sender.lower()

    def parse(self, subject: str, date_header: str, html_body: str, plain_body: str) -> Optional[DailyRecord]:
        body = html_body or plain_body
        if not body:
            return None

        soup = BeautifulSoup(body, "html.parser")
        text = soup.get_text(separator="\n")

        account = self._extract_after(text, r"A/C\s*No\s*[:\s]+(\d+)")

        # Date format: "2026.05.15 23:59"
        date_match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})\s+\d{2}:\d{2}", text)
        if date_match:
            try:
                stmt_date = date(int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)))
            except ValueError:
                stmt_date = self._parse_date_header(date_header)
        else:
            stmt_date = self._parse_date_header(date_header)

        closed_pl   = self._extract_next_number(text, r"Closed\s+(?:Trade\s+)?P/L")
        deposit_wd  = self._extract_next_number(text, r"Deposit\s*/\s*Withdrawal")
        balance     = self._extract_next_number(text, r"^Balance", multiline=True)
        equity      = self._extract_next_number(text, r"^Equity", multiline=True)
        floating_pl = self._extract_next_number(text, r"Floating\s+P/L")

        return DailyRecord(
            broker=self.broker_name,
            account=account,
            date=stmt_date,
            closed_pl=closed_pl,
            deposit_withdrawal=deposit_wd,
            balance=balance,
            equity=equity,
            floating_pl=floating_pl,
        )

    def _extract_after(self, text: str, pattern: str) -> str:
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else "unknown"

    def _extract_next_number(self, text: str, label_pattern: str, multiline: bool = False) -> float:
        flags = re.IGNORECASE | (re.MULTILINE if multiline else 0)
        m = re.search(label_pattern, text, flags)
        if not m:
            return 0.0
        snippet = text[m.end():m.end() + 80]
        num = re.search(r"([-]?\d[\d,\.]*)", snippet)
        return self._clean_number(num.group(1)) if num else 0.0

    @staticmethod
    def _parse_date_header(date_header: str) -> date:
        from email.utils import parsedate_to_datetime
        try:
            return parsedate_to_datetime(date_header).date()
        except Exception:
            return date.today()
