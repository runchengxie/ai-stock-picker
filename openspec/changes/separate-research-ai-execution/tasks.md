## 1. Workflow Boundaries

- [x] 1.1 Reorganize CLI help text and README examples around `research`, `ai-lab`, and `execution` workflows
- [x] 1.2 Mark AI stock-picking commands and documentation as experimental rather than canonical
- [x] 1.3 Remove direct live-execution guidance that depends on AI or research workbook artifacts as primary inputs

## 2. Portfolio Target Contract

- [x] 2.1 Define and document the canonical `targets` schema v2 with market-aware target entries and explicit target expressions
- [x] 2.2 Update target read/write utilities to support schema v2 and reject ambiguous ticker-only canonical inputs
- [x] 2.3 Add normalization from existing AI or research outputs into schema v2 target files

## 3. Execution Platform

- [x] 3.1 Refactor rebalance planning to consume schema v2 targets and honor `target_weight` or `target_quantity`
- [x] 3.2 Update execution input handling so canonical rebalance planning runs from target files rather than direct AI Excel inputs
- [x] 3.3 Make market-to-broker symbol mapping derive from explicit target market metadata instead of a US-default assumption for canonical targets
- [x] 3.4 Preserve dry-run-by-default behavior and include target source metadata in audit outputs

## 4. Verification and Migration

- [x] 4.1 Add unit tests for schema v2 parsing, normalization, and weight-aware rebalance planning
- [x] 4.2 Add CLI or end-to-end coverage for the canonical research flow, experimental AI flow, and target-based execution flow
- [x] 4.3 Validate migration messaging and deprecation behavior for legacy execution inputs
