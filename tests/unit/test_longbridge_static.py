from pathlib import Path

import pytest


def _longport_impl_file() -> Path:
    """Return the canonical LongPort client implementation path."""

    return Path("src/stock_analysis/execution/broker/longport_client.py")


@pytest.mark.unit
def test_pyproject_longport_dependency():
    """Tests that pyproject.toml contains the longport dependency."""
    pyproject_file = Path("pyproject.toml")
    assert pyproject_file.exists(), "pyproject.toml file does not exist"

    content = pyproject_file.read_text(encoding="utf-8")
    assert "longport>=0.2.77" in content, "longport>=0.2.77 dependency not found"


@pytest.mark.unit
def test_broker_directory_structure():
    """Tests if the broker directory structure is correct."""
    project_root = Path(".")

    # Check canonical execution broker directory.
    broker_dir = project_root / "src" / "stock_analysis" / "execution" / "broker"
    broker_init = broker_dir / "__init__.py"
    longport_client = broker_dir / "longport_client.py"

    assert broker_dir.exists(), "broker directory does not exist"
    assert broker_init.exists(), "broker/__init__.py does not exist"
    assert longport_client.exists(), "longport_client.py does not exist"


@pytest.mark.unit
def test_cli_contains_longport_commands():
    """Tests that the CLI file contains LongPort-related commands."""
    cli_file = Path("src/stock_analysis/app/cli.py")
    assert cli_file.exists(), "CLI file does not exist"

    content = cli_file.read_text(encoding="utf-8")

    # Check command definitions
    assert "lb-quote" in content, "lb-quote command not found"
    assert "lb-rebalance" in content, "lb-rebalance command not found"

    # Check function definitions
    assert "def run_lb_quote" in content, "run_lb_quote function not found"
    assert "def run_lb_rebalance" in content, "run_lb_rebalance function not found"

    # Check for LongPort-related imports or references
    assert "LongPort" in content, "LongPort-related code not found"


@pytest.mark.unit
def test_longport_client_exports():
    """Tests that longport_client.py exports the necessary functions and classes."""
    longport_client_file = _longport_impl_file()
    assert longport_client_file.exists(), "longport_client.py file does not exist"

    content = longport_client_file.read_text(encoding="utf-8")

    # Check for key function and class definitions
    assert "def _to_lb_symbol" in content, "_to_lb_symbol function not found"
    assert "def getenv_both" in content, "getenv_both function not found"
    assert "class LongPortClient" in content, "LongPortClient class not found"

    # Check for key methods
    assert "def quote_last" in content, "quote_last method not found"
    assert "def place_order" in content, "place_order method not found"


@pytest.mark.unit
def test_pytest_markers_configured():
    """Tests if pytest markers are correctly configured in pyproject.toml."""
    pyproject_file = Path("pyproject.toml")
    assert pyproject_file.exists(), "pyproject.toml file does not exist"

    content = pyproject_file.read_text(encoding="utf-8")

    # Check pytest marker configuration
    assert "markers" in content, "pytest markers configuration not found"
    assert "unit" in content, "unit marker not configured"
    assert "integration" in content, "integration marker not configured"
    assert "e2e" in content, "e2e marker not configured"


@pytest.mark.unit
def test_longport_imports():
    """Tests the compatibility imports in longport_client.py."""
    longport_client_file = _longport_impl_file()
    content = longport_client_file.read_text(encoding="utf-8")

    # Check the compatibility import structure
    assert "try:" in content, "Missing try statement for compatibility import"
    assert "from longport.openapi import" in content, "Missing longport import"
    assert "except ImportError:" in content, "Missing ImportError handling"
    assert "from longbridge.openapi import" in content, "Missing longbridge compatibility import"

    # Check for necessary class imports
    required_imports = ["Config", "QuoteContext", "TradeContext"]

    for import_item in required_imports:
        assert import_item in content, f"Missing import: {import_item}"


@pytest.mark.unit
def test_environment_compatibility():
    """Tests the environment variable compatibility function."""
    longport_client_file = _longport_impl_file()
    content = longport_client_file.read_text(encoding="utf-8")

    assert "def getenv_both" in content, "Missing environment variable compatibility function"
    assert "LONGPORT_" in content, "Missing the new environment variable prefix"
    assert "LONGBRIDGE_" in content, "Missing compatibility for the old environment variable prefix"


@pytest.mark.unit
def test_env_example_file():
    """Tests for the existence of the .env.example file (used for configuration examples)."""
    env_example = Path(".env.example")
    # This file may or may not exist, so we check for it without making it a strict requirement.
    if env_example.exists():
        content = env_example.read_text(encoding="utf-8")
        # If it exists, it should contain LongPort-related environment variable examples.
        longport_vars = [
            "LONGPORT_APP_KEY",
            "LONGPORT_APP_SECRET",
            "LONGPORT_ACCESS_TOKEN",
        ]
        for var in longport_vars:
            if var in content:
                # The test passes if at least one LongPort variable is found.
                break
        else:
            pytest.fail("If .env.example exists, it should contain LongPort environment variable examples.")
