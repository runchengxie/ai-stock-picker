import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_metrics_module() -> ModuleType:
    path = _repo_root() / "scripts" / "dev" / "maintainability_metrics.py"
    spec = importlib.util.spec_from_file_location("maintainability_metrics", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_maintainability_ratchet_matches_current_baseline() -> None:
    module = _load_metrics_module()
    metrics = module.collect_metrics(_repo_root(), limit=3)
    ratchet_budget_actuals = {
        name: getattr(metrics, name) for name in module.DEFAULT_RATCHET_BUDGETS
    }
    expected = module.DEFAULT_RATCHET_BUDGETS
    assert ratchet_budget_actuals == expected, (
        f"Ratchet drift! {ratchet_budget_actuals} != {expected}"
    )
    assert module.check_ratchet_budgets(metrics) == {}


def test_maintainability_metrics_ratchet_flag_passes() -> None:
    repo_root = _repo_root()
    result = subprocess.run(
        ["python", "scripts/dev/maintainability_metrics.py", "--ratchet"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Ratchet flag failed:\n{result.stderr}"


def test_ruff_cyclomatic_complexity_gate_is_pinned() -> None:
    with (_repo_root() / "pyproject.toml").open("rb") as config_file:
        config = tomllib.load(config_file)

    lint_config = config["tool"]["ruff"]["lint"]
    assert "C90" in lint_config["select"]
    assert lint_config["mccabe"]["max-complexity"] == 17
