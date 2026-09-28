# P1 customer-language audit

## Result

The five workspace labels are customer concepts in all supported UI locales: Overview, Requirements, Team, Documents & Evidence, and Proposal. Activity is absent. Team assembly is called **Team options**; proposal preparation uses **Create evidence pack** and **Evidence manifest**.

Normal views do not render processing enums, provider/model names, failure payloads, UUIDs, gap IDs, or hashes. Document roles, requirement distinctions, coverage, P1 workspace status/action labels, and provenance use localized customer copy. Source and manifest hashes remain available only under explicitly labeled technical details.

The EN, UZ, RU, and AR pursuit catalogs have identical key and ICU-placeholder topology. Arabic retains RTL direction, while source content remains bidirectional text rather than being translated or mutated.

## Checks

- Full frontend static suite validates catalog parity.
- P1 tests assert the customer terminology and absence of Activity.
- RTL audit reports no physical-direction, icon-direction, or authority violations.
