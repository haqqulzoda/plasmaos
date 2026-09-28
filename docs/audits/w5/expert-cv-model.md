# W5 Expert and CVVersion Model

`Expert` is a candidate authority with name, scope, qualifications, languages, specializations, consent state, evidence state, provenance, and timestamps. No leadership, procurement contact, generic contact, or competitor table feeds it.

`CVVersion` is append only. A new version receives the next positive version number under an Expert row lock and a SHA-256 over canonical structured facts. Database triggers reject update and delete.

The structured authority covers education, qualifications, certifications, assignments, actual role and dates inside assignment facts, relevant scope, languages, provenance, and evidence state. W5 stores no CV file in `TenderDocument`. No algorithm blindly sums assignment durations; a general experience duration requirement remains partial or needs review unless future reviewed logic can account for overlaps.

