"""Module for testing robustness of the AI stock-picking workflow (simulation).

This module tests the key components of the AI stock-picking workflow, including:
- RateLimiter: A sliding window for request throttling.
- Circuit: The open/closed logic of a circuit breaker.
- KeyPool: Its ability to differentiate between permanently removing a key
  (for 401/403 errors) and applying a project-level cooldown (for 429 errors).
- Simulation of `client.models.generate_content`: Tests timeouts, retry
  backoff, and state reset upon success.
- Parsing Structured JSON: Validates required fields and handles exception
  branches.
"""

# Standard library imports
import json
import threading
import time
from unittest.mock import Mock, patch

# Third-party library imports for testing
import pytest

pytest.importorskip("pydantic")
from pydantic import ValidationError

# Imports from the application's own code
from stock_analysis.ai_lab.selection.ai_stock_pick import (
    AIStockPick,
    Circuit,
    KeyPool,
    KeySlot,
    RateLimiter,
    call_with_pool,
    create_key_pool,
)

pytestmark = pytest.mark.integration


class FakeTime:
    """Utility class to simulate time progression in tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.current = start

    def time(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += seconds

    def monotonic(self) -> float:
        return self.current


@pytest.fixture
def fake_time(monkeypatch) -> "FakeTime":
    """Fixture patching time functions with a controllable clock."""
    ft = FakeTime()
    monkeypatch.setattr(time, "time", ft.time)
    monkeypatch.setattr(time, "sleep", ft.sleep)
    monkeypatch.setattr(time, "monotonic", ft.monotonic)
    return ft


class TestRateLimiter:
    """Tests for the sliding window rate limiter."""

    def test_initialization(self):
        """Tests the limiter's initialization."""
        limiter = RateLimiter(max_calls=10, per_seconds=60)
        # Verify that the attributes are set correctly upon creation.
        assert limiter.max_calls == 10
        assert limiter.per == 60
        assert len(limiter.calls) == 0

    def test_allow_within_limit(self):
        """Tests calls that are within the defined limit."""
        limiter = RateLimiter(max_calls=3, per_seconds=60)

        # The first 3 calls should be allowed.
        for _i in range(3):
            assert limiter.allow()
            limiter.record_call()

        # The 4th call should be rejected because the limit has been reached.
        assert not limiter.allow()

    def test_sliding_window_behavior(self, fake_time):
        """Tests the sliding window behavior."""
        limiter = RateLimiter(max_calls=2, per_seconds=1)  # Max 2 calls per second

        # Record two calls to hit the limit.
        limiter.record_call()
        limiter.record_call()

        # The next call should be blocked.
        assert not limiter.allow()

        # Wait for a time longer than the window (1 second).
        time.sleep(1.1)

        # Now, a new call should be allowed because the old records have expired.
        assert limiter.allow()

    def test_wait_method(self, fake_time):
        """Tests the `wait` method, which should block until a call is allowed."""
        limiter = RateLimiter(max_calls=1, per_seconds=1)

        # Make one call to use up the allowance.
        limiter.record_call()

        # Record the start time before waiting.
        start_time = time.time()

        # The `wait()` method should block until the window resets.
        limiter.wait()

        # Verify that the elapsed time is reasonable (should be close to 1 second).
        elapsed = time.time() - start_time
        assert elapsed >= 0.9  # Allow for some timing inaccuracy.

    def test_cleanup_old_calls(self, fake_time):
        """Tests the cleanup of expired call records."""
        limiter = RateLimiter(max_calls=5, per_seconds=1)

        # Add some call records.
        for _ in range(3):
            limiter.record_call()

        assert len(limiter.calls) == 3

        # Wait for the window to pass, making the records expire.
        time.sleep(1.1)

        # Calling `allow()` should trigger the cleanup of old records.
        limiter.allow()

        # The list of calls should now be empty.
        assert len(limiter.calls) == 0


class TestCircuit:
    """Tests for the Circuit Breaker."""

    def test_initialization(self):
        """Tests the circuit breaker's initialization."""
        circuit = Circuit(fail_threshold=3, cooldown=30)
        # Verify initial state.
        assert circuit.fail_threshold == 3
        assert circuit.cooldown == 30
        assert circuit.failures == 0
        assert circuit.open_until == 0

    def test_allow_when_closed(self):
        """Tests that requests are allowed when the circuit is closed (normal state)."""
        circuit = Circuit(fail_threshold=3, cooldown=30)
        assert circuit.allow()

    def test_record_failure_and_open(self):
        """Tests that recording failures eventually opens the circuit."""
        circuit = Circuit(fail_threshold=2, cooldown=1)

        # First failure.
        circuit.record_failure()
        assert circuit.failures == 1
        assert circuit.allow()  # Still below the threshold.

        # Second failure, which should open ("trip") the circuit.
        circuit.record_failure()
        assert circuit.failures == 2
        assert not circuit.allow()  # The circuit is now open and should block requests.

    def test_cooldown_period(self, fake_time):
        """Tests the behavior during the cooldown period."""
        circuit = Circuit(fail_threshold=1, cooldown=1)

        # Trigger the circuit to open.
        circuit.record_failure()
        assert not circuit.allow()

        # Wait for the cooldown period to end.
        time.sleep(1.1)

        # Now, requests should be allowed again (circuit is half-open or closed).
        assert circuit.allow()

    def test_record_success_resets_failures(self):
        """Tests that a successful call resets the failure counter."""
        circuit = Circuit(fail_threshold=3, cooldown=30)

        # Record some failures.
        circuit.record_failure()
        circuit.record_failure()
        assert circuit.failures == 2

        # A successful call should reset the counter back to zero.
        circuit.record_success()
        assert circuit.failures == 0

    def test_multiple_failures_extend_cooldown(self, fake_time):
        """Tests repeated failures while circuit open extend cooldown."""
        circuit = Circuit(fail_threshold=1, cooldown=1)

        # First failure opens the circuit and sets an `open_until` time.
        circuit.record_failure()
        first_open_until = circuit.open_until

        time.sleep(0.1)
        # Another failure should push the `open_until` time further into the future.
        circuit.record_failure()
        second_open_until = circuit.open_until

        assert second_open_until > first_open_until


class TestKeySlot:
    """Tests for the API Key Slot, which holds a single key and its state."""

    def test_initialization(self):
        """Tests the initialization of a key slot."""
        mock_client = Mock()
        mock_limiter = Mock()

        slot = KeySlot("test_key", "api_key_123", mock_client, mock_limiter)

        assert slot.name == "test_key"
        assert slot.api_key == "api_key_123"
        assert slot.client == mock_client
        assert slot.limiter == mock_limiter
        assert isinstance(
            slot.circuit, Circuit
        )  # Each slot has its own circuit breaker.
        assert not slot.dead  # It should not be "dead" initially.
        assert slot.next_ok_at == 0  # It should be available immediately.

    def test_slot_states(self):
        """Tests the state management of a slot."""
        mock_client = Mock()
        mock_limiter = Mock()

        slot = KeySlot("test_key", "api_key_123", mock_client, mock_limiter)

        # Test marking the slot as dead (permanently unusable).
        slot.dead = True
        assert slot.dead

        # Test setting the next available time.
        future_time = time.time() + 60
        slot.next_ok_at = future_time
        assert slot.next_ok_at == future_time


class TestKeyPool:
    """Tests for the API Key Pool manager."""

    def create_mock_slot(
        self,
        name: str,
        dead: bool = False,
        circuit_allow: bool = True,
        next_ok_at: float = 0,
    ) -> KeySlot:
        """Helper function to create a mock KeySlot for testing."""
        mock_client = Mock()
        mock_limiter = Mock()

        slot = KeySlot(name, f"api_key_{name}", mock_client, mock_limiter)
        slot.dead = dead
        slot.next_ok_at = next_ok_at

        # Mock the circuit breaker's behavior.
        slot.circuit.allow = Mock(return_value=circuit_allow)

        return slot

    def test_acquire_available_slot(self):
        """Tests acquiring an available slot from the pool."""
        slot1 = self.create_mock_slot("key1")
        slot2 = self.create_mock_slot("key2")

        pool = KeyPool([slot1, slot2])

        acquired_slot = pool.acquire()
        assert acquired_slot in [slot1, slot2]

    def test_skip_dead_slots(self):
        """Tests that the pool skips over 'dead' (permanently failed) slots."""
        dead_slot = self.create_mock_slot("dead_key", dead=True)
        alive_slot = self.create_mock_slot("alive_key", dead=False)

        pool = KeyPool([dead_slot, alive_slot])

        acquired_slot = pool.acquire()
        assert acquired_slot == alive_slot

    def test_skip_circuit_open_slots(self):
        """Tests that the pool skips slots whose circuit breakers are open."""
        open_slot = self.create_mock_slot("open_key", circuit_allow=False)
        closed_slot = self.create_mock_slot("closed_key", circuit_allow=True)

        pool = KeyPool([open_slot, closed_slot])

        acquired_slot = pool.acquire()
        assert acquired_slot == closed_slot

    def test_skip_time_restricted_slots(self, fake_time):
        """Tests that the pool skips slots that are on a temporary cooldown."""
        future_time = time.time() + 60
        restricted_slot = self.create_mock_slot(
            "restricted_key", next_ok_at=future_time
        )
        available_slot = self.create_mock_slot("available_key", next_ok_at=0)

        pool = KeyPool([restricted_slot, available_slot])

        acquired_slot = pool.acquire()
        assert acquired_slot == available_slot

    def test_project_cooldown(self, fake_time, monkeypatch):
        """Tests the project-level cooldown (affects all keys)."""
        slot = self.create_mock_slot("key1")
        pool = KeyPool([slot])

        # Set a project-level cooldown period and apply it to the slot.
        pool.project_cooldown_until = time.time() + 60
        slot.next_ok_at = pool.project_cooldown_until

        spy_sleep = Mock(side_effect=fake_time.sleep)
        monkeypatch.setattr(time, "sleep", spy_sleep)

        acquired_slot = pool.acquire()
        assert acquired_slot == slot
        # Verify that `time.sleep` was called to wait.
        assert spy_sleep.called

    def test_report_success(self, fake_time):
        """Tests reporting a successful API call."""
        slot = self.create_mock_slot("key1")
        # Mock the success method on the circuit breaker
        slot.circuit.record_success = Mock()
        pool = KeyPool([slot])

        pool.report_success(slot)

        # Verify the circuit breaker was notified of the success.
        slot.circuit.record_success.assert_called_once()
        # Verify the cooldown time was reset.
        assert slot.next_ok_at == time.time()

    def test_report_failure_401_403(self):
        """Tests reporting a 401/403 error, which should permanently remove the key."""
        slot = self.create_mock_slot("key1")
        pool = KeyPool([slot])

        # Simulate a 401 Unauthorized error.
        error_401 = Exception("401 Unauthorized")
        pool.report_failure(slot, error_401)

        # The slot should now be marked as dead.
        assert slot.dead

    def test_report_failure_429(self, fake_time):
        """Tests reporting a 429 error triggering a project-level cooldown."""
        slot = self.create_mock_slot("key1")
        pool = KeyPool([slot])

        # Simulate a 429 Too Many Requests error.
        error_429 = Exception("429 Too Many Requests")
        pool.report_failure(slot, error_429)

        # A project-level cooldown should be set.
        assert pool.project_cooldown_until > time.time()

    def test_report_failure_other_errors(self, fake_time):
        """Tests reporting errors handled by the circuit breaker."""
        slot = self.create_mock_slot("key1")
        # Mock the failure method on the circuit breaker
        slot.circuit.record_failure = Mock()
        pool = KeyPool([slot])

        # Simulate a generic server error.
        other_error = Exception("500 Internal Server Error")
        pool.report_failure(slot, other_error)

        # The failure should be recorded by the slot's circuit breaker.
        slot.circuit.record_failure.assert_called_once()
        # A short-term "soft backoff" time should be set for this specific key.
        assert slot.next_ok_at > time.time()


class TestCallWithPool:
    """Tests `call_with_pool`, orchestrating API calls via KeyPool."""

    def create_mock_pool(self, success_on_attempt: int = 1) -> tuple[Mock, Mock]:
        """Helper to create a mock KeyPool for testing."""
        mock_pool = Mock()
        mock_slot = Mock()
        mock_slot.name = "test_key"

        # Simulate the acquire method.
        mock_pool.acquire.return_value = mock_slot

        # Simulate the reporting methods.
        mock_pool.report_success = Mock()
        mock_pool.report_failure = Mock()

        return mock_pool, mock_slot

    def test_successful_call_first_attempt(self):
        """Tests a call that succeeds on the first try."""
        mock_pool, mock_slot = self.create_mock_pool()

        # A function that simulates a successful API call.
        def successful_call(slot):
            return {"result": "success", "slot_name": slot.name}

        result = call_with_pool(mock_pool, successful_call, max_retries=3)

        # Verify the result is correct.
        assert result["result"] == "success"
        assert result["slot_name"] == "test_key"

        # Verify that success was reported and failure was not.
        mock_pool.report_success.assert_called_once_with(mock_slot)
        mock_pool.report_failure.assert_not_called()

    def test_retry_on_failure(self):
        """Tests the retry logic for calls that initially fail."""
        mock_pool, mock_slot = self.create_mock_pool()

        call_count = 0

        # A function that fails twice before succeeding.
        def failing_then_success_call(slot):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Temporary failure")
            return {"result": "success after retries"}

        result = call_with_pool(mock_pool, failing_then_success_call, max_retries=5)

        # Verify it eventually succeeded.
        assert result["result"] == "success after retries"

        # Verify it was called 3 times (2 failures, 1 success).
        assert call_count == 3

        # Verify failures and success were reported correctly.
        assert mock_pool.report_failure.call_count == 2
        mock_pool.report_success.assert_called_once()

    def test_max_retries_exceeded(self):
        """Tests what happens when the maximum number of retries is exceeded."""
        mock_pool, mock_slot = self.create_mock_pool()

        def always_failing_call(slot):
            raise Exception("Always fails")

        # Expect the final exception to be raised.
        with pytest.raises(Exception, match="Always fails"):
            call_with_pool(mock_pool, always_failing_call, max_retries=2)

        # Verify it was called 3 times (initial call + 2 retries).
        assert mock_pool.report_failure.call_count == 3
        mock_pool.report_success.assert_not_called()

    def test_exponential_backoff(self, fake_time, monkeypatch):
        """Tests that the delay between retries increases exponentially."""
        mock_pool, mock_slot = self.create_mock_pool()

        call_times = []

        def failing_call(slot):
            call_times.append(time.time())
            raise Exception("Retry with backoff")

        mock_sleep = Mock(side_effect=fake_time.sleep)
        monkeypatch.setattr(time, "sleep", mock_sleep)
        try:
            call_with_pool(mock_pool, failing_call, max_retries=2)
        except Exception:
            pass  # An exception is expected.

        # Verify sleep was called for each retry.
        assert mock_sleep.call_count == 2

        # Verify the backoff time increases.
        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert (
            sleep_calls[0] < sleep_calls[1]
        )  # The second delay is longer than the first.


class TestAIStockPick:
    """Tests for the AIStockPick Pydantic data model."""

    def test_valid_model_creation(self):
        """Tests creating a model instance with valid data."""
        valid_data = {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "confidence_score": 8,
            "reasoning": "Strong fundamentals and growth prospects",
        }

        pick = AIStockPick(**valid_data)

        assert pick.ticker == "AAPL"
        assert pick.company_name == "Apple Inc."
        assert pick.confidence_score == 8
        assert pick.reasoning == "Strong fundamentals and growth prospects"

    def test_confidence_score_validation(self):
        """Tests validation for confidence_score (must be between 1 and 10)."""
        base_data = {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "reasoning": "Test reasoning",
        }

        # Test valid scores.
        for score in [1, 5, 10]:
            data = {**base_data, "confidence_score": score}
            pick = AIStockPick(**data)
            assert pick.confidence_score == score

        # Test invalid scores (should raise a validation error).
        for invalid_score in [0, 11, -1]:
            data = {**base_data, "confidence_score": invalid_score}
            with pytest.raises(ValidationError):
                AIStockPick(**data)

    def test_required_fields(self):
        """Tests that all required fields must be present."""
        # Test missing 'ticker'.
        with pytest.raises(ValidationError):
            AIStockPick(company_name="Apple Inc.", confidence_score=8, reasoning="Test")

        # Test missing 'company_name'.
        with pytest.raises(ValidationError):
            AIStockPick(ticker="AAPL", confidence_score=8, reasoning="Test")

        # Test missing 'confidence_score'.
        with pytest.raises(ValidationError):
            AIStockPick(ticker="AAPL", company_name="Apple Inc.", reasoning="Test")

        # Test missing 'reasoning'.
        with pytest.raises(ValidationError):
            AIStockPick(ticker="AAPL", company_name="Apple Inc.", confidence_score=8)

    def test_json_parsing(self):
        """Tests creating the model from a JSON string."""
        json_data = """
        {
            "ticker": "MSFT",
            "company_name": "Microsoft Corporation",
            "confidence_score": 9,
            "reasoning": "Excellent cloud business growth and strong financials"
        }
        """

        data = json.loads(json_data)
        pick = AIStockPick(**data)

        assert pick.ticker == "MSFT"
        assert pick.company_name == "Microsoft Corporation"
        assert pick.confidence_score == 9

    def test_invalid_json_structure(self):
        """Tests handling of JSON with an invalid structure."""
        # Test with extra fields (they should be ignored by Pydantic).
        data_with_extra = {
            "ticker": "GOOGL",
            "company_name": "Alphabet Inc.",
            "confidence_score": 7,
            "reasoning": "Strong search and cloud business",
            "extra_field": "should be ignored",
        }

        pick = AIStockPick(**data_with_extra)
        assert pick.ticker == "GOOGL"
        # Verify the extra field was not added to the model instance.
        assert not hasattr(pick, "extra_field")


class TestCreateKeyPool:
    """Tests for the `create_key_pool` factory function."""

    @patch.dict(
        "os.environ",
        {
            "GEMINI_API_KEY": "key1",
            "GEMINI_API_KEY_2": "key2",
            "GEMINI_API_KEY_3": "key3",
        },
    )
    @patch("stock_analysis.ai_lab.selection.ai_stock_pick.genai.GenerativeModel")
    def test_create_pool_with_all_keys(self, mock_model):
        """Tests creating a pool when all expected API key env vars are present."""
        mock_model.return_value = Mock()  # Mock the AI model client.

        pool = create_key_pool()

        assert isinstance(pool, KeyPool)
        assert len(pool.slots) == 3

        # Verify that slots were created for all keys.
        slot_names = [slot.name for slot in pool.slots]
        assert "GEMINI_API_KEY" in slot_names
        assert "GEMINI_API_KEY_2" in slot_names
        assert "GEMINI_API_KEY_3" in slot_names

    @patch.dict(
        "os.environ",
        {
            "GEMINI_API_KEY": "key1",
            "GEMINI_API_KEY_2": "key2",
            # Missing GEMINI_API_KEY_3
        },
    )
    @patch("stock_analysis.ai_lab.selection.ai_stock_pick.genai.GenerativeModel")
    def test_create_pool_with_partial_keys(self, mock_model):
        """Tests creating a pool with only a subset of keys available."""
        mock_model.return_value = Mock()

        pool = create_key_pool()

        assert isinstance(pool, KeyPool)
        assert len(pool.slots) == 2

    @patch.dict("os.environ", {}, clear=True)
    def test_create_pool_no_keys(self):
        """Tests that an error is raised if no API keys are found."""
        with pytest.raises(ValueError, match="No available GEMINI_API_KEY found"):
            create_key_pool()

    @patch.dict(
        "os.environ",
        {
            "GEMINI_API_KEY": "",  # Empty string should be filtered out.
            "GEMINI_API_KEY_2": "key2",
        },
    )
    @patch("stock_analysis.ai_lab.selection.ai_stock_pick.genai.GenerativeModel")
    def test_create_pool_filter_empty_keys(self, mock_model):
        """Tests that empty string API keys are ignored."""
        mock_model.return_value = Mock()

        pool = create_key_pool()

        assert len(pool.slots) == 1
        assert pool.slots[0].name == "GEMINI_API_KEY_2"


class TestAIIntegrationScenarios:
    """End-to-end tests for AI integration scenarios."""

    def test_complete_ai_workflow_simulation(self):
        """Simulates a complete, successful AI workflow."""
        # 1. Create a mock KeyPool with one working key.
        mock_slot1 = Mock()
        mock_slot1.name = "key1"
        mock_slot1.dead = False
        mock_slot1.next_ok_at = 0
        mock_slot1.circuit.allow.return_value = True
        mock_slot1.limiter.allow.return_value = True

        mock_pool = Mock()
        mock_pool.acquire.return_value = mock_slot1
        mock_pool.report_success = Mock()
        mock_pool.report_failure = Mock()

        # 2. Simulate a successful AI API call.
        def mock_ai_call(slot):
            return {
                "ticker": "AAPL",
                "company_name": "Apple Inc.",
                "confidence_score": 8,
                "reasoning": "Strong fundamentals and market position",
            }

        # 3. Execute the call using the pool.
        result = call_with_pool(mock_pool, mock_ai_call, max_retries=3)

        # 4. Verify the result.
        assert result["ticker"] == "AAPL"
        assert result["confidence_score"] == 8

        # 5. Verify that the success was reported back to the pool.
        mock_pool.report_success.assert_called_once_with(mock_slot1)

    def test_resilience_under_multiple_failures(self):
        """Tests the system's resilience when multiple keys are in failed states."""
        # Create slots simulating different failure modes.
        dead_slot = Mock()
        dead_slot.name = "dead_key"
        dead_slot.dead = True

        circuit_open_slot = Mock()
        circuit_open_slot.name = "circuit_open_key"
        circuit_open_slot.dead = False
        circuit_open_slot.next_ok_at = 0
        circuit_open_slot.circuit.allow.return_value = False  # Circuit is open.

        working_slot = Mock()
        working_slot.name = "working_key"
        working_slot.dead = False
        working_slot.next_ok_at = 0
        working_slot.circuit.allow.return_value = True  # Circuit is closed.

        # Simulate the pool's logic to find a working key.
        def mock_acquire():
            # This logic mimics the real pool's `acquire` method.
            candidates = [
                s
                for s in [dead_slot, circuit_open_slot, working_slot]
                if not s.dead and s.circuit.allow() and time.time() >= s.next_ok_at
            ]
            return candidates[0] if candidates else None

        mock_pool = Mock()
        mock_pool.acquire = mock_acquire
        mock_pool.report_success = Mock()

        def successful_call(slot):
            return {"result": "success", "slot": slot.name}

        result = call_with_pool(mock_pool, successful_call, max_retries=3)

        # It should have skipped the failed slots and used the working one.
        assert result["slot"] == "working_key"

    def test_json_parsing_error_handling(self):
        """Tests how parsing errors from malformed JSON are handled."""
        # A list of invalid JSON strings.
        invalid_json_cases = [
            '{"ticker": "AAPL", "confidence_score": "not_a_number"}',  # Wrong data type
            '{"ticker": "AAPL"}',  # Missing required fields
            '{"ticker": "AAPL", "confidence_score": 15}',  # Value out of range
            "invalid json string",  # Completely invalid format
        ]

        # Loop through each case and ensure it raises the expected error.
        for invalid_json in invalid_json_cases:
            try:
                data = json.loads(invalid_json)
                AIStockPick(**data)
                # If no exception is raised, the test fails.
                raise AssertionError(
                    f"Should have raised exception for: {invalid_json}"
                )
            except (json.JSONDecodeError, ValidationError, TypeError):
                # This is the expected outcome.
                pass

    def test_concurrent_key_pool_access(self, fake_time):
        """Tests concurrent access to the KeyPool from multiple threads."""
        # Create a real KeyPool for this test.
        mock_client = Mock()
        mock_limiter = Mock()
        mock_limiter.allow.return_value = True

        slots = []
        for i in range(3):
            slot = KeySlot(f"key_{i}", f"api_key_{i}", mock_client, mock_limiter)
            slots.append(slot)

        pool = KeyPool(slots)

        acquired_slots = []

        # A function for each thread to run.
        def acquire_slot():
            slot = pool.acquire()
            acquired_slots.append(slot)
            time.sleep(0.1)  # Simulate using the key for a short time.

        threads = []
        for _ in range(3):
            thread = threading.Thread(target=acquire_slot)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Verify that all 3 threads successfully acquired a slot.
        assert len(acquired_slots) == 3
        # Verify that each thread got a unique slot.
        assert len(set(acquired_slots)) == 3
