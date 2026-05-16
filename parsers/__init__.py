from .vantage import VantageParser
from .hantec import HantecParser
from .axitrader import AxiTraderParser
from .xm import XMParser

ALL_PARSERS = [VantageParser(), HantecParser(), AxiTraderParser(), XMParser()]
