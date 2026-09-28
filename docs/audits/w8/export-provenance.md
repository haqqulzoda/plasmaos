# W8 Export Provenance Audit

PDF, DOCX, and JSON are generated solely from the sealed pack response. The export payload declares the pack ID/version/hash, sealing timestamp, source categories, reviewed structured facts, generated summary boundary, and `commercial_price_included=false`.

JSON is canonical. PDF generation uses invariant metadata. DOCX ZIP members have stable ordering and timestamps. Artifacts are immutable and record type, SHA-256, bytes, creator, media type, generator version, and historical status.

Opaque private keys stay server-side. Downloads validate Organization, Pursuit, pack/artifact relationship, active Membership, on-disk size, and hash. Filesystem keys are absent from responses.
