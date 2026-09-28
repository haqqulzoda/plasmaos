# W4 Position Extraction

Positions are an independent aggregate, not a Requirement subtype or company credential. Fields cover title, quantity, mandatory/scored status, education, general and specific experience, relevant assignments, languages, certifications, location/travel, effort, dates, and exact sealed evidence.

The extraction schema requires a POSITION fact to carry position details and rejects position details on a corporate Requirement. Position coverage defaults to EVIDENCE_MISSING for current-stage work because W4 does not infer CV facts from company profiles. A current-stage Position produces an EXPERT resolution label only; no retrieval or matching exists in W4. Later-stage positions remain nonblocking obligations.

The permanent test supplies a corporate experience threshold and a Team Leader requirement in the same document and proves they persist in different tables without crossing their experience fields.
