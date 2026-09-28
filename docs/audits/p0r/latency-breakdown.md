# P0R latency breakdown

All duration values come from monotonic timers. ISO timestamps are retained for event ordering only because container wall time was corrected during the long provider calls. Only one live attempt succeeded, so no p50-like statistic is claimed.

## W3 upload and processing

| Component | Duration |
| --- | ---: |
| Upload request | 1.010000 s |
| Processing after upload response | 4.311996 s |
| Total upload start to customer-observed `READY` | 5.321996 s |
| Parser/scan worker execution inside that interval | 3.669481 s |

The document finished `CLEAN` and `READY` with 8 known pages and 16,594 extracted characters.

## W4 attempts

| Component | Attempt 1 failure | Attempt 2 success | Attempt 3 failure |
| --- | ---: | ---: | ---: |
| Analyze/seal API request | Not separately retained | 0.128755 s | 0.041662 s |
| Queue wait after API response | Not separately retained | ≈0.004 s | Effectively immediate / below timestamp resolution |
| Provider/model execution | 344.203338 s | 51.242189 s | 345.994519 s |
| Validation/persistence | Not completed due pre-fix rollback defect | ≈0.301912 s | <2.798833 s upper bound, including poll delay |
| Request accepted to customer-observed result | Provider failure followed by defect | 53.038844 s | 348.793352 s |
| Click/request start to customer-observed result | Not reliably retained | ≈53.167599 s | ≈348.835014 s |

Attempt 2 is the only reviewable live result. Its click-to-reviewable duration was approximately 53.168 seconds. The two other provider calls ran for about 5.7 minutes before returning malformed JSON. These bounded observations show significant reliability and latency variance; they do not establish an SLA.

## Worker timing and leases

- Analysis Celery task soft/hard limits for this canary: 600/660 seconds.
- Application analysis lease: 300 seconds; heartbeat target: 60 seconds; internal max attempts: 3.
- All canary requests had retry count 0. Attempt 3 showed continuing heartbeat renewals and a cleared lease after failure persistence.
- Private-document worker: queue `private_documents`, concurrency 1.
- Analysis worker: queue `pursuit_analysis`, prefork concurrency 1, `max-tasks-per-child=10`.
