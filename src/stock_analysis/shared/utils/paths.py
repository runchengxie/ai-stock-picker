"""Unified path configuration module.

Provides unified configuration for all paths in the project, eliminating duplicate path setup code.
"""

from pathlib import Path


def get_project_root() -> Path:
    """Get project root directory path.

    Returns:
        Path: Project root directory path
    """
    try:
        # Assume script is located in 'src/stock_analysis/' folder under root directory
        return Path(__file__).resolve().parent.parent.parent.parent
    except NameError:
        # Use current working directory if running in interactive environment (like Jupyter)
        return Path.cwd()


# Global path configuration
PROJECT_ROOT = get_project_root()
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

# Ensure output directory exists
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# Database path
DB_PATH = DATA_DIR / "financial_data.db"

# Default portfolio file paths
AI_PORTFOLIO_FILE = OUTPUTS_DIR / "point_in_time_ai_stock_picks_all_sheets.xlsx"
QUANT_PORTFOLIO_FILE = (
    OUTPUTS_DIR / "point_in_time_backtest_quarterly_sp500_historical.xlsx"
)

# JSON portfolio directories (per-date files)
AI_PORTFOLIO_JSON_DIR = OUTPUTS_DIR / "ai_pick"
QUANT_PORTFOLIO_JSON_DIR = OUTPUTS_DIR / "preliminary"

# Backtest configuration constants
DEFAULT_INITIAL_CASH = 1_000_000.0
SPY_INITIAL_CASH = 100_000.0
