## ADDED Requirements

### Requirement: Canonical target document

The system SHALL define a canonical portfolio target document for live
execution. The document SHALL include `schema_version`, `asof`, `source`, and a
`targets` collection. Each target entry SHALL include `symbol`, `market`, and
exactly one explicit target expression such as `target_weight` or
`target_quantity`.

#### Scenario: Valid target file is loaded

- **WHEN** a user provides a target document with the required top-level fields
  and target entries
- **THEN** the system recognizes it as the canonical execution input

### Requirement: Market-aware target identity

The canonical target document SHALL represent market identity explicitly rather
than relying on implicit US defaults or broker-specific ticker suffixes.

#### Scenario: Multi-market targets are expressed

- **WHEN** a target document contains entries for both US and HK securities
- **THEN** each entry carries explicit market identity and can be planned
  without inferring the market from a default assumption

### Requirement: Legacy strategy outputs can be normalized

The system SHALL provide a documented normalization path from legacy AI or
research outputs into the canonical target document.

#### Scenario: User converts AI output into canonical targets

- **WHEN** a user generates live targets from an AI or research result
- **THEN** the system emits a canonical target document rather than requiring
  the execution layer to understand the original strategy artifact directly
