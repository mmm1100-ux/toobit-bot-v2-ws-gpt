from dataclasses import dataclass
from enum import Enum

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

@dataclass
class SymbolState:
    symbol: str
    price: float = 0.0

@dataclass
class OrderState:
    order_id: str
    symbol: str
    side: Side
    quantity: float
