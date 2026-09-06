# Sprint 9.3 — Requested Result Index

See [the 36-section report](../../S9_3_RELEASE_HARDENING.md) for evidence and limitations.

1. **SPRINT 9.3 STATUS** — PASS — local Sprint 9.3 acceptance complete; no deployment or production access.
2. **REPOSITORY PREFLIGHT** — main at b121cda5b76911c59fdab5733d70aa6883908e9c; accepted S9.1/S9.2 work retained.
3. **ALEMBIC HEAD** — 20260904_0001_s8_2_analysis_language, unchanged sole head.
4. **H01 PREVIOUS STATE** — Caller asserted identity without cryptographic backend proof.
5. **H01 TRUST MODEL** — Verified Auth.js Google callback signs a server-only, short-lived assertion.
6. **GOOGLE TOKEN / BRIDGE VERIFICATION** — HS256, issuer, audience, subject/email, verification flag, expiry, issuance time and single-use UUID enforced.
7. **ACCOUNT RECONCILIATION RESULT** — Existing lifecycle and allowlists retained; conflicting identities rejected with 409.
8. **IMPERSONATION MATRIX** — All maintained negative cases denied before account reads/writes.
9. **VALID LOGIN MATRIX** — Pending, approved, restored, operator and admin policies pass.
10. **AUTH_VERSION RESULT** — Every protected backend request still checks current auth_version.
11. **PRIVILEGE ESCALATION RESULT** — Changed allowlisted identity cannot match ordinary signed claims.
12. **H01 LOGGING RESULT** — No tokens or signing secrets emitted by the bridge.
13. **H02 ROUTE INVENTORY** — 18 GET handlers documented in tender-read-inventory.json.
14. **H02 GUARD RESULT** — Canonical approved-user/pilot and resource guards enforced directly.
15. **DIRECT BACKEND AUTH MATRIX** — 45 direct cases and real HTTP browser counterparts pass.
16. **STATUS SEMANTICS RESULT** — 401 unauthenticated/revoked, 403 pending, authorized absent-resource 404.
17. **H03 CALL GRAPH** — Stored reads separated from explicit source/worker commands.
18. **PASSIVE TENDER GET RESULT** — Zero source calls; live date/contact retrieval removed.
19. **PASSIVE TENDER DETAILS RESULT** — Stored Tender Details only; read fingerprint unchanged.
20. **PASSIVE COMPLIANCE RESULT** — Latest/history reads remain passive and ownership-bound.
21. **DOCUMENT PREVIEW RESULT** — Missing stored document returns 404; no scrape/download fallback.
22. **EXPLICIT REFRESH RESULT** — Existing explicit source refresh preserved.
23. **EXPLICIT HYDRATION RESULT** — Existing sync-docs/worker hydration preserved.
24. **PASSIVITY INSTRUMENTATION** — HTTP/browser/analysis/dispatch spies plus DB fingerprints and Chromium network interception.
25. **H04 PREVIOUS FILTER RESULT** — 10k baseline prepass loaded all Tenders and checked 5,000 stored files.
26. **H04 BOUNDING RESULT** — Stored SQL predicates precede pagination; no application corpus prepass.
27. **DOCUMENT AVAILABILITY TRUTH RESULT** — URL metadata alone is unavailable; stored-state drift is disclosed and page/download truth stays missing.
28. **SCALE / PERFORMANCE RESULT** — 1k/10k/100k synthetic PostgreSQL passes; 25 rows and at most 25 fixture file checks.
29. **EXPLAIN RESULT** — Count/page EXPLAIN ANALYZE BUFFERS retained; no new index.
30. **PROPOSAL PAGINATION** — Default 25, maximum 100, stable ordering, additive headers and total.
31. **COMPLIANCE HISTORY PAGINATION** — Default 25, maximum 100, stable versions and URL historyPage.
32. **COMPLIANCE LEAN METADATA RESULT** — Snapshot columns and document relationships excluded with raiseload.
33. **READINESS PAGINATION** — Default 25, maximum 100; filters before pagination; total/header contract.
34. **ADMIN APPROVAL PAGINATION** — Default 25, maximum 100; envelope ordering and pagination preserved.
35. **API COMPATIBILITY RESULT** — Existing arrays retained; client pagination updated atomically.
36. **H05 SIZE LIMIT** — 20 MiB file and 21 MiB multipart request.
37. **H05 STREAMING RESULT** — Bounded multipart spool and 64 KiB staging reads.
38. **FILE SIGNATURE RESULT** — PDF magic plus structural PDF validation.
39. **FILE TYPE RESULT** — PDF only; no new supported format.
40. **FILENAME SAFETY** — Random tenant-scoped storage; hostile display names cannot control paths.
41. **TEMP CLEANUP** — Partial spools/staging files closed and removed, including errors.
42. **PARSE FAILURE RESULT** — Failure/empty text prevents model execution.
43. **MODEL FAILURE RESULT** — Safe failure, no success commit or state replacement.
44. **UPLOAD ABUSE RESULT** — Redis four shared slots, per-user 30-second rate limit, bounded child processes.
45. **H06 ERROR INVENTORY** — Auth, validation, uploads, source probes, document proxy, analysis history and diagnostics reviewed.
46. **STABLE ERROR CONTRACT** — Safe status/detail contracts; hardened boundary also supplies stable code/request_id.
47. **RAW EXCEPTION RESULT** — Internal exception strings removed from hardened responses.
48. **PYDANTIC LOGGING RESULT** — Input/context and raw validation objects excluded.
49. **PROVIDER LOGGING RESULT** — Safe event/type diagnostics replace raw provider exception logging.
50. **FRONTEND ERROR LOGGING** — No raw caught response/error objects logged.
51. **CORRELATION RESULT** — Server-generated UUID response/header correlation.
52. **H07 CREDENTIAL CONFIG RESULT** — Tracked release credentials/default passwords removed; explicit secrets required.
53. **DATABASE EXPOSURE RESULT** — No PostgreSQL host port published.
54. **PGADMIN RESULT** — Development profile only; loopback GUI and supplied credentials.
55. **DANGEROUS FLAG RESULT** — Unsafe schema/demo/pseudo flags fail production/release validation.
56. **SECURITY HEADER RESULT** — CSP/frame protection, nosniff, referrer and cache headers; HTTPS HSTS contract.
57. **CSRF / ORIGIN RESULT** — Cookie mutations require trusted Origin; Bearer authority preserved.
58. **CORS RESULT** — Explicit HTTPS credentialed release origins; required response headers exposed.
59. **SSRF RESULT** — Two-host HTTPS/public-DNS allowlist; browser redirects rechecked; HTTPX probe redirects disabled.
60. **H08 AUDIT RESULT** — 18 prior advisories reduced to zero in locked npm audit.
61. **DEPENDENCY UPDATE RESULT** — Targeted framework/auth/HTTP/image/toolchain updates; exact lock diff retained.
62. **FRAMEWORK COMPATIBILITY RESULT** — Next 16.2.11/Auth.js beta.32 pass production build and browser checks.
63. **BACKEND REPRODUCIBILITY** — Exact stable Python constraints; Python 3.12 target; pip check passes.
64. **TEST DEPENDENCY RESULT** — requirements-test.txt pins the complete verification environment.
65. **H10 PRODUCTION REQUEST BASELINE** — Seven production pages plus four client-navigation baselines recorded.
66. **USERS/ME RESULT** — Hard-load users/me counts reduced from 20–27 to 3–7.
67. **REVOCATION RESULT** — No authority TTL/cache introduced; revocation next navigation denied.
68. **REQUEST BUDGET RESULT** — Hard-load cap 30 total, 8 me, 4 access-status and 6 refresh requests.
69. **H11 SIGN-IN ROUTE RESULT** — Canonical sign-in remains /.
70. **SESSION EXPIRY RESULT** — Expired/missing session returns to real sign-in, never /login.
71. **TRANSIENT ACCESS FAILURE RESULT** — Outage shows temporary unavailable, not pending approval.
72. **RETRY UX RESULT** — Localized retry preserves the same route/query.
73. **AUTH STATE BROWSER MATRIX** — Synthetic real-backend account-state cases pass.
74. **BID PREPARATION MOBILE RESULT** — Header/badge layout wraps without overlap.
75. **MY TENDERS MOBILE RESULT** — Search/filter inputs shrink and stack; pagination wraps.
76. **EXPLORER MOBILE RESULT** — Tabs and pagination wrap; filter/menu controls fit.
77. **RTL MOBILE RESULT** — Arabic 320/390/768/1440 direction and control bounds checked.
78. **READINESS DIAGNOSTIC RESULT** — Readiness probes DB/Redis with two-second limits.
79. **QUEUE DIAGNOSTIC RESULT** — Admin queue lengths, recent failure/retry sample and oldest queue age added.
80. **FAILURE DIAGNOSTIC RESULT** — Safe 503, no raw job options/messages/secrets.
81. **PERMANENT RELEASE GATE** — Maintained scripts/run_release_gate.sh with nine groups and all.
82. **BACKEND CORE GATE** — Broad maintained backend suite integrated.
83. **SECURITY GATE** — 118 focused security/read/config/upload/runtime tests pass.
84. **ANALYSIS GATE** — 50 tests and 12 subtests pass.
85. **CONNECTOR GATE INTEGRATION** — Existing connector gate invoked unchanged as a group.
86. **MIGRATION GATE** — Own disposable DB bootstrap/head/current/drift/schema checks.
87. **FRONTEND GATE** — npm ci, TypeScript, ESLint, 159 frontend tests, RTL audit and production build.
88. **BROWSER GATE** — Portable installed Playwright Chromium; no Windows browser path.
89. **CONFIG / DEPENDENCY GATE** — Safe config, exact stable Python constraints, pip check and npm audit.
90. **CI RESULT** — GitHub workflow added; remote job not executed.
91. **PRODUCTION-TARGET PROTECTION** — Loopback host, disposable DB prefix and explicit confirmation required before imports.
92. **PERFORMANCE BUDGET RESULT** — Executable query/page/file and production request budgets.
93. **PASSIVITY REGRESSION GATE** — Spies fail on unexpected source/generation work; fingerprints reject writes.
94. **AUTH REGRESSION GATE** — Self-asserted identity regression cannot obtain a backend token.
95. **UPLOAD REGRESSION GATE** — Signature/size/parse/model/commit/cleanup/timeout/rate regressions maintained.
96. **ERROR REDACTION GATE** — Secret/token/customer sentinels absent from hardened response/log paths.
97. **SECURITY CONFIG GATE** — Unsafe flags/origins/credentials/public DB bind rejected.
98. **API PERFORMANCE RETEST** — 100k synthetic pages return at most 25 rows with 3–5 queries and 0–25 fixture file checks.
99. **FRONTEND REQUEST RETEST** — Real production before/after and client navigation counts retained.
100. **PASSIVE DB FINGERPRINT** — 15 GETs preserve domain fingerprints with zero domain DML.
101. **SOURCE NETWORK FINGERPRINT** — Controlled major page loads record zero external-source requests.
102. **AUTH DB FINGERPRINT** — Invalid proof performs no account read/write; valid account bookkeeping preserved.
103. **UPLOAD DB FINGERPRINT** — Failed upload preserves prior state and never commits false success.
104. **MIGRATION RESULT** — No migration added.
105. **FRONTEND QUALITY** — 159 frontend tests pass; typecheck, clean lint, RTL and production build pass.
106. **BACKEND QUALITY** — 732 passed, 1 existing skipped, 100 subtests passed.
107. **CONNECTOR GATE** — 196 passed, 1 existing skipped, 6 subtests passed.
108. **SPRINT 8 REGRESSION** — Four UI locales, EN/UZ/RU analysis and Arabic gates preserved.
109. **SR-3 REGRESSION** — Source refresh, cursor, notifications, New badge and one-poller contracts preserved.
110. **SPRINT 6 / 5 REGRESSION** — Explorer, Tender Details, My Tenders and Bid Preparation gates pass.
111. **COMPLIANCE / VERSION REGRESSION** — Ownership/version immutability/history/detail/export/concurrency/language gates pass.
112. **AUTH REGRESSION** — Existing lifecycle plus proof/replay/revocation regression passes.
113. **BROWSER SECURITY MATRIX** — Real HTTP authority/impersonation/login/replay checks included.
114. **BROWSER PASSIVITY MATRIX** — Details, Compliance, Explorer, stored document proxy, My Tenders, Bid Preparation and Readiness checked.
115. **BROWSER MOBILE MATRIX** — Four locales × four widths × three surfaces plus outage recovery.
116. **BROWSER ACCESSIBILITY** — Visible controls, menu bounds, keyboard focus, ARIA/RTL contracts retained.
117. **FINAL CHROMIUM ACCEPTANCE** — 145/145 passed; 0 failed
118. **H01 CLOSURE** — Closed and security gate passes.
119. **H02 CLOSURE** — Closed and backend guard matrix passes.
120. **H03 CLOSURE** — Closed and passivity/fingerprint gates pass.
121. **H04 CLOSURE** — Closed with bounded SQL/page storage work and documented drift semantics.
122. **H05 CLOSURE** — Closed with failure fingerprints and processing bounds.
123. **H06 CLOSURE** — Closed with stable errors/redaction and historic-read protection.
124. **H07 CLOSURE** — Closed; deployment provisioning/TLS/egress caveats documented.
125. **H08 DISPOSITION** — Zero npm advisories; bounded updates and exact reproducibility documented.
126. **H09 CLOSURE** — All four collections bounded, ordered and client-compatible.
127. **H10 CLOSURE** — Bounded with real request evidence; no revocation weakening.
128. **H11 CLOSURE** — Recovery/sign-in/transient-state fixes pass.
129. **H12 CLOSURE** — Narrow layout/RTL fixes pass controlled cases.
130. **EXACT FILES CHANGED** — See changed-files.md and changed-files.json for exact baseline-relative paths/hashes.
131. **DOCUMENT CREATED** — docs/S9_3_RELEASE_HARDENING.md with all 36 requested sections.
132. **REMAINING RISKS** — Synthetic/provider/container/remote-CI/egress/storage-density limits explicitly disclosed.
133. **SPRINT 9.4 ENTRY CONTRACT** — Evidence handoff only; Sprint 9.4 has not been started.
134. **RECOMMENDED NEXT TASK** — Review Sprint 9.3 acceptance, then separately authorize the next sprint; no deployment.
