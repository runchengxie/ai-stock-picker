## ADDED Requirements

### Requirement: Canonical research workflow

The system SHALL define a canonical research workflow for data preparation,
rule-based strategy generation, portfolio snapshot generation, and backtesting
without requiring AI model credentials or broker credentials.

#### Scenario: Research path runs without AI or broker dependencies

- **WHEN** a user runs the documented research workflow in an environment that
  lacks AI and broker credentials
- **THEN** the research commands operate only on research dependencies and do
  not require AI or live execution integrations

### Requirement: AI workflow is explicitly experimental

The system SHALL present AI stock selection as an experimental or lab workflow
and SHALL distinguish it from the canonical research path in CLI help and user
documentation.

#### Scenario: User views AI workflow entry points

- **WHEN** a user reads AI-related CLI help or workflow documentation
- **THEN** the AI path is labeled as experimental and is not described as the
  default live-trading workflow

### Requirement: Execution workflow is isolated from research artifacts

The system SHALL treat live execution as a separate workflow that consumes
canonical target files rather than directly consuming research workbooks or AI
workbooks.

#### Scenario: User prepares live rebalancing

- **WHEN** a user invokes the live rebalance planning workflow
- **THEN** the workflow accepts a canonical target file as input and does not
  require direct execution from strategy-specific workbook artifacts
