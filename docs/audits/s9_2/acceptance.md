# Sprint 9.2 acceptance ledger

**Scoped cleanup: PASS. Application release readiness: NOT PASS.**

Each entry points to the numbered section in the [31-section report](../../S9_2_LEGACY_CONTRACT_TEST_TOPOLOGY_CLEANUP.md). Logs and exact changes are in the [execution record](execution.json). Optional actions passed through explicit KEEP decisions; they are not claimed implemented.

| # | Criterion | Disposition | Evidence / limit |
| --- | --- | --- | --- |
| 1 | repository rebased against current SHA | PASS | Report §2. Inventory refreshed at unchanged current SHA before deletions. |
| 2 | test_ai developer probe removed from pytest topology | PASS | Report §3. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 3 | tender API probe removed from pytest topology | PASS | Report §3. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 4 | Uzbek NLP/OpenAPI probe removed from pytest topology | PASS | Report §3. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 5 | moved probes have explicit main | PASS | Report §3. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 6 | probe imports perform zero I/O | PASS | Report §4. Four probes passed isolated import checks; operational dependencies forbidden during execution. |
| 7 | broad collection performs no probe I/O | PASS | Report §4. Guarded recursive backend collector passed with zero detected side effects. |
| 8 | duplicate basename inventory rerun | PASS | Report §5. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 9 | colliding script proof files renamed | PASS | Report §5. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 10 | all renamed-script imports updated | PASS | Report §5. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 11 | pytest import mismatch eliminated | PASS | Report §5. Original mismatch reproduced; final 615-test collection clean. |
| 12 | all ten stale assertions semantically repaired | PASS | Report §6. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 13 | stale nodes 10/10 pass | PASS | Report §6. Exact ten IDs: 10 passed; none deselected. |
| 14 | no stale test simply deselected | PASS | Report §6. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 15 | `_bounded_int` removed only after zero-caller proof | PASS | Report §7. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 16 | `_strict_bool` removed only after zero-caller proof | PASS | Report §7. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 17 | registry validation preserved | PASS | Report §7. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 18 | `_normalized_source_result` tests migrated | PASS | Report §8. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 19 | obsolete result helper removed | PASS | Report §8. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 20 | source result semantics preserved | PASS | Report §8. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 21 | jwt-decode zero-use proof confirmed | PASS | Report §9. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 22 | tailwind-merge zero-use proof confirmed | PASS | Report §9. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 23 | only those proven-unused dependencies removed | PASS | Report §9. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 24 | no unrelated dependency upgrade | PASS | Report §9. Every unrelated lockfile package record is identical. |
| 25 | clean npm install succeeds | PASS | Report §9. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 26 | GIZ duplicate closure identified by function/call graph | PASS | Report §10. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 27 | canonical GIZ service preserved | PASS | Report §10. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 28 | heavy GIZ task preserved | PASS | Report §10. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 29 | archive/security limits preserved | PASS | Report §10. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 30 | only closed duplicate GIZ functions deleted | PASS | Report §10. Exact 22-name closure only; 199 surviving Tender definitions AST-identical. |
| 31 | no ADB helper deleted | PASS | Report §10. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 32 | no EBRD helper deleted | PASS | Report §10. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 33 | security package/module topology proven | PASS | Report §11. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 34 | security shadow removed only if truly redundant | PASS | Report §11. Shadow and package AST equal before removal; three static readers migrated. |
| 35 | auth behavior unchanged by security topology cleanup | PASS | Report §11. Canonical security package AST unchanged. |
| 36 | existing security regressions pass | PASS | Report §25. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 37 | DocumentViewer not deleted | PASS | Report §12. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 38 | DocumentViewer move is behavior-neutral if performed | PASS (KEEP / not applicable) | Report §12. KEEP decision; no move performed. |
| 39 | ACCESS_TOKEN_EXPIRE_MINUTES handled without changing token expiry | PASS | Report §13. No tracked example/config value required removal; eight-hour constant preserved. |
| 40 | public API build variables handled only with deployment-caller proof | PASS | Report §13. KEEP build inputs due to Docker/Compose/release callers. |
| 41 | private .env files not automatically mutated | PASS | Report §13. Private environment files untouched. |
| 42 | historical/operator-dangerous tools classified | PASS | Report §14. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 43 | compatibility ledger completed | PASS | Report §15. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 44 | Hunter redirect decision explicit | PASS | Report §15. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 45 | Hunter HTTP decision explicit | PASS | Report §15. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 46 | active Hunter worker preserved | PASS | Report §15. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 47 | active Hunter agent preserved | PASS | Report §15. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 48 | Celery task-name compatibility preserved | PASS | Report §15. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 49 | source sync adapters kept unless explicitly approved otherwise | PASS | Report §15. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 50 | legacy frontend redirects kept by default | PASS | Report §15. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 51 | tracked cache inventory exact | PASS | Report §16. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 52 | tracked Python caches removed | PASS | Report §16. Exactly 53 index removals; local cache bytes retained. |
| 53 | ignore rules preserved | PASS | Report §16. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 54 | test/import run leaves no cache dirtiness | PASS | Report §16. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 55 | no translation key deleted by regex-only proof | PASS | Report §17. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 56 | any deleted translation key has namespace-aware proof | PASS (KEEP / not applicable) | Report §17. Not applicable: no translation keys deleted. |
| 57 | four-locale catalog parity preserved | PASS | Report §17. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 58 | Arabic analysis remains gated | PASS | Report §24. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 59 | Arabic PDF gate remains | PASS | Report §24. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 60 | no ORM table deleted | PASS | Report §19. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 61 | no migration deleted/squashed | PASS | Report §19. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 62 | all five source definitions preserved | PASS | Report §19. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 63 | ADB/EBRD recovery foundations preserved | PASS | Report §19. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 64 | no new migration | PASS | Report §19. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 65 | Alembic remains single clean head | PASS | Report §26. Disposable bootstrap/current/check pass at sole expected head. |
| 66 | broad maintained pytest collection succeeds | PASS | Report §20. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 67 | no import-time network/model/chdir | PASS | Report §4. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 68 | maintained backend suite has zero unexpected failures | PASS | Report §21. 614 passed, 0 failed, 1 skipped, 100 subtests passed. |
| 69 | frontend typecheck passes | PASS | Report §22. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 70 | ESLint passes | PASS | Report §22. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 71 | message validation passes | PASS | Report §22. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 72 | RTL audit passes | PASS | Report §22. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 73 | production build passes | PASS | Report §22. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 74 | connector gate passes | PASS | Report §23. 196 passed, 0 failed, 1 skipped, 6 subtests passed. |
| 75 | SR-2.x regression passes | PASS | Report §21. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 76 | SR-3 regression passes | PASS | Report §21. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 77 | Sprint 8 regression passes | PASS | Report §24. Included backend and frontend Sprint 8 checks pass; historical browser launchers not claimed. |
| 78 | Compliance/version regression passes | PASS | Report §21. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 79 | Sprint 6 regression passes | PASS | Report §21. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 80 | Sprint 5 workflow regressions pass | PASS | Report §21. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 81 | existing auth regression suite passes | PASS | Report §25. Existing auth/security suite passes; does not certify H01/H02. |
| 82 | no H01/H02 behavior accidentally legitimized | PASS | Report §29. No new assertion approves the known bypasses; auth/GET implementation unchanged. |
| 83 | working tree contains only intended changes | PASS | Report §27. Intended 9.2 diff separated from accepted pre-existing 9.1 additions. |
| 84 | exact changed-file inventory returned | PASS | Report §28. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 85 | H01–H12 carried forward explicitly | PASS | Report §29. Every H01–H12 item explicitly open; H01/H02 mandatory 9.3 blockers. |
| 86 | application is NOT declared release-ready | PASS | Report §1. Cleanup PASS is explicitly separate from release readiness. |
| 87 | no ADB recovery | PASS | Report §31. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 88 | no EBRD recovery | PASS | Report §31. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 89 | no deployment | PASS | Report §31. Implemented or preserved as documented; relevant retained gate evidence applies. |
| 90 | no production access/mutation. | PASS | Report §31. Implemented or preserved as documented; relevant retained gate evidence applies. |
