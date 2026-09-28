# W7 Tenant Isolation Audit

All W7 tables carry `organization_id`. Roots bind Organization and Pursuit; revisions and decisions bind an actor Membership in that Organization; descendants bind revision and Organization through composite foreign keys.

Every route resolves an approved user and Organization context. List and detail queries filter by Organization and Pursuit before projection. Cross tenant detail uses a not found response, and cross tenant lists are empty.

A `NETWORK_SHARED` Expert may be independently selected by several Organizations, but scenario roots, contributions, W6 fact snapshots, issues, decisions, and capacity remain private. The permanent integration proof uses a network shared Expert and verifies that the second Organization sees no scenario rows.

