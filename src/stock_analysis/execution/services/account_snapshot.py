"""Account snapshot service

Provides business logic for account snapshots, returning structured data.
"""

from __future__ import annotations

try:
    from ..broker.longport_client import LongPortClient
except ImportError:  # pragma: no cover - allow tests without LongPort dependencies
    LongPortClient = None  # type: ignore
from ...shared.models import AccountSnapshot, Position, Quote
from ...shared.utils.fx import to_usd
from ...shared.logging import get_logger

logger = get_logger(__name__)


def get_account_snapshot(
    env: str = "real",
    include_quotes: bool = True,
    pre_quotes: dict[str, tuple[float, str]] | None = None,
    client: LongPortClient | None = None,
) -> AccountSnapshot:
    """Get account snapshot

    Args:
        env: Environment selection (only 'real' is supported, parameter kept for compatibility)

    Returns:
        AccountSnapshot: Account snapshot data

    Raises:
        Exception: When unable to retrieve account data
    """
    try:
        created_here = False
        if client is None:
            if LongPortClient is None:  # pragma: no cover - guards missing dependency
                raise ImportError(
                    "LongPort client library is not installed"
                )
            client = LongPortClient(env=env)
            created_here = True
        cash_usd, stock_position_map, net_assets, base_ccy = client.portfolio_snapshot()

        # Stock position quotes: can choose not to fetch, or use externally provided cache
        stock_quotes: dict[str, tuple[float, str]] = {}
        if include_quotes and not pre_quotes:
            if stock_position_map:
                stock_quotes = client.quote_last(list(stock_position_map.keys()))
        else:
            stock_quotes = pre_quotes or {}

        positions: list[Position] = []

        # Stock positions -> Position
        for symbol, quantity in stock_position_map.items():
            price, _ = stock_quotes.get(symbol, (0.0, ""))
            positions.append(
                Position(
                    symbol=symbol,
                    quantity=int(quantity),
                    last_price=float(price),
                    estimated_value=int(quantity) * float(price),
                    env=env,
                )
            )

        # Fund positions -> Position (using NAV as price)
        fund_map = client.fund_positions()
        for fsymbol, (units, nav, _ccy) in fund_map.items():
            qty_int = int(
                units
            )  # Position.quantity is int; can be extended to float for more precision
            positions.append(
                Position(
                    symbol=fsymbol,
                    quantity=qty_int,
                    last_price=float(nav),
                    estimated_value=units * float(nav),
                    env=env,
                )
            )

        if created_here:
            client.close()

        # Pass through total assets:
        # - If net assets are in USD, use directly
        # - If not USD, try to convert to USD using FX; return 0 on failure to trigger upper-level recalculation
        tpv = 0.0
        if net_assets:
            if str(base_ccy).upper() == "USD":
                tpv = float(net_assets)
            else:
                converted = to_usd(float(net_assets), str(base_ccy))
                tpv = float(converted) if converted is not None else 0.0
        return AccountSnapshot(
            env=env,
            cash_usd=cash_usd,
            positions=positions,
            total_portfolio_value=tpv,
            base_currency=str(base_ccy).upper() if base_ccy else None,
        )

    except ImportError as e:  # Surface missing dependency clearly
        logger.error(f"Failed to import LongPort module: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to get account data: {e}")
        raise RuntimeError(f"Failed to get account data: {e}") from e


def get_multiple_account_snapshots(envs: list[str]) -> list[AccountSnapshot]:
    """Get account snapshots for multiple environments."""
    return [get_account_snapshot(env=env) for env in envs]


def get_quotes(
    symbols: list[str], client: LongPortClient | None = None
) -> dict[str, Quote]:
    """Get stock quotes

    Args:
        symbols: List of stock symbols
        env: Environment selection

    Returns:
        Dict[str, Quote]: Mapping from stock symbols to quotes

    Raises:
        Exception: When unable to retrieve quotes
    """
    try:
        created_here = False
        if client is None:
            if LongPortClient is None:  # pragma: no cover
                raise ImportError("LongPort client library is not installed")
            client = LongPortClient()
            created_here = True
        quote_data = client.quote_last(symbols)
        if created_here:
            client.close()

        quotes = {}
        for symbol, (price, timestamp) in quote_data.items():
            quotes[symbol] = Quote(
                symbol=symbol, price=float(price), timestamp=timestamp
            )

        return quotes

    except ImportError as e:  # pragma: no cover - same reason as above
        logger.error(f"Failed to import LongPort module: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to get quotes: {e}")
        raise
