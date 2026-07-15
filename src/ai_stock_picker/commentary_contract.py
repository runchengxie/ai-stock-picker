"""Natural-language grounding labels and prompt policy for customer commentary."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import Market

FIELD_ALIASES: dict[str, dict[Market, tuple[str, ...]]] = {
    "amount_ratio_20d": {
        "CN": ("20日成交额比率", "20日成交额特征"),
        "US": ("20-day amount ratio", "20-day turnover ratio"),
    },
    "close_to_20d_high": {
        "CN": ("距20日高点", "20日高点距离"),
        "US": ("proximity to the 20-day high", "distance from the 20-day high"),
    },
    "confidence_label": {
        "CN": ("候选置信标签",),
        "US": ("candidate confidence label",),
    },
    "daily_confirm_score": {
        "CN": ("日线确认特征", "日度确认特征"),
        "US": ("daily confirmation signal",),
    },
    "industry": {"CN": ("行业标签",), "US": ("industry label",)},
    "intraday_stability_score": {
        "CN": ("日内波动稳定性",),
        "US": ("intraday stability", "intraday stability signal"),
    },
    "liquidity_score": {
        "CN": ("流动性特征",),
        "US": ("liquidity signal",),
    },
    "name": {"CN": ("股票名称",), "US": ("company name", "stock name")},
    "relevance": {"CN": ("主题相关性",), "US": ("topic relevance",)},
    "ret_10d": {"CN": ("近10日表现",), "US": ("10-day performance",)},
    "ret_5d": {"CN": ("近5日表现",), "US": ("5-day performance",)},
    "score": {
        "CN": ("综合候选评分", "综合评分"),
        "US": ("overall candidate score", "candidate score"),
    },
    "sector": {"CN": ("板块标签",), "US": ("sector label",)},
    "source_concepts": {
        "CN": ("关联概念",),
        "US": ("related concepts", "source concepts"),
    },
    "source_topics": {
        "CN": ("热点主题",),
        "US": ("source topics", "hot topics"),
    },
    "symbol": {"CN": ("股票代码",), "US": ("ticker symbol",)},
    "topic": {"CN": ("候选主题",), "US": ("candidate topic",)},
    "trend_score": {"CN": ("趋势特征",), "US": ("trend signal",)},
    "volume_score": {"CN": ("量能特征",), "US": ("volume signal",)},
}

COMMENTARY_POLICY = {
    "kind": "ai_interpretation",
    "independent_fact_check": "not_performed",
    "customer_disclaimer": (
        "AI interpretation based only on supplied candidate fields; "
        "not independently fact-checked."
    ),
}

FEATURE_SEMANTICS = {
    "intraday_stability_score": (
        "The upstream risk_score is projected into intraday_stability_score before "
        "candidate data reaches the prompt. Higher means more stable intraday price "
        "behavior; never interpret a higher value as higher risk."
    )
}


def preferred_commentary_labels(
    available_fields: Iterable[str],
    market: Market,
) -> dict[str, str]:
    """Return one customer-facing label for each supplied candidate field."""

    return {
        field: FIELD_ALIASES[field][market][0]
        for field in sorted(set(available_fields))
        if field in FIELD_ALIASES
    }


__all__ = [
    "COMMENTARY_POLICY",
    "FEATURE_SEMANTICS",
    "FIELD_ALIASES",
    "preferred_commentary_labels",
]
