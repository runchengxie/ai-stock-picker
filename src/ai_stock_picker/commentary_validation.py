"""Fail-closed validation for customer-visible AI commentary."""

from __future__ import annotations

import ipaddress
import re
import unicodedata

from .candidate_models import Candidate
from .commentary_contract import FIELD_ALIASES
from .contracts import Market

_CJK_IDEOGRAPH = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")
_CYRILLIC_OR_GREEK = re.compile(
    r"[\u0370-\u03ff\u0400-\u052f\u1f00-\u1fff\u2de0-\u2dff\ua640-\ua69f]"
)
_UNDERSCORED_IDENTIFIER = re.compile(
    r"(?i)(?<![a-z0-9_])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![a-z0-9_])"
)
_SENTENCE_TERMINATORS = frozenset("。！？!?；;\n")
_SCHEME_OR_WWW = re.compile(r"(?i)(?:https?://|www\.|(?:ftp|mailto):)")
_EMAIL_PATTERN = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w.-]+\.[^\W_]{2,}(?!\w)")
_IPV4_CANDIDATE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_IPV6_CANDIDATE = re.compile(
    r"(?i)(?<![0-9a-f:])(?:\[[0-9a-f:.%]+\]|[0-9a-f:.%]*:[0-9a-f:.%]+)"
    r"(?![0-9a-f:])"
)
_BARE_HOST_CANDIDATE = re.compile(
    r"(?<![\w.-])[\w-]+(?:\.[\w-]+)+(?![\w-])",
    re.UNICODE,
)
_DOMAIN_IN_CONTEXT = re.compile(
    r"(?i)(?:详情见|访问|链接(?:为|至)?|domain|website|site)\s*"
    r"(?:[\w-]{1,63}(?:\.|。))+[\w-]{2,63}(?:[/][^\s，。；！？]*)?"
)
_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(?:\bsk-[a-z0-9_-]{8,}|\bAIza[a-z0-9_-]{10,}|"
    r"\bgh[pousr]_[a-z0-9]{10,})"
)
_STRUCTURED_METADATA_PATTERN = re.compile(
    r"(?ix)\b(?:provider|model)(?:\s*[/_-]\s*(?:provider|model))?"
    r"\s*[_ -]?(?:id|name|identifier|metadata)\b|"
    r"\b(?:api\s*)?endpoint\b|"
    r"\b(?:prompt|response|request)\s*[_ -]?"
    r"(?:sha(?:-?256)?|hash|digest)\b|"
    r"(?:供应商|模型)(?:[/／](?:供应商|模型))?"
    r"(?:id|标识|标识符|编号|名称|元数据)|"
    r"(?:接口|API)?端点|(?:提示词|响应|请求)(?:哈希|摘要)|"
    r"\b(?:generated|written|produced)\s+by\s+(?:an?\s+)?"
    r"(?:(?:(?:large\s+)?language|ai)\s+model|model|llm)\b|"
    r"(?:由|通过|使用|调用)"
    r"(?:语言模型|AI模型|人工智能模型|大语言模型|大模型|模型|LLM)"
    r"(?:生成|撰写|输出)(?:这段)?(?:解读|文本|说明)?"
)
_TRADE_OR_PROMISE_PATTERN = re.compile(
    r"(?i)\b(?:buy(?:ing)?|sell(?:ing)?|hold(?:ing)?|overweight|underweight|"
    r"price\s+target|target\s+price|"
    r"recommend(?:ed|ation)?|accumulate|buy\s+the\s+dip|take\s+a\s+position|"
    r"portfolio\s+allocation|position\s+sizing|enter\s+the\s+trade|"
    r"(?:investors?\s+should\s+)?go\s+long|add\s+to\s+(?:the\s+)?portfolio|"
    r"(?:increas(?:e|ing)|rais(?:e|ing)|boost(?:ing)?|add(?:ing)?|expand(?:ing)?)\s+"
    r"(?:portfolio\s+)?(?:exposure|allocation|position(?:\s+size)?)|"
    r"guaranteed?\s+(?:return|profit|gain)|risk[- ]free\s+return)\b|"
    r"买入|买进|卖出|卖掉|持有|加仓|减仓|建仓|清仓|做多|做空|抄底|追涨|低吸|"
    r"逢低布局|择机布局|长期持仓|纳入组合|重仓|仓位|配置|介入|参与|推荐|增配|"
    r"(?:提高|增加|提升|扩大)(?:仓位|敞口|配置)|"
    r"目标价|目标价格|止盈价|止损价|保证收益|保证回报|稳赚|必赚|必涨|保本|"
    r"无风险收益|投资建议|操作建议"
)
_EXTERNAL_CLAIM_PATTERN = re.compile(
    r"(?i)\b(?:according\s+to|fundamentals?|earnings|revenue|analysts?|"
    r"production\s+capacity|order\s+backlog|sales\s+orders?|profits?|"
    r"company\s+announcement|regulatory\s+filing|government\s+policy|"
    r"customer\s+demand|market\s+demand|competitive\s+landscape|competition|"
    r"industry\s+outlook|management\s+risk|business\s+diversification|"
    r"reports?\s+(?:show|say)|news\s+(?:shows?|says?)|will|expected\s+to)\b|"
    r"基本面|财报显示|公告显示|新闻显示|媒体报道|分析师认为|行业景气|管理风险|"
    r"业务多元|产能|订单|业绩|营收|营业收入|利润|盈利|公告|政策|"
    r"客户需求|市场需求|外部需求|竞争格局|竞争态势|供不应求|产销两旺|订单饱满|"
    r"已经核实|已独立核验|事实证明|预计|有望|将会"
)
_NEGATED_OR_SUBJECTIVE_GROUNDING = re.compile(
    r"(?i)\b(?:does?\s+not|cannot|can't|fails?\s+to)\s+support\b|"
    r"\bnot\s+(?:based|grounded)\s+on\b|"
    r"\bnot\s+(?:the\s+)?(?:ranking\s+)?basis\b|"
    r"\b(?:intuition|personal\s+judgment|own\s+judgment|"
    r"subjective(?:\s+(?:view|judgment))?|gut\s+feeling)\b|"
    r"并不支持|不支持|无法支持|不能支持|不足以支持|未能支持|"
    r"(?:并非|不是|不构成|不作为).{0,20}(?:排序)?依据|"
    r"(?:与|和).{0,20}(?:排序|结论).{0,8}无关|"
    r"主观|直觉|凭感觉|个人判断|自行判断"
)
_FORBIDDEN_RISK_SCORE_PATTERN = re.compile(r"(?i)\brisk[_ -]?score\b|风险分")
_STABILITY_HIGH_INVERSION = re.compile(
    r"(?is)(?:intraday_stability_score|intraday\s+stability|日内波动稳定性)"
    r".{0,100}(?:higher|\bhigh\b|high(?:er)?\s+value|越高|较高|高值|值越大|高)"
    r".{0,60}(?:(?:high|higher|more|greater)\s+risk|riskier|"
    r"(?:more|increasingly)\s+volatile|higher\s+volatility|"
    r"(?:less|decreasingly)\s+stable|unstable|"
    r"风险越高|风险更高|风险更大|高风险|波动越大|波动更大|波动越高|波动更高|"
    r"越不稳定|更不稳定|不稳定|稳定性更低)"
)
_STABILITY_LOW_INVERSION = re.compile(
    r"(?is)(?:intraday_stability_score|intraday\s+stability|日内波动稳定性)"
    r".{0,100}(?:lower|\blow\b|low(?:er)?\s+value|越低|较低|低值|值越小|低)"
    r".{0,60}(?:(?:low|lower|less)\s+risk|risk\s+is\s+(?:low|lower)|"
    r"less\s+volatile|lower\s+volatility|(?:more|increasingly)\s+stable|"
    r"higher\s+stability|"
    r"风险低|风险越低|风险更低|风险较低|低风险|波动越小|波动更小|波动较小|"
    r"越稳定|更稳定|稳定性更高)"
)
_STABILITY_PREFIX_HIGH_INVERSION = re.compile(
    r"(?is)(?:higher|\bhigh\b|越高|较高|高值)(?:\s+|的\s*)"
    r"(?:intraday_stability_score|intraday\s+stability|日内波动稳定性)"
    r".{0,60}(?:(?:high|higher|more|greater)\s+risk|riskier|"
    r"(?:more|increasingly)\s+volatile|higher\s+volatility|"
    r"(?:less|decreasingly)\s+stable|unstable|"
    r"风险越高|风险更高|风险更大|高风险|波动越大|波动更大|波动越高|波动更高|"
    r"越不稳定|更不稳定|不稳定|稳定性更低)"
)
_STABILITY_PREFIX_LOW_INVERSION = re.compile(
    r"(?is)(?:lower|\blow\b|越低|较低|低值)(?:\s+|的\s*)"
    r"(?:intraday_stability_score|intraday\s+stability|日内波动稳定性)"
    r".{0,60}(?:(?:low|lower|less)\s+risk|risk\s+is\s+(?:low|lower)|"
    r"less\s+volatile|lower\s+volatility|(?:more|increasingly)\s+stable|"
    r"higher\s+stability|风险低|风险越低|风险更低|风险较低|低风险|"
    r"波动越小|波动更小|波动较小|越稳定|更稳定|稳定性更高)"
)
_FORBIDDEN_COMPACT_TERMS = frozenset(
    {
        "anthropic",
        "apikey",
        "bearertoken",
        "chatgpt",
        "claude",
        "credential",
        "deepseek",
        "gemini",
        "openai",
        "password",
        "secret",
        "token",
        "密码",
        "秘钥",
        "密钥",
        "凭据",
        "令牌",
    }
)
_KNOWN_GROUNDING_FIELDS = frozenset(FIELD_ALIASES)
_VALUE_BOUND_FIELDS = frozenset(
    {
        "confidence_label",
        "industry",
        "name",
        "sector",
        "source_concepts",
        "source_topics",
        "symbol",
        "topic",
    }
)
_CATEGORICAL_FIELDS = frozenset(
    {
        "confidence_label",
        "industry",
        "sector",
        "source_concepts",
        "source_topics",
        "topic",
    }
)
_CATEGORY_CONNECTOR = re.compile(r"(?i)\s*(?:和|与|及|以及|、|\band\b|\bor\b)\s*")
_SENSITIVE_CATEGORY_REFERENCE = re.compile(
    r"(?i)大模型(?:推理需求|应用|生态|主题|概念)?|"
    r"供应商(?:应用|生态|主题|概念)|"
    r"\b(?:LLM|AI\s+model)\s+(?:application|ecosystem|theme|concept)s?\b"
)


def validate_customer_commentary(
    field: str,
    value: str,
    candidate: Candidate,
    *,
    market: Market,
    provider: str,
    model: str,
) -> None:
    """Validate one commentary field against language, policy, and candidate data."""

    normalized = unicodedata.normalize("NFKC", value)
    _require_market_language(field, normalized, market)
    available_fields = {"symbol", "name", "topic", "score", *candidate.features}
    _reject_forbidden_content(field, normalized)

    unknown_identifiers = {
        match.group(0).casefold()
        for match in _UNDERSCORED_IDENTIFIER.finditer(normalized)
    } - _KNOWN_GROUNDING_FIELDS
    if unknown_identifiers:
        raise ValueError(
            f"provider output {field} cites an unsupported candidate field"
        )

    sentences = _split_grounding_sentences(normalized)
    if not sentences:
        raise ValueError(f"provider output {field} has no grounded sentence")
    for sentence in sentences:
        mentioned_fields = _mentioned_grounding_fields(sentence, market)
        if not mentioned_fields:
            raise ValueError(
                f"provider output {field} has a sentence without a supplied "
                "candidate-field basis"
            )
        if mentioned_fields - available_fields:
            raise ValueError(
                f"provider output {field} cites a field absent from its candidate"
            )
        _require_candidate_values(field, sentence, candidate, mentioned_fields)
        _reject_unsupplied_sensitive_categories(field, sentence, candidate)

    _reject_system_metadata_terms(field, normalized, provider, model)


def validate_legacy_customer_commentary(
    field: str,
    value: str,
    *,
    market: Market,
    provider: str,
    model: str,
) -> None:
    """Apply customer-safety checks without imposing the current grounding policy."""

    normalized = unicodedata.normalize("NFKC", value)
    _require_market_language(field, normalized, market)
    _reject_legacy_safety_content(field, normalized)
    _reject_system_metadata_terms(field, normalized, provider, model)


def _reject_system_metadata_terms(
    field: str,
    value: str,
    provider: str,
    model: str,
) -> None:
    compact = _compact_for_policy_scan(value)
    dynamic_terms = {
        compact_term
        for raw_term in (provider, model)
        if len(compact_term := _compact_for_policy_scan(raw_term)) >= 4
    }
    if any(
        term and term in compact for term in _FORBIDDEN_COMPACT_TERMS | dynamic_terms
    ):
        raise ValueError(f"provider output {field} contains forbidden system metadata")


def _require_market_language(field: str, value: str, market: Market) -> None:
    if market == "CN" and _CJK_IDEOGRAPH.search(value) is None:
        raise ValueError(
            f"CN provider output {field} must use Simplified Chinese and contain "
            "at least one CJK ideograph"
        )
    if market == "US" and (
        _LATIN_LETTER.search(value) is None or _CJK_IDEOGRAPH.search(value)
    ):
        raise ValueError(f"US provider output {field} must use English")


def _reject_forbidden_content(field: str, value: str) -> None:
    if _CYRILLIC_OR_GREEK.search(value):
        raise ValueError(f"provider output {field} contains confusable script text")
    if _contains_url_email_or_ip(value) or _SECRET_VALUE_PATTERN.search(value):
        raise ValueError(f"provider output {field} contains a URL, address, or secret")
    if _STRUCTURED_METADATA_PATTERN.search(value):
        raise ValueError(f"provider output {field} contains structured system metadata")
    if _FORBIDDEN_RISK_SCORE_PATTERN.search(value):
        raise ValueError(f"provider output {field} uses the forbidden risk-score label")
    if any(
        pattern.search(value)
        for pattern in (
            _STABILITY_HIGH_INVERSION,
            _STABILITY_LOW_INVERSION,
            _STABILITY_PREFIX_HIGH_INVERSION,
            _STABILITY_PREFIX_LOW_INVERSION,
        )
    ):
        raise ValueError(f"provider output {field} reverses stability semantics")
    if _NEGATED_OR_SUBJECTIVE_GROUNDING.search(value):
        raise ValueError(f"provider output {field} negates its candidate-field basis")
    if _TRADE_OR_PROMISE_PATTERN.search(value):
        raise ValueError(
            f"provider output {field} contains trading advice or a return promise"
        )
    if _EXTERNAL_CLAIM_PATTERN.search(value):
        raise ValueError(
            f"provider output {field} contains an external or future claim"
        )


def _reject_legacy_safety_content(field: str, value: str) -> None:
    if _CYRILLIC_OR_GREEK.search(value):
        raise ValueError(f"provider output {field} contains confusable script text")
    if _contains_url_email_or_ip(value) or _SECRET_VALUE_PATTERN.search(value):
        raise ValueError(f"provider output {field} contains a URL, address, or secret")
    if _STRUCTURED_METADATA_PATTERN.search(value):
        raise ValueError(f"provider output {field} contains structured system metadata")
    if _FORBIDDEN_RISK_SCORE_PATTERN.search(value):
        raise ValueError(f"provider output {field} uses the forbidden risk-score label")
    if any(
        pattern.search(value)
        for pattern in (
            _STABILITY_HIGH_INVERSION,
            _STABILITY_LOW_INVERSION,
            _STABILITY_PREFIX_HIGH_INVERSION,
            _STABILITY_PREFIX_LOW_INVERSION,
        )
    ):
        raise ValueError(f"provider output {field} reverses stability semantics")
    if _TRADE_OR_PROMISE_PATTERN.search(value):
        raise ValueError(
            f"provider output {field} contains trading advice or a return promise"
        )


def _mentioned_grounding_fields(value: str, market: Market) -> set[str]:
    return {
        field
        for field in _KNOWN_GROUNDING_FIELDS
        if _contains_field_reference(value, field)
        or any(
            _contains_literal_reference(value, alias)
            for alias in FIELD_ALIASES[field][market]
        )
    }


def _require_candidate_values(
    output_field: str,
    sentence: str,
    candidate: Candidate,
    mentioned_fields: set[str],
) -> None:
    for candidate_field in mentioned_fields & _VALUE_BOUND_FIELDS:
        values = _candidate_values(candidate, candidate_field)
        if not values or not any(
            _contains_literal_reference(sentence, value) for value in values
        ):
            raise ValueError(
                f"provider output {output_field} does not bind {candidate_field} "
                "to a supplied candidate value"
            )
        if candidate_field in _CATEGORICAL_FIELDS:
            _reject_unknown_coordinated_values(
                output_field,
                sentence,
                candidate_field,
                values,
            )


def _candidate_values(candidate: Candidate, field: str) -> tuple[str, ...]:
    top_level: dict[str, object] = {
        "symbol": candidate.symbol,
        "name": candidate.name,
        "topic": candidate.topic,
    }
    raw = top_level.get(field, candidate.features.get(field))
    if isinstance(raw, str):
        return (raw,) if raw else ()
    if isinstance(raw, list):
        return tuple(str(item) for item in raw if str(item))
    return ()


def _reject_unknown_coordinated_values(
    output_field: str,
    sentence: str,
    candidate_field: str,
    values: tuple[str, ...],
) -> None:
    normalized_sentence = unicodedata.normalize("NFKC", sentence).casefold()
    normalized_values = tuple(
        unicodedata.normalize("NFKC", value).casefold() for value in values
    )
    for connector in _CATEGORY_CONNECTOR.finditer(normalized_sentence):
        left = normalized_sentence[: connector.start()].rstrip()
        right = normalized_sentence[connector.end() :].lstrip()
        left_is_value = any(left.endswith(value) for value in normalized_values)
        right_is_value = any(right.startswith(value) for value in normalized_values)
        if left_is_value != right_is_value:
            raise ValueError(
                f"provider output {output_field} coordinates an unsupported "
                f"{candidate_field} value"
            )


def _reject_unsupplied_sensitive_categories(
    output_field: str,
    sentence: str,
    candidate: Candidate,
) -> None:
    supplied_values = {
        unicodedata.normalize("NFKC", value).casefold()
        for field in _CATEGORICAL_FIELDS
        for value in _candidate_values(candidate, field)
    }
    for match in _SENSITIVE_CATEGORY_REFERENCE.finditer(sentence):
        reference = unicodedata.normalize("NFKC", match.group(0)).casefold()
        if reference not in supplied_values:
            raise ValueError(
                f"provider output {output_field} contains an unsupported categorical "
                "value"
            )


def _split_grounding_sentences(value: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    for index, character in enumerate(value):
        if character == "." and _period_is_inside_data_token(value, index):
            continue
        if character != "." and character not in _SENTENCE_TERMINATORS:
            continue
        sentence = value[start:index].strip(" \t\r,，:：")
        if sentence:
            sentences.append(sentence)
        start = index + 1
    tail = value[start:].strip(" \t\r,，:：")
    if tail:
        sentences.append(tail)
    return sentences


def _period_is_inside_data_token(value: str, index: int) -> bool:
    before = value[:index]
    after = value[index + 1 :]
    if before[-1:].isdigit() and after[:1].isdigit():
        return True
    if re.search(r"\d{6}$", before) and re.match(r"(?i)(?:SH|SZ|BJ)\b", after):
        return True
    return bool(
        re.search(r"\b[A-Z][A-Z0-9]*$", before) and re.match(r"[A-Z0-9]+\b", after)
    )


def _contains_field_reference(value: str, field: str) -> bool:
    return (
        re.search(
            rf"(?i)(?<![a-z0-9_]){re.escape(field)}(?![a-z0-9_])",
            value,
        )
        is not None
    )


def _contains_literal_reference(value: str, literal: str) -> bool:
    normalized = unicodedata.normalize("NFKC", literal)
    left = (
        r"(?<![a-z0-9])" if normalized[0].isascii() and normalized[0].isalnum() else ""
    )
    right = (
        r"(?![a-z0-9])" if normalized[-1].isascii() and normalized[-1].isalnum() else ""
    )
    return re.search(rf"(?i){left}{re.escape(normalized)}{right}", value) is not None


def _contains_url_email_or_ip(value: str) -> bool:
    if (
        _SCHEME_OR_WWW.search(value)
        or _EMAIL_PATTERN.search(value)
        or _DOMAIN_IN_CONTEXT.search(value)
    ):
        return True
    for pattern in (_IPV4_CANDIDATE, _IPV6_CANDIDATE):
        for match in pattern.finditer(value):
            candidate = match.group(0).strip("[]().,;")
            try:
                ipaddress.ip_address(candidate)
            except ValueError:
                continue
            return True
    for match in _BARE_HOST_CANDIDATE.finditer(value):
        candidate = match.group(0)
        if re.search(r"\d+(?:\.\d+)+$", candidate):
            continue
        if re.search(r"(?i)\d{6}\.(?:SH|SZ|BJ)$", candidate):
            continue
        labels = candidate.split(".")
        if len(labels[-1]) >= 2 and labels[-1].isalpha():
            return True
    return False


def _compact_for_policy_scan(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    without_marks = "".join(
        character for character in normalized if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"[\W_]+", "", without_marks)


__all__ = ["validate_customer_commentary", "validate_legacy_customer_commentary"]
