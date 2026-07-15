"""Natural-language grounding labels and prompt policy for customer commentary."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import ResponseLanguage

FIELD_ALIASES: dict[str, dict[ResponseLanguage, tuple[str, ...]]] = {
    "amount_ratio_20d": {
        "zh-CN": ("20日成交额比率", "20日成交额特征"),
        "en": ("20-day amount ratio", "20-day turnover ratio"),
    },
    "close_to_20d_high": {
        "zh-CN": ("距20日高点", "20日高点距离"),
        "en": ("proximity to the 20-day high", "distance from the 20-day high"),
    },
    "confidence_label": {
        "zh-CN": ("候选置信标签",),
        "en": ("candidate confidence label",),
    },
    "daily_confirm_score": {
        "zh-CN": ("日线确认特征", "日度确认特征"),
        "en": ("daily confirmation signal",),
    },
    "industry": {"zh-CN": ("行业标签",), "en": ("industry label",)},
    "intraday_stability_score": {
        "zh-CN": ("日内波动稳定性",),
        "en": ("intraday stability", "intraday stability signal"),
    },
    "liquidity_score": {
        "zh-CN": ("流动性特征",),
        "en": ("liquidity signal",),
    },
    "name": {"zh-CN": ("股票名称",), "en": ("company name", "stock name")},
    "relevance": {"zh-CN": ("主题相关性",), "en": ("topic relevance",)},
    "ret_10d": {"zh-CN": ("近10日表现",), "en": ("10-day performance",)},
    "ret_5d": {"zh-CN": ("近5日表现",), "en": ("5-day performance",)},
    "score": {
        "zh-CN": ("综合候选评分", "综合评分"),
        "en": ("overall candidate score", "candidate score"),
    },
    "sector": {"zh-CN": ("板块标签",), "en": ("sector label",)},
    "source_concepts": {
        "zh-CN": ("关联概念",),
        "en": ("related concepts", "source concepts"),
    },
    "source_topics": {
        "zh-CN": ("热点主题",),
        "en": ("source topics", "hot topics"),
    },
    "symbol": {"zh-CN": ("股票代码",), "en": ("ticker symbol",)},
    "topic": {"zh-CN": ("候选主题",), "en": ("candidate topic",)},
    "trend_score": {"zh-CN": ("趋势特征",), "en": ("trend signal",)},
    "volume_score": {"zh-CN": ("量能特征",), "en": ("volume signal",)},
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
    response_language: ResponseLanguage,
) -> dict[str, str]:
    """Return one customer-facing label for each supplied candidate field."""

    return {
        field: FIELD_ALIASES[field][response_language][0]
        for field in sorted(set(available_fields))
        if field in FIELD_ALIASES
    }


__all__ = [
    "COMMENTARY_POLICY",
    "FEATURE_SEMANTICS",
    "FIELD_ALIASES",
    "preferred_commentary_labels",
]
