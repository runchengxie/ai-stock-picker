"""Minimal stubs for LongPort/LongBridge openapi used during testing.

These classes provide just enough structure for the unit tests without
depending on the real third-party SDKs.  They also allow
``LongPortClient`` to fall back gracefully when the actual packages are
not installed.
"""

class Config:
    """Placeholder configuration object with :meth:`from_env` helper."""

    @staticmethod
    def from_env():  # pragma: no cover - trivial method
        return Config()


class Market:
    US = "US"
    HK = "HK"
    CN = "CN"
    SG = "SG"


class QuoteContext:
    def __init__(self, config):  # pragma: no cover - used in tests
        pass


class TradeContext:
    def __init__(self, config):  # pragma: no cover - used in tests
        pass


# Simple enum-style containers to satisfy tests
class OrderSide:
    Buy = "Buy"
    Sell = "Sell"


class OrderType:
    LO = "LO"


class TimeInForceType:
    Day = "Day"
    GTC = "GTC"
