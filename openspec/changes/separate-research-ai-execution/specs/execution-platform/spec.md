## ADDED Requirements

### Requirement: Rebalance planning honors explicit target intent

The execution platform SHALL build rebalance plans from the canonical target
document and SHALL honor the explicit target expression carried by each target
entry instead of silently converting every target list into equal weights.

#### Scenario: Weight-based targets are planned

- **WHEN** a target document contains explicit target weights
- **THEN** the rebalance plan reflects those weights in the desired positions

### Requirement: Dry-run remains the default execution mode

The execution platform SHALL default to dry-run planning and SHALL require an
explicit execution action before submitting live orders.

#### Scenario: User previews a rebalance plan

- **WHEN** a user runs rebalance planning without an explicit execution flag
- **THEN** the platform produces a preview and does not submit live orders

### Requirement: Execution outputs are auditable

The execution platform SHALL persist an audit record for rebalance planning or
execution that ties the plan to the canonical target input and resulting order
set.

#### Scenario: Rebalance plan is produced

- **WHEN** the platform completes a dry-run or live rebalance operation
- **THEN** it writes an audit artifact that records the target source, planned
  changes, and order outcomes
