## Context

The current repository exposes research/backtesting, AI-assisted stock picking,
and live execution through one `stockq` surface. A partial separation already
exists because `targets gen` can produce a JSON file for rebalancing, but the
current target shape is ticker-oriented, execution still accepts AI Excel
inputs, and the planner currently turns target lists into equal-weight orders.

This change needs a cross-cutting design because it touches CLI semantics,
documentation, target-file data models, execution planning, and how users think
about the default workflow. The design must also preserve momentum by avoiding
an unnecessary backtest-engine rewrite in the same phase.

## Goals / Non-Goals

**Goals:**

- Establish a canonical boundary between strategy generation and live
  execution.
- Make rule-based research and backtesting the canonical project path.
- Keep AI stock selection available, but clearly position it as a lab workflow.
- Define a target contract that can carry explicit portfolio intent for future
  US and HK strategies.
- Make execution depend on canonical target files and broker adapters rather
  than strategy-specific artifacts.

**Non-Goals:**

- Splitting the repository into multiple Git repositories in this phase.
- Replacing `backtrader` or rewriting the research runner.
- Proving historical validity of LLM-based stock picking.
- Adding a second broker adapter in the same change.

## Decisions

### 1. Keep one repository, split logical boundaries first

The project will remain in a single repository for now, but the workflow and
module surfaces will be organized around three logical areas:

- `research`: data loading, universe construction, rule-based signals,
  portfolio snapshots, and backtests
- `ai-lab`: optional LLM-based ranking or explanation workflows
- `execution`: target generation, account snapshots, rebalance planning,
  broker adapters, and audit logs

This preserves velocity and avoids the overhead of immediate multi-repo
coordination. A later repository split remains possible once interfaces are
stable.

Alternative considered:

- Split into three repositories immediately. Rejected because the current
  interfaces are not stable enough; it would freeze accidental contracts rather
  than deliberate ones.

### 2. Introduce a canonical portfolio target contract v2

The core seam will be a normalized target document that represents portfolio
intent independent of its source. The contract will be market-aware and support
 explicit target semantics.

The design baseline is:

```json
{
  "schema_version": 2,
  "asof": "YYYY-MM-DD",
  "source": "research|ai_lab|manual|other",
  "target_gross_exposure": 1.0,
  "targets": [
    {
      "symbol": "AAPL",
      "market": "US",
      "target_weight": 0.10,
      "notes": "optional",
      "metadata": {}
    }
  ],
  "notes": "optional"
}
```

Each target entry will require `symbol` and `market`, plus exactly one target
expression such as `target_weight` or `target_quantity`. Broker-specific symbol
formats remain adapter concerns.

Alternative considered:

- Keep the current ticker-list contract and interpret weights opportunistically.
  Rejected because it cannot represent market identity cleanly and encourages
  silent equal-weight behavior.

### 3. Execution consumes canonical targets only

Live rebalance planning will treat the canonical target contract as its primary
input. Legacy artifacts such as AI Excel or research workbooks may still be
convertible during migration, but they will no longer be treated as canonical
execution inputs.

This makes the execution layer strategy-agnostic and avoids leaking research-
specific assumptions into live trading.

Alternative considered:

- Continue allowing `lb-rebalance` to read AI Excel directly. Rejected because
  it keeps the execution boundary porous and makes it harder to generalize to
  other strategies and markets.

### 4. AI becomes an explicit lab workflow

AI stock picking will remain supported, but it will be labeled and documented
as an experimental workflow. Its outputs will be treated as candidate research
artifacts that must be normalized into the canonical target contract before
execution.

This keeps the project honest about the epistemic limits of time-conditioned
LLM analysis while preserving a useful hobbyist and hypothesis-generation path.

Alternative considered:

- Remove AI entirely. Rejected because the user still wants an experimentation
  path and research assistant workflow.

### 5. Preserve the current backtest engine in phase one

The first phase will keep existing research runners, including `backtrader`
where already used. The boundary split and target contract are higher leverage
than an engine rewrite, and they reduce the risk of mixing architectural
changes with numerical backtest changes in one move.

Alternative considered:

- Rewrite research backtesting around a lighter engine now. Rejected because it
  increases scope and makes regression diagnosis harder.

### 6. Market identity is explicit in targets, not inferred in planners

Target files will carry market identity explicitly, and execution planners will
derive broker-specific symbols from `(symbol, market)` pairs. This avoids a
US-default assumption from leaking into future HK or multi-market execution.

Alternative considered:

- Keep market inference inside the broker adapter. Rejected because it makes the
  contract ambiguous and can silently misroute cross-market symbols.

## Risks / Trade-offs

- [Risk] The migration may temporarily increase CLI surface area while legacy
  and canonical flows coexist. -> Mitigation: mark legacy inputs deprecated,
  route users through explicit conversion commands, and update README examples
  early.
- [Risk] Target contract design may overfit current equal-weight workflows. ->
  Mitigation: require explicit target expressions and market identity, even if
  the first producer still emits equal weights.
- [Risk] AI users may see the relabeling as a downgrade. -> Mitigation: keep AI
  commands available, but make the experimental status and normalization path
  explicit.
- [Risk] Execution changes can affect real-money workflows. -> Mitigation: keep
  dry-run as default, preserve audit logs, and phase behavior changes behind the
  new target schema.
- [Risk] Monorepo boundaries may drift back together over time. -> Mitigation:
  codify the workflow boundaries in specs, docs, and CLI semantics before
  implementation expands again.

## Migration Plan

1. Document the new workflow model and label the canonical versus experimental
   paths.
2. Introduce the target contract v2 and a normalization path from current AI or
   research outputs into the new format.
3. Update execution planning to consume v2 target files and honor explicit
   target intent.
4. Deprecate direct execution from AI Excel or other strategy-specific inputs.
5. Reorganize CLI help and README examples around research, AI lab, and
   execution boundaries.
6. Leave the current research runners in place and evaluate later whether a
   backtest-engine change is still warranted.

Rollback strategy:

- Continue accepting the legacy target parser during the migration window if v2
  adoption exposes operational issues.
- Keep the previous execution commands available until the canonical target flow
  is verified in dry-run mode.

## Open Questions

- Should `target_weight` and `target_quantity` both remain supported in v2, or
  should quantity stay out of scope until a later execution-focused change?
- Should normalization produce one shared target schema for all strategies, or
  should research snapshots keep a richer upstream schema alongside the live
  target contract?
- How aggressively should legacy Excel execution input be deprecated in the
  first implementation pass: warning-only, hidden from docs, or removed?
