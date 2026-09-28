# W6 Tenant Isolation

Root and child rows carry Organization ownership. Pursuit and actor references use composite Organization foreign keys. Every read first filters roots by Organization and Pursuit. Cross tenant identifiers return no record.

Participation for a `NETWORK_SHARED` Firm or Expert remains Organization private. W6 never adds participation fields to shared candidate schemas and never reports that a candidate is busy for another customer. Same candidate detection is limited to roots inside the current Organization and Pursuit.

Raw private notes can be stored on availability and interest facts but are excluded from every response and Team list surface.
