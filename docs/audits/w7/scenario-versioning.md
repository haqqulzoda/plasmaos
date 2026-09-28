# W7 Scenario Versioning Audit

## Authority

`TeamScenario` is the stable Organization private name. Composition exists only in `TeamScenarioRevision` descendants.

Each revision seals the exact AnalysisRun and AnalysisPack, version, sorted selection SHA-256, assessment schema, outcome, counts, creator, and time. The selection hash includes the schema and sorted W6 participation record identities, so request ordering cannot change the identity.

## Immutability

The W7 migration installs update/delete rejection triggers on revisions, participants, contributions, Gap assessments, issues, and decisions. Scenario roots reject delete; archival remains the only permitted root lifecycle field. Composite foreign keys keep every child in the same Organization, revision, analysis, participant, match, Gap, and participation record chain.

The permanent migration test upgrades W6→W7, downgrades W7→W6, upgrades again, and runs `alembic check`. The integration test proves update/delete rejection for every historical table.

