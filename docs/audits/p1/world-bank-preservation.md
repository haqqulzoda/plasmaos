# P1 World Bank preservation audit

## Result

SOURCE pursuits retain the established tender-details authority. Overview lazily reads `/tenders/{source_tender_id}/details` and renders the canonical `project_context.data` and `project_leadership.data.items` projections under Project Context and Project Leadership.

The implementation does not infer leadership, contacts, email, dates, or tender actionability. It links back to the canonical source tender for the full context. A source-detail failure is isolated to these optional sections and does not fail the pursuit workspace.

No World Bank schema, enrichment job, connector, source identity, or existing Tender Details presentation was changed.
