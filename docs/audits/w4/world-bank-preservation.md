# W4 World Bank Preservation

W4 reads issued TenderDocument text only when a customer explicitly selects and seals it. It does not read Project Context or Project Leadership into the analysis pack and does not use ProjectRoleAssignment as personnel evidence.

The migration is additive and does not rewrite projects, tender_projects, project_role_assignments, tenders, legacy tender_analyses, or analysis_versions. Procurement contacts remain separate from Project Leadership. A project leader is never converted to a Position, Expert, or company evidence record.

The permanent PostgreSQL test hashes the World Bank project, current leadership, legacy TenderAnalysis, and legacy AnalysisVersion before W4 activity and proves their rows remain byte-for-byte unchanged afterward.
