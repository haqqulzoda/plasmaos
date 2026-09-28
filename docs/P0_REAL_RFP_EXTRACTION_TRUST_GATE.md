# P0 — Real-RFP Extraction Correctness & Trust Gate

## Status

Implemented against the accepted W0-W8 workspace. P0 preserves immutable analysis packs, W4 coverage semantics, W5-W8 lineage and authority, World Bank source behavior, the W1 no-AI-pricing boundary, and passive reads. No production access or deployment was performed.

## Baseline and migration

The accepted baseline was Alembic head `20261001_0001_w8_proposal_evidence_pack`. P0 adds the narrow reversible migration `20261002_0001_p0_extraction_trust_gate` for:

- `pursuit_analysis_runs.quality_state`;
- count-only `pursuit_analysis_runs.extraction_diagnostics`;
- `pursuit_analysis_positions.qualification_criteria` so mandatory/preferred/desired distinctions survive persistence.

The migration is additive, upgrades from W8, downgrades to W8, and is covered by Alembic drift checks.

## Root cause and correction

The real eight-page PDF reached the parser, sealed pack, and model intact. The model returned five requirements and one position, all schema-valid. Literal quote/source-context checks rejected every fact because harmless PDF page markers, running headers, line wrapping, and section-heading whitespace differed. Persistence therefore received zero rows, while the old worker still declared `COMPLETED/FULL`.

The classification is `QUOTE_VALIDATION_REJECTION`. The detailed, hash-addressed pipeline reproduction is in [root-cause.md](audits/p0/root-cause.md).

Matching now applies deterministic PDF-layout normalization and maps each match back to exact immutable source offsets. It is not fuzzy matching and does not weaken the requirement that evidence exist in the sealed source. Prompt/schema/pipeline versions are now:

- `pursuit_analysis_p0_v2`
- prompt SHA-256 `98c86fadaa1a9554dd53e1220a5711a679548ecc0f86135602753b3d04066854`
- `pursuit_analysis_output_p0_v2`
- `pursuit_analysis_pipeline_p0_v2`

The prompt now asks for exhaustive supported obligations, preserves qualification strength, treats hourly rate as customer-provided input, and preserves individual-versus-firm ambiguity.

## Trust behavior

A persisted quality assessment separates processing completion from reliable extraction. Suspiciously empty and implausibly sparse runs become `NEEDS_ATTENTION`; failures become `FAILED`; materially populated runs become `READY_FOR_REVIEW`. Historical completed/empty runs receive a conservative derived state on read without mutation.

Customer UI no longer treats zero extraction as proof of no gaps. It surfaces review/rerun actions, derives Next Action from current analysis/scenario state, demotes pipeline identifiers, displays source/user conflicts without overwriting confirmed data, and marks the 2012 source deadline as historical and passed.

## Real-RFP result

The deterministic real-procurement benchmark proves all eight pages and late-page content enter the analyzer. It verifies the Communications Consultant role, qualification criteria and preference distinctions; all specified proposal obligations; later-stage contract and Notice-to-Proceed duties; missing artifacts as `EVIDENCE_MISSING`; correct source context; and the no-AI-pricing boundary. See [real-rfp-golden-benchmark.md](audits/p0/real-rfp-golden-benchmark.md).

Additional evidence:

- [Extraction-quality gate](audits/p0/extraction-quality-gate.md)
- [Context provenance and conflicts](audits/p0/context-provenance-conflicts.md)
- [UI trust states](audits/p0/ui-trust-states.md)
- [Validation ledger](audits/p0/validation.md)
- [Exact P0 file inventory](audits/p0/files-changed.md)
- [Chromium result](audits/p0/browser-all/results.json)

## Validation result

The final guarded `scripts/run_release_gate.sh all` invocation exited 0 against a disposable loopback PostgreSQL database. It completed 846 backend tests with one skip and 100 subtests; 118 security tests; 50 analysis tests and 12 subtests; 198 connector tests with one skip and 6 subtests; migration head/current/check/schema preflight; 100,000-row scale checks; TypeScript; ESLint; 297 frontend tests; RTL audit; production build; 203 Chromium cases with zero failures and zero external requests; 24 configuration tests; `pip check`; and npm audit with zero vulnerabilities.

The permanent focused P0 suite covers all eight pages, source context, golden semantics, role ambiguity, qualification distinctions, pricing, later-stage duties, missing artifacts, quality states, conflict states, passivity, and migration upgrade/downgrade. Dedicated compatibility checks also passed for World Bank/project behavior and communications.

## Remaining risk and P1 entry

The deterministic fixture exercises the real parser output, schema, validator, normalizer, and persistence semantics. Two post-fix calls to the unchanged external Gemini provider exceeded a 600-second local timeout, so a fresh live provider response was not available as additional confirmation. This does not weaken the reproduced root cause or deterministic acceptance evidence, but provider latency remains an operational risk for a staging canary.

P1 may start from Alembic head `20261002_0001_p0_extraction_trust_gate` after a non-production environment applies the migration and runs a live-provider canary when the provider is responsive. P1 should not reopen the P0 evidence rules, W4 semantics, no-AI-pricing boundary, or W5-W8 authorities.

## Scope boundary

P0 does not redesign the overall pursuit workspace, add navigation/tabs, alter candidate/team/proposal models or authorities, change model/provider, add connectors, add AI pricing, or access/deploy production. Those boundaries remain the recommended entry conditions for P1.
