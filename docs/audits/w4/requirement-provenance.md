# W4 Requirement Provenance

Every Requirement belongs to one run and one sealed pack item. Persisted evidence includes the verbatim quote, optional verbatim table/header/list context, character span, page only when a source marker supports it, paragraph fallback, and the exact pack identity.

The analyzer receives only sealed text. Document content is delimited as untrusted data. Structured output must preserve numeric operators, thresholds, units, conditions, exceptions, preference/scoring status, and contribution rules. Before persistence, the service verifies both quote and supplied source context occur in the sealed text. Unsupported or unclear rules remain NEEDS_INTERPRETATION.

The UI shows source document and original-language evidence before normalized or generated interpretation. Reviewer corrections apply through append-only assertions and cannot change quotes, locators, spans, pack IDs, or machine output.
