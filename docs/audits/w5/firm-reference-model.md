# W5 Firm and ProjectReference Model

`Firm` records canonical, display, and legal names; geography; services; capabilities; sectors; source; scope; evidence state; and timestamps. It has no foreign key to `Organization` except the optional private-scope owner used solely for visibility.

`ProjectReference` records project name, client, geography, service, sector, the Firm's actual role, proven share, proven value, currency, value basis, dates, completion state, relevant scope, provenance, and evidence review state.

Database constraints preserve value truth:

- a value requires currency and an explicit value basis;
- `UNKNOWN` cannot accompany a recorded value;
- shares remain between 0 and 100;
- completion cannot predate start;
- participation role and completion state are separate;
- total contract or consortium value is never labeled as Firm share.

Qualification counts only reviewed or verified completed references that overlap the exact Gap. Historical participation alone cannot produce `SUPPORTED_BY_EVIDENCE`.

