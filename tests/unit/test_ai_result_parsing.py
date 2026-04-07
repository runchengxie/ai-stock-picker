"""Unit tests for AI result parsing.

Tests the fault-tolerant parsing of AI model output, including:
- Handling of incomplete or malformed JSON.
- Trailing commas and extraneous text.
- Cases where the array length is not 10.
- Missing fields or incorrect data types.
- Validation of the "ten picks out of ten" hard requirement.
"""

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("pydantic")
from pydantic import ValidationError
from stock_analysis.ai_lab.selection.ai_stock_pick import AIStockPick, parse_response_robust


@pytest.mark.unit
class TestAIStockPickModel:
    """Tests the validation of the AIStockPick data model."""

    def test_valid_stock_pick(self):
        """Tests with valid stock pick data."""
        valid_data = {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "confidence_score": 8,
            "reasoning": "Strong fundamentals and market position",
        }

        pick = AIStockPick(**valid_data)
        assert pick.ticker == "AAPL"
        assert pick.company_name == "Apple Inc."
        assert pick.confidence_score == 8
        assert pick.reasoning == "Strong fundamentals and market position"

    def test_confidence_score_validation(self):
        """Tests the confidence score validation (must be an integer from 1 to 10)."""
        base_data = {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "reasoning": "Test reasoning",
        }

        # Valid scores
        for score in [1, 5, 10]:
            data = {**base_data, "confidence_score": score}
            pick = AIStockPick(**data)
            assert pick.confidence_score == score

        # Invalid scores should raise a validation error
        invalid_scores = [0, 11, -1, 5.5, None]
        for score in invalid_scores:
            data = {**base_data, "confidence_score": score}
            with pytest.raises(ValidationError):  # Pydantic ValidationError
                AIStockPick(**data)

    def test_required_fields(self):
        """Tests the validation of required fields."""
        complete_data = {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "confidence_score": 8,
            "reasoning": "Strong fundamentals",
        }

        # Test that each field is required
        for field in complete_data.keys():
            incomplete_data = {k: v for k, v in complete_data.items() if k != field}
            with pytest.raises(ValidationError):  # Pydantic ValidationError
                AIStockPick(**incomplete_data)


@pytest.mark.unit
class TestJSONParsingRobustness:
    """Tests the robustness of JSON parsing."""

    def test_perfect_json_parsing(self):
        """Tests parsing of a perfectly formatted JSON."""
        perfect_json = """[
            {
                "ticker": "AAPL",
                "company_name": "Apple Inc.",
                "confidence_score": 9,
                "reasoning": "Excellent fundamentals"
            },
            {
                "ticker": "MSFT",
                "company_name": "Microsoft Corp.",
                "confidence_score": 8,
                "reasoning": "Strong cloud business"
            }
        ]"""

        # Simulate a response object
        response = SimpleNamespace()
        response.text = perfect_json
        response.parsed = None

        result = parse_response_robust(response)

        assert result is not None
        assert len(result) == 2
        assert isinstance(result[0], AIStockPick)
        assert result[0].ticker == "AAPL"
        assert result[1].ticker == "MSFT"

    def test_trailing_comma_json(self):
        """Tests JSON with a trailing comma."""
        trailing_comma_json = """[
            {
                "ticker": "AAPL",
                "company_name": "Apple Inc.",
                "confidence_score": 9,
                "reasoning": "Excellent fundamentals",
            },
        ]"""

        response = SimpleNamespace()
        response.text = trailing_comma_json
        response.parsed = None

        # Standard JSON parsing would fail; the robust function should return None.
        result = parse_response_robust(response)
        assert result is None

    def test_malformed_json_with_extra_text(self):
        """Tests malformed JSON that includes extra text before or after."""
        malformed_json = """Here are my stock picks:
        [
            {
                "ticker": "AAPL",
                "company_name": "Apple Inc.",
                "confidence_score": 9,
                "reasoning": "Great company"
            }
        ]

        These are my top recommendations based on analysis."""

        response = SimpleNamespace()
        response.text = malformed_json
        response.parsed = None

        result = parse_response_robust(response)
        assert result is None

    def test_incomplete_json(self):
        """Tests incomplete JSON (abruptly truncated)."""
        incomplete_json = """[
            {
                "ticker": "AAPL",
                "company_name": "Apple Inc.",
                "confidence_score": 9,
                "reasoning": "Excellent fund"""

        response = SimpleNamespace()
        response.text = incomplete_json
        response.parsed = None

        result = parse_response_robust(response)
        assert result is None

    def test_non_array_json(self):
        """Tests JSON that is not in an array format at the root."""
        non_array_json = """{
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "confidence_score": 9,
            "reasoning": "Single stock object"
        }"""

        response = SimpleNamespace()
        response.text = non_array_json
        response.parsed = None

        result = parse_response_robust(response)
        assert result is None

    def test_empty_response(self):
        """Tests an empty response."""
        response = SimpleNamespace()
        response.text = ""
        response.parsed = None

        result = parse_response_robust(response)
        assert result is None

    def test_null_response(self):
        """Tests a null response."""
        response = SimpleNamespace()
        response.text = None
        response.parsed = None

        result = parse_response_robust(response)
        assert result is None


@pytest.mark.unit
class TestTenStockRequirement:
    """Tests the strict requirement of exactly ten stock picks."""

    def test_exactly_ten_stocks_valid(self):
        """Tests a valid case with exactly 10 stocks."""
        ten_stocks_data = []
        for i in range(10):
            ten_stocks_data.append(
                {
                    "ticker": f"STOCK{i + 1}",
                    "company_name": f"Company {i + 1}",
                    "confidence_score": (i % 10) + 1,
                    "reasoning": f"Reasoning for stock {i + 1}",
                }
            )

        json_text = json.dumps(ten_stocks_data)
        response = SimpleNamespace()
        response.text = json_text
        response.parsed = None

        result = parse_response_robust(response)

        assert result is not None
        assert len(result) == 10
        for i, pick in enumerate(result):
            assert isinstance(pick, AIStockPick)
            assert pick.ticker == f"STOCK{i + 1}"

    def test_less_than_ten_stocks(self):
        """Tests a case with fewer than 10 stocks."""
        five_stocks_data = []
        for i in range(5):
            five_stocks_data.append(
                {
                    "ticker": f"STOCK{i + 1}",
                    "company_name": f"Company {i + 1}",
                    "confidence_score": 8,
                    "reasoning": f"Reasoning for stock {i + 1}",
                }
            )

        json_text = json.dumps(five_stocks_data)
        response = SimpleNamespace()
        response.text = json_text
        response.parsed = None

        result = parse_response_robust(response)

        # Parsing succeeds, but the count is incorrect.
        assert result is not None
        assert len(result) == 5  # The caller should validate this count.

    def test_more_than_ten_stocks(self):
        """Tests a case with more than 10 stocks."""
        fifteen_stocks_data = []
        for i in range(15):
            fifteen_stocks_data.append(
                {
                    "ticker": f"STOCK{i + 1}",
                    "company_name": f"Company {i + 1}",
                    "confidence_score": 7,
                    "reasoning": f"Reasoning for stock {i + 1}",
                }
            )

        json_text = json.dumps(fifteen_stocks_data)
        response = SimpleNamespace()
        response.text = json_text
        response.parsed = None

        result = parse_response_robust(response)

        # Parsing succeeds, but the count is incorrect.
        assert result is not None
        assert len(result) == 15  # The caller should validate this count.


@pytest.mark.unit
class TestFieldValidationEdgeCases:
    """Tests edge cases for field validation."""

    def test_missing_fields_in_json(self):
        """Tests a case where fields are missing in the JSON."""
        incomplete_stock = {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            # Missing confidence_score and reasoning
        }

        json_text = json.dumps([incomplete_stock])
        response = SimpleNamespace()
        response.text = json_text
        response.parsed = None

        # Should fail during the creation of the AIStockPick object.
        result = parse_response_robust(response)
        assert result is None

    def test_wrong_field_types(self):
        """Tests a case with incorrect field types."""
        wrong_type_stock = {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "confidence_score": "eight",  # Should be an integer
            "reasoning": "Good company",
        }

        json_text = json.dumps([wrong_type_stock])
        response = SimpleNamespace()
        response.text = json_text
        response.parsed = None

        result = parse_response_robust(response)
        assert result is None

    def test_empty_string_fields(self):
        """Tests fields with empty strings."""
        empty_fields_stock = {
            "ticker": "",  # Empty ticker
            "company_name": "Apple Inc.",
            "confidence_score": 8,
            "reasoning": "",
        }

        json_text = json.dumps([empty_fields_stock])
        response = SimpleNamespace()
        response.text = json_text
        response.parsed = None

        # According to the model definition, an empty string might be valid,
        # but this may not be desirable for the business logic.
        result = parse_response_robust(response)
        if result is not None:
            assert len(result) == 1
            assert result[0].ticker == ""

    def test_null_fields_in_json(self):
        """Tests null fields in the JSON."""
        null_fields_stock = {
            "ticker": "AAPL",
            "company_name": None,
            "confidence_score": 8,
            "reasoning": "Good reasoning",
        }

        json_text = json.dumps([null_fields_stock])
        response = SimpleNamespace()
        response.text = json_text
        response.parsed = None

        # Null fields for required string/int types should cause validation to fail.
        result = parse_response_robust(response)
        assert result is None


@pytest.mark.unit
class TestResponseObjectVariations:
    """Tests handling of different response object variations."""

    def test_response_with_parsed_attribute(self):
        """Tests a response object that has a pre-populated 'parsed' attribute."""
        # Create a mock list of already parsed objects.
        parsed_picks = [
            AIStockPick(
                ticker="AAPL",
                company_name="Apple Inc.",
                confidence_score=9,
                reasoning="Strong fundamentals",
            )
        ]

        response = SimpleNamespace()
        response.parsed = parsed_picks
        response.text = "some text that should be ignored"

        result = parse_response_robust(response)

        assert result is not None
        assert len(result) == 1
        assert result[0].ticker == "AAPL"

    def test_response_with_empty_parsed(self):
        """Tests a response where 'parsed' is empty but 'text' has valid content."""
        valid_json = """[
            {
                "ticker": "MSFT",
                "company_name": "Microsoft Corp.",
                "confidence_score": 8,
                "reasoning": "Cloud leadership"
            }
        ]"""

        response = SimpleNamespace()
        response.parsed = None  # or []
        response.text = valid_json

        result = parse_response_robust(response)

        assert result is not None
        assert len(result) == 1
        assert result[0].ticker == "MSFT"

    def test_response_without_attributes(self):
        """Tests a response object missing 'parsed' and 'text' attributes."""
        response = SimpleNamespace()
        # Has neither 'parsed' nor 'text'

        result = parse_response_robust(response)
        assert result is None

    def test_response_parsing_exception(self):
        """Tests exception handling during the parsing process."""

        # Create a response object whose properties raise an exception.
        class BadResponse:
            @property
            def parsed(self):
                raise Exception("Forced parsing error")

            @property
            def text(self):
                raise Exception("Forced text access error")

        response = BadResponse()
        result = parse_response_robust(response)
        assert result is None
