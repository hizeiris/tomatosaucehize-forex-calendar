from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class DailyRecord:
    broker: str
    account: str
    date: date
    closed_pl: float
    deposit_withdrawal: float
    balance: float
    equity: float
    floating_pl: float = 0.0
    statement_type: str = "daily"  # "daily" or "monthly"
    deposit: float = 0.0     # money broker paid into account (+)
    withdrawal: float = 0.0  # money pulled out of account (-)


class BaseParser:
    broker_name: str = ""
    gmail_query: str = ""

    def can_parse(self, subject: str, sender: str) -> bool:
        raise NotImplementedError

    def parse(self, subject: str, date_header: str, html_body: str, plain_body: str) -> Optional[DailyRecord]:
        raise NotImplementedError

    @staticmethod
    def _clean_number(text: str) -> float:
        """Convert a string like '1,234.56' or '-0.00' to float."""
        if not text:
            return 0.0
        cleaned = text.strip().replace(",", "").replace(" ", "")
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
