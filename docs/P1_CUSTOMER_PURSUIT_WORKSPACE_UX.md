# P1 — Customer Pursuit Workspace UX

## Status

P1 restructures the existing pursuit workspace into a customer-facing, decision-first experience without changing W0–W8 or P0/P0R domain authority. The workspace now has five accessible tabs: Overview, Requirements, Team, Documents & Evidence, and Proposal. Activity was intentionally omitted because the current domain does not provide a meaningful customer activity projection.

The accepted P0R trust gate remains authoritative. Extraction quality, source provenance, immutable packs, review records, candidate evidence, participation, team revisions, approval, proposal evidence, and the no-AI-pricing boundary are unchanged.

## Delivered experience

- The header carries tender identity, stage, reference, deadline, historical-RFP warning, and one authoritative next action.
- Overview presents compact confirmed context, preserves source conflicts, and derives scope, evaluation/qualification, submission checklist, and later-stage obligations from the latest reviewable analysis.
- World Bank source pursuits retain canonical Project Context and Project Leadership data from the tender details read model.
- Requirements is the primary decision surface. It presents counts rather than percentages and orders each inspector as source requirement, Plasma assessment, then organization evidence and review controls.
- Analysis is nonblocking. Running and failed attempts have truthful localized states, retry remains explicit, and a previous successful result stays visible after a later unreviewable attempt.
- Team shows partner and expert needs before team assembly. Team options become available only after participation records exist.
- Documents & Evidence separates official/source documents from organization-private documents. Hashes are confined to technical disclosures.
- Proposal uses progressive disclosure and customer terms: Create evidence pack and Evidence manifest. It remains price-free.
- EN, UZ, RU, and AR catalogs have exact key/ICU parity. Tabs support LTR/RTL arrow navigation.
- Responsive behavior covers 320, 390, 768, and 1440 pixel viewports; proposal matrices become labeled cards on narrow screens.

## Boundaries

P1 changes frontend presentation, customer copy, responsive styling, browser fixtures, and evidence only. It adds no schema or migration, changes no provider/model/prompt, performs no deployment, and does not access production systems. API mutations remain explicit user actions; passive tab loads are reads only.

## Validation

The permanent `scripts/run_release_gate.sh all` wrapper exited 0 against a disposable loopback-only PostgreSQL/Redis target and controlled local browser/API fixtures. After the async-retention and Axe assertions were strengthened, its permanent browser group was rerun against the final production build. Validation completed:

- full backend: 846 passed, 1 skipped, 100 subtests passed;
- security: 118 passed;
- analysis: 50 passed, 12 subtests passed;
- connectors: 198 passed, 1 skipped, 6 subtests passed;
- Alembic heads/current/check/schema preflight: passed at head `20261002_0001_p0_extraction_trust_gate`;
- scale: passed at 1k, 10k, and 100k rows within the existing 5-query/25-file ceiling;
- TypeScript, ESLint, RTL audit, and the 29-route production build: passed;
- frontend: 303 of 303 passed; focused P0–P1 coverage: 45 of 45 passed;
- real Chromium: 204 passed, 0 failed, 0 external requests across EN/UZ/RU/AR and 320/390/768/1440, including running-to-failed rerun retention;
- Axe on all 16 locale/width Pursuit workspace combinations: 0 serious or critical violations;
- configuration: 24 passed; Python dependency check: no broken requirements; npm audit: 0 vulnerabilities.

The retained Chromium result is [results.json](audits/p1/browser-all/results.json), SHA-256 `888734d7bfebed538455d648c0c7442439014e7b82ec0d6cadd61e6bd0b7e982`.

## Evidence

- [Customer language](audits/p1/customer-language.md)
- [Workspace hierarchy](audits/p1/workspace-hierarchy.md)
- [Progressive disclosure](audits/p1/progressive-disclosure.md)
- [Analysis states](audits/p1/analysis-states.md)
- [Real-RFP informativeness](audits/p1/real-rfp-informativeness.md)
- [World Bank preservation](audits/p1/world-bank-preservation.md)
- [Demo readiness](audits/p1/demo-readiness.md)

P1 stops here. It does not begin another slice.
