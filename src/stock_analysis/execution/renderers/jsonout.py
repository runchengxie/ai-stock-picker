"""JSON renderer

Provides JSON format data rendering functionality.
"""

import json
from typing import Any

from ...shared.models import AccountSnapshot, Order, Quote, RebalanceResult


def _serialize_dataclass(obj: Any) -> dict[str, Any]:
    """Serialize dataclass object to dictionary

    Args:
        obj: Object to serialize

    Returns:
        Dict[str, Any]: Serialized dictionary
    """
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for field_name in obj.__dataclass_fields__:
            value = getattr(obj, field_name)
            if hasattr(value, "__dataclass_fields__"):
                result[field_name] = _serialize_dataclass(value)
            elif isinstance(value, list):
                result[field_name] = [
                    _serialize_dataclass(item)
                    if hasattr(item, "__dataclass_fields__")
                    else item
                    for item in value
                ]
            elif hasattr(value, "isoformat"):  # datetime objects
                result[field_name] = value.isoformat()
            else:
                result[field_name] = value
        return result
    return obj


def render_quotes_json(quotes: list[Quote]) -> str:
    """Render stock quotes JSON

    Args:
        quotes: List of quotes

    Returns:
        str: JSON string
    """
    data = [_serialize_dataclass(quote) for quote in quotes]
    return json.dumps(data, ensure_ascii=False, indent=2)


def render_account_snapshot_json(snapshot: AccountSnapshot) -> str:
    """Render account snapshot JSON

    Args:
        snapshot: Account snapshot

    Returns:
        str: JSON string
    """
    data = _serialize_dataclass(snapshot)
    return json.dumps(data, ensure_ascii=False, indent=2)


def render_multiple_account_snapshots_json(snapshots: list[AccountSnapshot]) -> str:
    """Render multiple account snapshots JSON

    Args:
        snapshots: List of account snapshots

    Returns:
        str: JSON string
    """
    data = [_serialize_dataclass(snapshot) for snapshot in snapshots]
    return json.dumps(data, ensure_ascii=False, indent=2)


def render_rebalance_result_json(result: RebalanceResult) -> str:
    """Render rebalance result JSON

    Args:
        result: Rebalance result

    Returns:
        str: JSON string
    """
    data = _serialize_dataclass(result)
    return json.dumps(data, ensure_ascii=False, indent=2)


def render_orders_json(orders: list[Order]) -> str:
    """Render order list JSON

    Args:
        orders: List of orders

    Returns:
        str: JSON string
    """
    data = [_serialize_dataclass(order) for order in orders]
    return json.dumps(data, ensure_ascii=False, indent=2)


def render_json(data: Any) -> str:
    """Generic JSON renderer

    Args:
        data: Data to render

    Returns:
        str: JSON string
    """
    if hasattr(data, "__dataclass_fields__"):
        serialized = _serialize_dataclass(data)
    elif isinstance(data, list) and data and hasattr(data[0], "__dataclass_fields__"):
        serialized = [_serialize_dataclass(item) for item in data]
    else:
        serialized = data

    return json.dumps(serialized, ensure_ascii=False, indent=2)
