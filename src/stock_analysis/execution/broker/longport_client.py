import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

# Compatibility import: prefer longport, fallback to longbridge and finally local stubs
try:  # pragma: no cover - depends on external package
    from longport.openapi import (
        Config,
        Market,
        OrderSide,
        OrderType,
        QuoteContext,
        TimeInForceType,
        TradeContext,
    )
except ImportError:  # pragma: no cover - executed when longport not available
    try:  # pragma: no cover - depends on optional package
        from longbridge.openapi import (
            Config,
            Market,
            OrderSide,
            OrderType,
            QuoteContext,
            TimeInForceType,
            TradeContext,
        )
    except ImportError:  # pragma: no cover - executed when neither SDK installed
        from ._stubs import (
            Config,
            Market,
            OrderSide,
            OrderType,
            QuoteContext,
            TimeInForceType,
            TradeContext,
        )

# Timezone support (Python 3.9+), fallback to local time determination when unavailable
try:
    from zoneinfo import ZoneInfo  # type: ignore
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from datetime import date, datetime

from ...shared.utils.fx import to_usd
from ...shared.logging import get_logger

logger = get_logger(__name__)


def get_config():
    """Return LongPort configuration based on environment variables.

    Compatible with direct calls in tests, equivalent to Config.from_env().
    """
    return Config.from_env()


def getenv_both(name_new: str, name_old: str, default: str = None) -> str:
    """Compatibility environment variable reading function, prioritize new prefix, fallback to old prefix.

    Args:
        name_new: New environment variable name (LONGPORT_*)
        name_old: Old environment variable name (LONGBRIDGE_*)
        default: Default value

    Returns:
        Environment variable value or default value
    """
    return os.getenv(name_new) or os.getenv(name_old) or default


class Env(str, Enum):
    REAL = "real"


@dataclass
class BrokerLimits:
    # 0 or negative means "no local cap" (unlimited, rely on broker)
    max_notional_per_order: float = 0.0
    max_qty_per_order: int = 0
    trading_window_start: str = "09:30"  # Local time (fallback only)
    trading_window_end: str = "16:00"


def _to_lb_symbol(ticker: str, market: str | None = None) -> str:
    """Convert ticker to LongPort symbol format.

    Args:
        ticker: Stock ticker symbol

    Returns:
        Formatted symbol for LongPort API
    """
    t = ticker.strip().upper()
    explicit_market = str(market or "").strip().upper()
    if explicit_market:
        if "." in t and t.rsplit(".", 1)[-1] in {"US", "HK", "SG", "CN"}:
            t = t.rsplit(".", 1)[0]
        return f"{t}.{explicit_market}"
    if t.endswith((".US", ".HK", ".SG", ".CN")):
        return t
    return f"{t}.US"  # Most stocks in your project are US stocks, default to .US


def _market_of(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith(".US"):
        return "US"
    if s.endswith(".HK"):
        return "HK"
    if s.endswith(".CN"):
        return "CN"
    if s.endswith(".SG"):
        return "SG"
    # 默认为美股
    return "US"


def _market_enum(m: str) -> Market:
    return {
        "US": Market.US,
        "HK": Market.HK,
        "CN": Market.CN,
        "SG": Market.SG,
    }[m]


def _enum_value(e):
    """Return a comparable value for both enum objects and string constants.

    ``longport`` exposes order-related constants as enum-like objects without
    a ``value`` attribute, whereas the legacy ``longbridge`` package and the
    test stubs use plain strings.  This helper normalises these different
    representations to a simple string such as ``"Buy"`` or ``"LO"``.  If the
    object provides a ``value`` attribute we use it, otherwise we fall back to
    the textual representation and extract the last component after a dot
    (e.g. ``OrderType.LO`` -> ``"LO"``).
    """

    if hasattr(e, "value"):
        try:  # ``Mock`` objects also have a ``value`` attribute; keep them as-is
            from unittest.mock import Mock

            if isinstance(e, Mock):
                return e
        except Exception:  # pragma: no cover - mock import always available in tests
            pass
        return e.value
    s = str(e)
    if "." in s:
        return s.split(".")[-1]
    return e


def _market_tz(m: str) -> str:
    # Exchange local timezone
    return {
        "US": "America/New_York",
        "HK": "Asia/Hong_Kong",
        "CN": "Asia/Shanghai",
        "SG": "Asia/Singapore",
    }[m]


class LongPortClient:
    """LongPort client for stock trading and querying.

    Provides a unified interface to access LongPort's trading and quote functionality.
    """

    def __init__(
        self, env: str | None = None, limits: BrokerLimits | None = None, config=None
    ):
        """Initialize LongPort client.

        Args:
            config: LongPort configuration object, if None then read from environment variables
        """
        # Force use of REAL environment
        self.env = Env.REAL
        self.region = getenv_both("LONGPORT_REGION", "LONGBRIDGE_REGION", "hk")

        self.app_key = getenv_both("LONGPORT_APP_KEY", "LONGBRIDGE_APP_KEY")
        self.app_secret = getenv_both("LONGPORT_APP_SECRET", "LONGBRIDGE_APP_SECRET")
        self.token_test = getenv_both(
            "LONGPORT_ACCESS_TOKEN_TEST", "LONGBRIDGE_ACCESS_TOKEN_TEST"
        )
        # Live trading prioritizes LONGPORT_ACCESS_TOKEN, compatible with legacy LONGPORT_ACCESS_TOKEN_REAL
        self.token_real = os.getenv("LONGPORT_ACCESS_TOKEN") or os.getenv(
            "LONGPORT_ACCESS_TOKEN_REAL"
        )

        # Validate required items first
        if not self.app_key or not self.app_secret:
            raise RuntimeError("缺少 LONGPORT_APP_KEY/SECRET。请通过系统环境变量注入。")

        # Only support REAL environment
        if not self.token_real:
            raise RuntimeError(
                "缺少 LONGPORT_ACCESS_TOKEN（或兼容 LONGPORT_ACCESS_TOKEN_REAL）。请通过系统环境变量注入。"
            )
        access_token = self.token_real

        # Inject token/region via environment variables, then use SDK's from_env to select correct endpoint and default config
        self._prev_env = {
            "LONGPORT_APP_KEY": os.getenv("LONGPORT_APP_KEY"),
            "LONGPORT_APP_SECRET": os.getenv("LONGPORT_APP_SECRET"),
            "LONGPORT_ACCESS_TOKEN": os.getenv("LONGPORT_ACCESS_TOKEN"),
            "LONGPORT_REGION": os.getenv("LONGPORT_REGION"),
        }
        os.environ["LONGPORT_APP_KEY"] = self.app_key
        os.environ["LONGPORT_APP_SECRET"] = self.app_secret
        os.environ["LONGPORT_ACCESS_TOKEN"] = access_token
        if self.region:
            os.environ["LONGPORT_REGION"] = self.region
        # Uniformly use SDK recommended from_env to ensure correct region and routing
        self.config = Config.from_env()

        # Lazily construct quote/trade contexts to avoid failing at init time
        # in environments with intermittent connectivity or region mismatch.
        # Use lightweight wrappers that only create the underlying contexts
        # when a method is actually invoked.

        class _LazyContext:
            def __init__(self, factory):
                self._factory = factory
                self._ctx = None

            def _ensure(self):
                if self._ctx is None:
                    self._ctx = self._factory()
                return self._ctx

            def __getattr__(self, name):
                return getattr(self._ensure(), name)

        # Region-aware factory with fallback on connection timeout
        def _mk_ctx(kind: str):
            def _factory():
                # Try current region first, then fall back to common regions
                tried: list[str] = []
                for rg in [self.region, "us", "hk", "sg"]:
                    if not rg or rg in tried:
                        continue
                    tried.append(rg)
                    os.environ["LONGPORT_REGION"] = rg
                    try:
                        cfg = Config.from_env()
                        return QuoteContext(cfg) if kind == "quote" else TradeContext(cfg)
                    except Exception as e:  # Defer raising until all options tried
                        # Only retry on probable connectivity/endpoint issues
                        msg = str(e).lower()
                        if "timeout" in msg or "connect" in msg or "dns" in msg:
                            continue
                        raise
                # Should not reach here; raise a generic error if we do
                raise RuntimeError("无法初始化 LongPort 上下文：网络或区域配置异常")

            return _factory

        self.quote = _LazyContext(_mk_ctx("quote"))
        self.trade = _LazyContext(_mk_ctx("trade"))
        # Backward compatible attribute names expected by older code/tests
        self.q = self.quote
        self.t = self.trade

        # Build limits from env if not explicitly provided. 0 means unlimited.
        if limits is None:

            def _to_float(v: str | None, default: float = 0.0) -> float:
                try:
                    return float(str(v)) if v is not None else default
                except Exception:
                    return default

            def _to_int(v: str | None, default: int = 0) -> int:
                try:
                    return int(float(str(v))) if v is not None else default
                except Exception:
                    return default

            max_notional_env = getenv_both(
                "LONGPORT_MAX_NOTIONAL_PER_ORDER",
                "LONGBRIDGE_MAX_NOTIONAL_PER_ORDER",
                "0",
            )
            max_qty_env = getenv_both(
                "LONGPORT_MAX_QTY_PER_ORDER",
                "LONGBRIDGE_MAX_QTY_PER_ORDER",
                "0",
            )
            tw_start = getenv_both(
                "LONGPORT_TRADING_WINDOW_START",
                "LONGBRIDGE_TRADING_WINDOW_START",
                "09:30",
            )
            tw_end = getenv_both(
                "LONGPORT_TRADING_WINDOW_END",
                "LONGBRIDGE_TRADING_WINDOW_END",
                "16:00",
            )
            self.limits = BrokerLimits(
                max_notional_per_order=_to_float(max_notional_env, 0.0),
                max_qty_per_order=_to_int(max_qty_env, 0),
                trading_window_start=str(tw_start or "09:30"),
                trading_window_end=str(tw_end or "16:00"),
            )
        else:
            self.limits = limits

        enable_overnight = getenv_both(
            "LONGPORT_ENABLE_OVERNIGHT", "LONGBRIDGE_ENABLE_OVERNIGHT", "false"
        )
        self.allow_extended = str(enable_overnight).strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }

        # Cache related
        self._session_cache: dict[str, list[tuple[int, int, str]]] = {}
        self._session_cache_expire_at: float = 0.0
        self._is_trading_day_cache: dict[str, bool] = {}
        self._day_cache_expire_at: float = 0.0
        self._cache_ttl_seconds: int = 600

    # ---------- Quote Data ----------
    def quote_last(self, symbols: Iterable[str]) -> dict[str, tuple[float, str]]:
        """Get last quotes for given symbols.

        Args:
            symbols: List of ticker symbols

        Returns:
            Dict mapping symbol to (last_price, timestamp) tuple
        """
        bars: dict[str, tuple[float, str]] = {}
        symbol_list = [_to_lb_symbol(x) for x in symbols]
        quote_ctx = getattr(self, "q", None) or getattr(self, "quote", None)
        if quote_ctx is None:
            raise AttributeError("Quote context not initialised")
        ret = quote_ctx.quote(symbol_list)
        for i in ret:
            # Prefer last_done, fallback to prev_close if missing/zero
            px = float((getattr(i, "last_done", 0) or 0) or 0)
            if px <= 0:
                prev = getattr(i, "prev_close", None)
                if prev not in (None, 0):
                    try:
                        px = float(prev)
                    except Exception:
                        px = 0.0
            bars[i.symbol] = (px, getattr(i, "timestamp", "") or "")
        return bars

    def candles(
        self,
        symbol: str,
        start: date,
        end: date,
        period,
        adjust: int | None = None,
    ):
        """Fetch historical candle data for a symbol.

        Parameters mirror the underlying SDK's ``history_candlesticks_by_date``
        call; the method mainly ensures the ticker is converted to the
        LongPort format and that parameters are forwarded correctly.
        """

        quote_ctx = getattr(self, "q", None) or getattr(self, "quote", None)
        if quote_ctx is None:
            raise AttributeError("Quote context not initialised")
        lb_symbol = _to_lb_symbol(symbol)
        market = _market_enum(_market_of(lb_symbol))
        return quote_ctx.history_candlesticks_by_date(
            lb_symbol, period, market, start, end, adjust
        )

    def submit_limit(
        self,
        symbol: str,
        price: float,
        quantity: float,
        tif: TimeInForceType | None = None,
        remark: str | None = None,
    ):
        """Submit a limit order.

        The sign of ``quantity`` determines the order side: positive for buy
        orders and negative for sell orders. ``quantity`` is converted to its
        absolute value when sending to the broker. ``price`` and ``quantity``
        are converted to ``Decimal`` to avoid floating point issues.
        """

        trade_ctx = getattr(self, "t", None) or getattr(self, "trade", None)
        if trade_ctx is None:
            raise AttributeError("Trade context not initialised")

        side = OrderSide.Buy if quantity >= 0 else OrderSide.Sell
        qty = Decimal(str(abs(quantity)))
        px = Decimal(str(price))
        if tif is None:
            tif = TimeInForceType.Day
        return trade_ctx.submit_order(
            symbol=_to_lb_symbol(symbol),
            order_type=_enum_value(OrderType.LO),
            side=_enum_value(side),
            submitted_price=px,
            submitted_quantity=qty,
            time_in_force=_enum_value(tif),
            remark=remark,
        )

    def portfolio_snapshot(
        self,
    ) -> tuple[float, dict[str, int], float | None, str | None]:
        """
        Get account snapshot including cash and position information.

        Returns:
            Tuple of (cash_usd, stock_position_map, net_assets, base_currency)
            - cash_usd: USD available cash only (no FX conversion)
            - stock_position_map: {'AAPL.US': 100, ...}
            - net_assets: Total assets from broker (multi-currency/positions), if available
            - base_currency: Currency of net_assets (e.g. 'HKD')

        Compatible with different SDK versions of asset/balance and stock_positions/position_list return formats.
        """
        cash_usd = 0.0
        pos_map: dict[str, int] = {}
        net_assets: float | None = None
        base_ccy: str | None = None

        # ---------- Cash ----------
        # Be resilient: try asset() then account_balance(); log failures instead of swallowing silently.
        asset = None
        last_err: Exception | None = None
        for fn_name in ("asset", "account_balance"):
            fn = getattr(self.trade, fn_name, None)
            if not fn:
                continue
            try:
                asset = fn()
                break
            except Exception as e:  # pragma: no cover - depends on live SDK/network
                last_err = e
                logger.debug(f"调用 {fn_name}() 获取资金失败: {e}")
                continue

        if asset is None:
            if last_err is not None:
                logger.warning(f"无法获取账户资金信息，视为0（原因: {last_err}）")
        else:
            # 1) Prefer detailed cash_infos aggregation by currency; support list returns
            assets_seq = asset if isinstance(asset, (list, tuple)) else [asset]
            totals: dict[str, float] = {}
            picked_net_assets: float | None = None
            picked_base_ccy: str | None = None
            for ab in assets_seq:
                ci_list = (
                    getattr(ab, "cash_infos", None)
                    or getattr(ab, "cash_info", None)
                    or []
                )
                for ci in ci_list:
                    ccy = str(
                        getattr(ci, "currency", "") or getattr(ci, "ccy", "")
                    ).upper()
                    # prefer available_cash > cash > withdraw_cash
                    raw_amt = (
                        getattr(ci, "available_cash", None)
                        or getattr(ci, "cash", None)
                        or getattr(ci, "withdraw_cash", 0.0)
                    )
                    try:
                        amt = float(raw_amt or 0.0)
                    except Exception:
                        amt = 0.0
                    if not ccy:
                        continue
                    totals[ccy] = totals.get(ccy, 0.0) + amt

                if picked_net_assets is None:
                    na = getattr(ab, "net_assets", None)
                    if na is not None:
                        try:
                            picked_net_assets = float(na)
                        except Exception:
                            picked_net_assets = None
                if picked_base_ccy is None:
                    picked_base_ccy = (
                        str(
                            getattr(ab, "currency", "")
                            or getattr(ab, "base_currency", "")
                        ).upper()
                        or None
                    )

            if totals:
                logger.debug(
                    "现金分币种: "
                    + ", ".join(f"{k}={v:.2f}" for k, v in totals.items())
                )
            # USD direct bucket
            cash_usd = totals.get("USD", 0.0)
            # Broker-reported total assets and base currency
            if picked_net_assets is not None:
                net_assets = picked_net_assets
            if picked_base_ccy is not None:
                base_ccy = picked_base_ccy

            # 2) If no USD bucket, try converting other currencies; finally fallback to object-level fields
            if cash_usd == 0.0:
                if totals:
                    total_conv = 0.0
                    any_conv = False
                    for ccy, amt in totals.items():
                        if ccy == "USD":
                            continue
                        conv = to_usd(amt, ccy)
                        if conv is not None:
                            total_conv += float(conv)
                            any_conv = True
                    if any_conv:
                        cash_usd = total_conv
                        logger.debug(f"按汇率折算非USD现金合计: {cash_usd:.2f} USD")

                if cash_usd == 0.0:
                    # Some SDKs expose top-level fields on a single object; attempt a last resort
                    for name in (
                        "available_cash",
                        "cash",
                        "withdraw_cash",
                        "total_cash",
                    ):
                        v = getattr(asset, name, None)
                        if v is None:
                            continue
                        try:
                            raw = float(v)
                        except Exception:
                            continue
                        if raw == 0.0:
                            continue
                        b = (base_ccy or "").upper() if base_ccy else None
                        if b and b != "USD":
                            converted = to_usd(raw, b)
                            if converted is not None:
                                cash_usd = float(converted)
                                logger.debug(
                                    f"使用{b}字段{name}={raw:.2f}折算USD={cash_usd:.2f}"
                                )
                                break
                        elif b == "USD":
                            cash_usd = raw
                            logger.debug(f"使用USD字段{name}={cash_usd:.2f}")
                            break
                if cash_usd == 0.0 and totals and any(k != "USD" for k in totals):
                    logger.debug(
                        "未找到USD现金，检测到非USD余额；如需折算，请配置FX或启用USD子账户。"
                    )

        # ---------- Positions ----------
        try:
            pos_fn = getattr(self.trade, "stock_positions", None) or getattr(
                self.trade, "position_list", None
            )
            if not pos_fn:
                return cash_usd, pos_map, net_assets, base_ccy

            ret = pos_fn()

            # Compatible with multiple formats:
            # 1) Object has .list; 2) Object has .channels (new version return);
            # 3) dict has same-named keys; 4) Direct list
            groups = getattr(ret, "list", None) or getattr(ret, "channels", None)
            if groups is None and isinstance(ret, dict):
                groups = ret.get("list", None) or ret.get("channels", None)
            if groups is None:
                groups = ret  # Some SDKs directly return flattened list

            def push(sym, qty, market=None):
                if sym is None or qty is None:
                    return
                try:
                    q = int(float(qty))
                except Exception:
                    return
                s = str(sym).upper()
                if "." not in s and market:
                    s = f"{s}.{str(market).upper()}"
                pos_map[s] = pos_map.get(s, 0) + q

            if isinstance(groups, list):
                for g in groups:
                    # Format A (old): Group object contains stock_info list
                    stock_info = getattr(g, "stock_info", None)
                    if stock_info is None and isinstance(g, dict):
                        stock_info = g.get("stock_info")

                    if stock_info is not None:
                        for it in stock_info:
                            sym = (
                                getattr(it, "symbol", None)
                                if not isinstance(it, dict)
                                else it.get("symbol")
                            )
                            qty = (
                                getattr(it, "quantity", None)
                                if not isinstance(it, dict)
                                else it.get("quantity")
                            )
                            mkt = (
                                getattr(it, "market", None)
                                if not isinstance(it, dict)
                                else it.get("market")
                            )
                            push(sym, qty, mkt)
                    else:
                        # Format B (new): Group contains positions list (e.g. ret.channels[].positions)
                        positions = getattr(g, "positions", None)
                        if positions is None and isinstance(g, dict):
                            positions = g.get("positions")
                        if positions is not None:
                            for it in positions:
                                sym = (
                                    getattr(it, "symbol", None)
                                    if not isinstance(it, dict)
                                    else it.get("symbol")
                                )
                                qty = (
                                    getattr(it, "quantity", None)
                                    if not isinstance(it, dict)
                                    else it.get("quantity")
                                )
                                mkt = (
                                    getattr(it, "market", None)
                                    if not isinstance(it, dict)
                                    else it.get("market")
                                )
                                push(sym, qty, mkt)
                        else:
                            # Format C: Already flattened Position object
                            it = g
                            sym = (
                                getattr(it, "symbol", None)
                                if not isinstance(it, dict)
                                else it.get("symbol")
                            )
                            qty = (
                                getattr(it, "quantity", None)
                                if not isinstance(it, dict)
                                else it.get("quantity")
                            )
                            mkt = (
                                getattr(it, "market", None)
                                if not isinstance(it, dict)
                                else it.get("market")
                            )
                            push(sym, qty, mkt)
        except Exception as e:
            logger.warning(f"获取持仓信息失败: {e}")

        return cash_usd, pos_map, net_assets, base_ccy

    def fund_positions(self) -> dict[str, tuple[float, float, str]]:
        """
        Get fund position information.

        Returns:
            Fund position mapping: { symbol => (holding_units, current_nav, currency) }
            - symbol: Fund code/ISIN returned by LongPort
            - holding_units: Holding units (float)
            - current_nav: Current net asset value (float)
            - currency: Currency code
        """
        result: dict[str, tuple[float, float, str]] = {}
        try:
            fn = getattr(self.trade, "fund_positions", None)
            if not fn:
                return result
            resp = fn()
            # Format: resp.list[account].fund_info[*]
            accounts = getattr(resp, "list", None) or []
            for acc in accounts:
                fund_info = getattr(acc, "fund_info", None) or []
                for it in fund_info:
                    sym = (
                        getattr(it, "symbol", None)
                        if not isinstance(it, dict)
                        else it.get("symbol")
                    )
                    units = (
                        getattr(it, "holding_units", None)
                        if not isinstance(it, dict)
                        else it.get("holding_units")
                    )
                    nav = (
                        getattr(it, "current_net_asset_value", None)
                        if not isinstance(it, dict)
                        else it.get("current_net_asset_value")
                    )
                    ccy = (
                        getattr(it, "currency", None)
                        if not isinstance(it, dict)
                        else it.get("currency")
                    )
                    if sym is None or units is None or nav is None:
                        continue
                    try:
                        u = float(units)
                        p = float(nav)
                    except Exception:
                        continue
                    result[str(sym)] = (u, p, str(ccy or ""))
        except Exception as e:
            # Failure to get fund positions doesn't affect main flow
            logger.warning(f"获取基金持仓失败: {e}")
        return result

    def lot_size(self, symbol: str) -> int:
        """Get the lot size (shares per lot) for a stock.

        Args:
            symbol: Stock symbol

        Returns:
            Shares per lot
        """
        # Fast path: US stocks default to 1, avoid unnecessary permission output from static info queries
        if _market_of(symbol) == "US":
            return 1
        try:
            info = self.quote.static_info([_to_lb_symbol(symbol)])
            if info and info[0].lot_size:
                return max(1, int(info[0].lot_size))
        except Exception as e:
            logger.warning(f"获取 {symbol} 的 lot size 失败: {e}")
        return 1

    # ---------- Internal: Authoritative market info caching ----------
    def _refresh_caches_if_needed(self) -> None:
        """Refresh trading session and trading day cache if expired."""
        now_ts = time.time()
        # Refresh trading session cache
        if now_ts >= self._session_cache_expire_at:
            try:
                resp = self.quote.trading_session()
                session_map: dict[str, list[tuple[int, int, str]]] = {}
                for item in getattr(resp, "market_trade_session", []) or []:
                    market = getattr(item, "market", "").upper()
                    sessions = []
                    for seg in getattr(item, "trade_session", []) or []:
                        beg = int(getattr(seg, "beg_time", 0))  # hhmm
                        end = int(getattr(seg, "end_time", 0))  # hhmm
                        code = getattr(seg, "trade_session", None)
                        # Convention: None/0 => Regular, 1 => Pre, 2 => Post, 3 => Overnight (if supported)
                        if code in (None, 0):
                            kind = "Regular"
                        elif code == 1:
                            kind = "Pre"
                        elif code == 2:
                            kind = "Post"
                        elif code == 3:
                            kind = "Overnight"
                        else:
                            kind = "Other"
                        sessions.append((beg, end, kind))
                    if market:
                        session_map[market] = sessions
                self._session_cache = session_map
                self._session_cache_expire_at = now_ts + self._cache_ttl_seconds
            except Exception:
                # Clear and expire immediately when unavailable, leave to fallback logic
                self._session_cache = {}
                self._session_cache_expire_at = 0.0

        # Refresh "is today a trading day" cache (by market)
        if now_ts >= self._day_cache_expire_at:
            try:
                date.today()
                # We only populate when a market is used, clear first
                self._is_trading_day_cache = {}
                self._day_cache_expire_at = now_ts + self._cache_ttl_seconds
            except Exception:
                self._is_trading_day_cache = {}
                self._day_cache_expire_at = 0.0

    def _is_trading_day(self, market_str: str) -> bool:
        # Check cache first
        if market_str in self._is_trading_day_cache:
            return self._is_trading_day_cache[market_str]
        try:
            today = date.today()
            resp = self.quote.trading_days(_market_enum(market_str), today, today)
            days = set(getattr(resp, "trade_day", []) or [])
            # API returns YYMMDD string, simply check if today is in it
            yymmdd = today.strftime("%Y%m%d")[2:]  # Convert to YYMMDD
            ok = yymmdd in days
            self._is_trading_day_cache[market_str] = ok
            return ok
        except Exception:
            # API failure: conservatively return False (fail closed)
            self._is_trading_day_cache[market_str] = False
            return False

    # ---------- Pre-order checks ----------
    def _check_window(self, symbol: str) -> None:
        """Check if current time is within trading window.

        Uses LongPort authoritative trading session and trading day interface. Falls back to local time estimation if interface unavailable.
        """
        self._refresh_caches_if_needed()

        symbol_fmt = _to_lb_symbol(symbol)
        market_str = _market_of(symbol_fmt)

        # 1) Reject if not a trading day
        if not self._is_trading_day(market_str):
            raise RuntimeError("非交易日，禁止交易")

        # 2) Authoritative segment determination
        sessions = self._session_cache.get(market_str, [])
        if sessions and ZoneInfo is not None:
            tz = ZoneInfo(_market_tz(market_str))
            now_ex = datetime.now(tz)
            hhmm = now_ex.hour * 100 + now_ex.minute

            # Allowed segments
            def allowed(kind: str) -> bool:
                if kind == "Regular":
                    return True
                # Pre/Post/Overnight: only allow when extended hours are enabled
                return self.allow_extended and (
                    kind in {"Pre", "Post", "Overnight", "Other"}
                )

            in_any = any(
                beg <= hhmm <= end and allowed(kind) for beg, end, kind in sessions
            )
            if not in_any:
                allowed_kinds = {k for _, _, k in sessions if allowed(k)}
                win = (
                    ", ".join(
                        [
                            f"{beg:04d}-{end:04d}({k})"
                            for beg, end, k in sessions
                            if k in allowed_kinds
                        ]
                    )
                    or "无"
                )
                raise RuntimeError(f"不在允许的交易时段：{win}")
            return

        # 3) Fallback: rough local time string check (original logic)
        now_local = datetime.now().strftime("%H:%M")
        if not (
            self.limits.trading_window_start
            <= now_local
            <= self.limits.trading_window_end
        ):
            raise RuntimeError(
                f"不在交易时段 {self.limits.trading_window_start}-{self.limits.trading_window_end}（降级判定）"
            )

    def _check_lot(self, symbol: str, qty: int) -> None:
        """Check if quantity is valid lot size."""
        sec = self.quote.static_info([symbol])[0]
        lot = max(1, sec.lot_size or 1)
        if qty % lot != 0:
            raise RuntimeError(f"{symbol} 数量需为最小交易单位 {lot} 的整数倍")

    # ---------- Order placement (market order equal weight example) ----------
    def place_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        dry_run: bool = True,
        est_px: float | None = None,
    ) -> dict:
        """Place order with risk controls.

        Args:
            symbol: Stock symbol
            qty: Quantity to trade
            side: Order side (BUY/SELL)
            dry_run: If True, only simulate the order

        Returns:
            Order result dictionary
        """
        if qty <= 0:
            raise ValueError("下单数量必须为正")

        symbol_formatted = _to_lb_symbol(symbol)

        # Dry run or TEST: skip time window check, but keep lot and amount estimation
        if dry_run:
            lot = self.lot_size(symbol_formatted)
            if qty % lot != 0:
                raise RuntimeError(
                    f"{symbol_formatted} 数量需为最小交易单位 {lot} 的整数倍"
                )
            px = (
                float(est_px)
                if est_px is not None
                else self.quote_last([symbol]).get(symbol_formatted, (0.0, ""))[0]
            )
            notional = px * qty
            # Do not enforce local notional cap in dry run; broker will enforce actual limits.
            if (
                self.limits.max_notional_per_order
                and self.limits.max_notional_per_order > 0
                and notional > self.limits.max_notional_per_order
            ):
                logger.warning(
                    "估算成交金额 %.2f 超过本地预设上限 %.0f，继续（干跑模式不拦截）",
                    notional,
                    self.limits.max_notional_per_order,
                )
            return {
                "env": self.env.value,
                "dry_run": True,
                "symbol": symbol_formatted,
                "qty": qty,
                "side": side,
                "est_px": px,
                "est_notional": notional,
                "ts": time.time(),
            }

        # Real order: strict checks
        self._check_window(symbol_formatted)  # Original logic called here again
        self._check_lot(symbol_formatted, qty)
        if self.limits.max_qty_per_order and qty > self.limits.max_qty_per_order:
            raise RuntimeError(f"超过单笔数量上限 {self.limits.max_qty_per_order}")
        px = (
            float(est_px)
            if est_px is not None
            else self.quote_last([symbol]).get(symbol_formatted, (0.0, ""))[0]
        )
        notional = px * qty
        # Do not enforce local notional cap; rely on broker-side risk control instead.
        if (
            self.limits.max_notional_per_order
            and self.limits.max_notional_per_order > 0
            and notional > self.limits.max_notional_per_order
        ):
            logger.warning(
                "估算成交金额 %.2f 超过本地预设上限 %.0f，继续下单（以券商风控为准）",
                notional,
                self.limits.max_notional_per_order,
            )

        # TODO: Call LongPort real order interface (left blank to avoid accidental triggering)
        return {
            "env": self.env.value,
            "dry_run": False,
            "symbol": symbol_formatted,
            "qty": qty,
            "side": side,
            "est_px": px,
            "est_notional": notional,
            "ts": time.time(),
            "order_id": "SIMULATED_ID",
        }

    def close(self):
        """Close quote and trade contexts (fault-tolerant, does not depend on whether SDK provides close)."""
        for ctx in (self.quote, self.trade):
            try:
                fn = getattr(ctx, "close", None)
                if callable(fn):
                    fn()
            except Exception:
                # Ignore close exceptions to avoid affecting main flow
                pass
        # Restore environment variables to avoid affecting subsequent instances or other usage in processes
        try:
            for k, v in (getattr(self, "_prev_env", {}) or {}).items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        except Exception:
            # Any restoration failure should not affect the caller
            pass
