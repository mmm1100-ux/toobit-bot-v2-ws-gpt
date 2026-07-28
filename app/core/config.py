from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Settings:
    api_key: str = ""
    api_secret: str = ""
    symbol: str = "BTCUSDT"

    @classmethod
    def load(cls):
        return cls(
            api_key=os.getenv("TOOBIT_API_KEY", ""),
            api_secret=os.getenv("TOOBIT_API_SECRET", ""),
            symbol=os.getenv("BOT_SYMBOL", "BTCUSDT"),
        )
