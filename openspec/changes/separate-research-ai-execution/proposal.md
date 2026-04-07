## Why

The repository currently combines three different problem spaces in one
workflow surface: rule-based research/backtesting, AI-assisted stock selection,
and live trade execution. That coupling makes the project harder to maintain,
keeps an experimental AI path looking like a canonical strategy, and blocks the
execution layer from becoming a reusable target-based platform for future US and
HK strategies.

## What Changes

- Introduce a stable portfolio target contract that separates strategy outputs
  from live execution inputs.
- Reframe AI stock picking as an optional lab workflow instead of the default
  or canonical strategy path.
- Split the project surface into distinct research, AI lab, and execution
  boundaries while keeping the codebase in a single repository for now.
- Update execution planning to consume the target contract rather than rely on
  AI Excel inputs or ticker-only assumptions.
- Preserve the current backtest engines in the first phase and defer any
  backtest-engine rewrite until after the boundaries and contract are stable.

## Capabilities

### New Capabilities

- `workflow-boundaries`: Define separate user-facing workflows and artifacts for
  research, AI lab experiments, and live execution.
- `portfolio-target-contract`: Define the canonical target file format used to
  move portfolio intent from research or manual input into execution.
- `execution-platform`: Define execution behavior that consumes target files,
  compares them with live account state, and produces auditable rebalance
  actions independent of any single strategy source.

### Modified Capabilities

- None.

## Impact

- Affected code: `src/stock_analysis/cli.py`,
  `src/stock_analysis/commands/backtest.py`,
  `src/stock_analysis/commands/targets.py`,
  `src/stock_analysis/commands/lb_rebalance.py`,
  `src/stock_analysis/utils/targets.py`,
  `src/stock_analysis/services/rebalancer.py`,
  `src/stock_analysis/services/selection/ai_stock_pick.py`,
  `README.md`, and related tests.
- Affected APIs/contracts: `targets.json`, CLI command semantics, execution
  inputs, and documentation for the default workflow.
- Affected systems: research outputs, AI experiment outputs, live rebalance
  planning, and future broker/market expansion.
