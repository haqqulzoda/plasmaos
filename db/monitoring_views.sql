-- Plasma OS database monitoring views for DBeaver/pgAdmin.
-- Run this file against the plasma_ai database.

create or replace view monitor_users as
select
    u.id,
    u.email,
    u.name,
    u.subscription_tier,
    u.is_admin,
    u.company_name,
    u.phone_contact,
    u.created_at,
    count(distinct p.id) as proposal_count,
    count(distinct ta.id) as analysis_count
from users u
left join proposals p on p.user_id = u.id
left join tender_analyses ta on ta.company_name like u.id::text || ':%'
group by u.id
order by u.created_at desc;

create or replace view monitor_tender_documents as
select
    td.id,
    td.tender_id,
    t.external_id,
    t.title as tender_title,
    td.file_type,
    td.file_size,
    td.storage_path,
    td.file_url,
    case
        when td.parsed_text is null or length(trim(td.parsed_text)) = 0 then false
        else true
    end as has_parsed_text,
    length(coalesce(td.parsed_text, '')) as parsed_text_chars,
    td.created_at
from tender_documents td
join tenders t on t.id = td.tender_id
order by td.created_at desc;

create or replace view monitor_user_uploaded_tz as
select
    p.id as proposal_id,
    p.user_id,
    u.email,
    u.name,
    p.tender_id,
    t.title as tender_title,
    p.structured_data ->> 'uploaded_tz_path' as uploaded_tz_path,
    case
        when coalesce(p.structured_data ->> 'uploaded_tz_text', '') = '' then false
        else true
    end as has_extracted_text,
    length(coalesce(p.structured_data ->> 'uploaded_tz_text', '')) as extracted_text_chars,
    p.created_at
from proposals p
join users u on u.id = p.user_id
join tenders t on t.id = p.tender_id
where p.structured_data::jsonb ? 'uploaded_tz_path'
order by p.created_at desc;

create or replace view monitor_proposals as
select
    p.id,
    p.user_id,
    u.email,
    u.name,
    p.tender_id,
    t.external_id,
    t.title as tender_title,
    p.status,
    p.ai_confidence_score,
    p.final_pdf_url,
    p.created_at
from proposals p
join users u on u.id = p.user_id
join tenders t on t.id = p.tender_id
order by p.created_at desc;

create or replace view monitor_tender_sync_jobs as
select
    tsj.id,
    tsj.job_id,
    tsj.user_id,
    u.email,
    tsj.tender_id,
    t.title as tender_title,
    tsj.status,
    tsj.progress,
    tsj.error_message,
    tsj.created_at,
    tsj.updated_at
from tender_sync_jobs tsj
join users u on u.id = tsj.user_id
join tenders t on t.id = tsj.tender_id
order by tsj.updated_at desc;

create or replace view monitor_company_tender_dossier as
select
    u.id as user_id,
    u.email,
    u.name as user_name,
    coalesce(cp.company_name, u.company_name) as company_name,
    cp.id as company_profile_id,
    t.id as tender_id,
    t.external_id,
    t.title as tender_title,
    t.budget,
    t.currency,
    t.deadline,
    t.region,
    t.status as tender_status,
    p.id as proposal_id,
    p.status as proposal_status,
    p.ai_confidence_score,
    p.final_pdf_url,
    p.structured_data ->> 'strategic_summary' as strategic_summary,
    p.structured_data ->> 'uploaded_tz_path' as uploaded_tz_path,
    p.structured_data ->> 'our_price' as proposed_price,
    p.structured_data ->> 'delivery_days' as delivery_days,
    latest_analysis.id as latest_analysis_id,
    latest_analysis.created_at as latest_analysis_at,
    latest_analysis.content_hash,
    latest_analysis.override_seal,
    latest_analysis.analysis_json -> 'evaluation' as compliance_evaluation,
    latest_analysis.analysis_json -> 'strategy_intelligence' as strategy_intelligence,
    coalesce(doc_stats.document_count, 0) as document_count,
    coalesce(doc_stats.parsed_document_count, 0) as parsed_document_count,
    coalesce(doc_stats.total_file_size, 0) as total_document_bytes,
    coalesce(override_stats.override_count, 0) as override_count,
    rec.match_score as recommendation_match_score,
    rec.strategic_rationale as recommendation_rationale,
    rec.is_dismissed as recommendation_dismissed,
    p.created_at as proposal_created_at
from proposals p
join users u on u.id = p.user_id
join tenders t on t.id = p.tender_id
left join company_profiles cp on cp.user_id = u.id
left join lateral (
    select ta.*
    from tender_analyses ta
    where ta.tender_id = p.tender_id
      and ta.company_name = u.id::text || ':' || coalesce(cp.id::text, 'no-profile')
    order by ta.created_at desc
    limit 1
) latest_analysis on true
left join lateral (
    select
        count(*)::bigint as document_count,
        count(*) filter (
            where td.parsed_text is not null
              and length(trim(td.parsed_text)) > 0
        )::bigint as parsed_document_count,
        coalesce(sum(td.file_size), 0)::bigint as total_file_size
    from tender_documents td
    where td.tender_id = p.tender_id
) doc_stats on true
left join lateral (
    select count(*)::bigint as override_count
    from risk_override_logs rol
    where rol.user_id = p.user_id
      and rol.tender_id = p.tender_id
) override_stats on true
left join tender_recommendations rec
    on rec.tender_id = p.tender_id
   and rec.company_profile_id = cp.id
order by p.created_at desc;

create or replace view monitor_compliance_analyses as
with normalized_analyses as (
    select
        ta.*,
        case
            when ta.company_name ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:'
            then split_part(ta.company_name, ':', 1)::uuid
            else null
        end as owner_user_id,
        case
            when split_part(ta.company_name, ':', 2) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            then nullif(split_part(ta.company_name, ':', 2), '')::uuid
            else null
        end as owner_company_profile_id
    from tender_analyses ta
)
select
    ta.id as analysis_id,
    ta.tender_id,
    t.external_id,
    t.title as tender_title,
    ta.owner_user_id as user_id,
    u.email,
    u.name as user_name,
    coalesce(cp.company_name, u.company_name, ta.analysis_json ->> 'tenant_company_name') as company_name,
    ta.owner_company_profile_id as company_profile_id,
    (ta.analysis_json::jsonb #>> '{evaluation,is_compliant}')::boolean as is_compliant,
    ta.analysis_json::jsonb #>> '{evaluation,status_message}' as compliance_status_message,
    jsonb_array_length(coalesce(ta.analysis_json::jsonb #> '{evaluation,met_requirements}', '[]'::jsonb)) as met_requirement_count,
    jsonb_array_length(coalesce(ta.analysis_json::jsonb #> '{evaluation,missing_requirements}', '[]'::jsonb)) as missing_requirement_count,
    jsonb_array_length(coalesce(ta.analysis_json::jsonb #> '{evaluation,unmapped_requirements}', '[]'::jsonb)) as unmapped_requirement_count,
    ta.analysis_json -> 'evaluation' as compliance_evaluation,
    ta.analysis_json -> 'hybrid_compliance' as hybrid_compliance,
    ta.analysis_json -> 'strategy_intelligence' as strategy_intelligence,
    ta.content_hash,
    ta.override_seal,
    ta.created_at
from normalized_analyses ta
join tenders t on t.id = ta.tender_id
left join users u on u.id = ta.owner_user_id
left join company_profiles cp on cp.id = ta.owner_company_profile_id
order by ta.created_at desc;

create or replace view monitor_compliance_missing_requirements as
select
    ca.analysis_id,
    ca.tender_id,
    ca.external_id,
    ca.tender_title,
    ca.user_id,
    ca.email,
    ca.company_name,
    item ->> 'uuid' as taxonomy_node_id,
    item ->> 'name' as requirement_name,
    nullif(item ->> 'impact_weight', '')::int as impact_weight,
    nullif(item ->> 'is_fatal', '')::boolean as is_fatal,
    ca.created_at as analysis_created_at
from monitor_compliance_analyses ca
cross join lateral jsonb_array_elements(
    coalesce(ca.compliance_evaluation::jsonb -> 'missing_requirements', '[]'::jsonb)
) as item
order by ca.created_at desc, is_fatal desc, impact_weight desc;

create or replace view monitor_compliance_met_requirements as
select
    ca.analysis_id,
    ca.tender_id,
    ca.external_id,
    ca.tender_title,
    ca.user_id,
    ca.email,
    ca.company_name,
    item ->> 'uuid' as taxonomy_node_id,
    item ->> 'name' as requirement_name,
    ca.created_at as analysis_created_at
from monitor_compliance_analyses ca
cross join lateral jsonb_array_elements(
    coalesce(ca.compliance_evaluation::jsonb -> 'met_requirements', '[]'::jsonb)
) as item
order by ca.created_at desc, requirement_name asc;

create or replace view monitor_compliance_unmapped_requirements as
select
    ca.analysis_id,
    ca.tender_id,
    ca.external_id,
    ca.tender_title,
    ca.user_id,
    ca.email,
    ca.company_name,
    item #>> '{}' as requirement_text,
    ca.created_at as analysis_created_at
from monitor_compliance_analyses ca
cross join lateral jsonb_array_elements(
    coalesce(ca.compliance_evaluation::jsonb -> 'unmapped_requirements', '[]'::jsonb)
) as item
order by ca.created_at desc;

create or replace view monitor_company_tender_documents as
select
    p.user_id,
    u.email,
    coalesce(cp.company_name, u.company_name) as company_name,
    p.id as proposal_id,
    p.tender_id,
    t.external_id,
    t.title as tender_title,
    td.id as document_id,
    td.file_type,
    td.file_size,
    td.storage_path,
    td.file_url,
    case
        when td.parsed_text is null or length(trim(td.parsed_text)) = 0 then false
        else true
    end as has_parsed_text,
    length(coalesce(td.parsed_text, '')) as parsed_text_chars,
    td.created_at as document_created_at
from proposals p
join users u on u.id = p.user_id
join tenders t on t.id = p.tender_id
left join company_profiles cp on cp.user_id = u.id
join tender_documents td on td.tender_id = p.tender_id
order by p.created_at desc, td.created_at asc;

create or replace view monitor_company_tender_compliance_requirements as
select
    p.user_id,
    u.email,
    coalesce(cp.company_name, u.company_name) as company_name,
    p.id as proposal_id,
    p.tender_id,
    t.external_id,
    t.title as tender_title,
    tr.id as tender_requirement_id,
    tn.id as taxonomy_node_id,
    tn.category,
    tn.name as requirement_name,
    tn.description,
    tn.impact_weight,
    tn.is_fatal,
    tr.is_mandatory,
    cc.id is not null as company_has_credential,
    cc.value as company_credential_value,
    cc.expiration_date as company_credential_expiration
from proposals p
join users u on u.id = p.user_id
join tenders t on t.id = p.tender_id
left join company_profiles cp on cp.user_id = u.id
join tender_requirements tr on tr.tender_id = p.tender_id
join taxonomy_nodes tn on tn.id = tr.taxonomy_node_id
left join company_credentials cc
    on cc.company_profile_id = cp.id
   and cc.taxonomy_node_id = tr.taxonomy_node_id
order by p.created_at desc, tn.is_fatal desc, tn.impact_weight desc, tn.name asc;

create or replace view monitor_company_tender_overrides as
select
    rol.id,
    rol.user_id,
    u.email,
    coalesce(cp.company_name, u.company_name) as company_name,
    rol.tender_id,
    t.external_id,
    t.title as tender_title,
    rol.analysis_id,
    rol.missing_node_id,
    tn.category,
    tn.name as missing_requirement,
    tn.is_fatal,
    tn.impact_weight,
    rol.justification,
    rol.state_hash,
    rol.created_at
from risk_override_logs rol
join users u on u.id = rol.user_id
join tenders t on t.id = rol.tender_id
join taxonomy_nodes tn on tn.id = rol.missing_node_id
left join company_profiles cp on cp.user_id = u.id
order by rol.created_at desc;

create or replace view monitor_company_tender_audit_trail as
with normalized_analyses as (
    select
        ta.*,
        case
            when ta.company_name ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:'
            then split_part(ta.company_name, ':', 1)::uuid
            else null
        end as owner_user_id
    from tender_analyses ta
)
select
    ta.tender_id,
    t.external_id,
    t.title as tender_title,
    ta.id as analysis_id,
    ta.company_name as analysis_owner_key,
    ta.owner_user_id as user_id,
    u.email,
    coalesce(cp.company_name, u.company_name) as company_name,
    al.id as audit_log_id,
    al.action_type,
    al.risk_type,
    al.previous_hash,
    al.current_hash,
    al.timestamp
from normalized_analyses ta
join tenders t on t.id = ta.tender_id
left join users u on u.id = ta.owner_user_id
left join company_profiles cp on cp.user_id = u.id
join audit_logs al on al.analysis_id = ta.id
order by al.timestamp desc;

create or replace view monitor_user_activity_timeline as
select
    u.id as user_id,
    u.email,
    coalesce(cp.company_name, u.company_name) as company_name,
    'USER_SIGNED_UP' as action_type,
    u.created_at as action_at,
    null::uuid as tender_id,
    null::text as external_id,
    null::text as tender_title,
    null::uuid as proposal_id,
    null::uuid as analysis_id,
    jsonb_build_object(
        'name', u.name,
        'subscription_tier', u.subscription_tier,
        'is_admin', u.is_admin
    ) as details,
    null::text as cryptographic_hash,
    null::text as previous_hash,
    false as is_hash_chained
from users u
left join company_profiles cp on cp.user_id = u.id

union all

select
    u.id as user_id,
    u.email,
    coalesce(cp.company_name, u.company_name) as company_name,
    'PROPOSAL_CREATED' as action_type,
    p.created_at as action_at,
    p.tender_id,
    t.external_id,
    t.title as tender_title,
    p.id as proposal_id,
    null::uuid as analysis_id,
    jsonb_build_object(
        'proposal_status', p.status,
        'ai_confidence_score', p.ai_confidence_score,
        'final_pdf_url', p.final_pdf_url
    ) as details,
    null::text as cryptographic_hash,
    null::text as previous_hash,
    false as is_hash_chained
from proposals p
join users u on u.id = p.user_id
join tenders t on t.id = p.tender_id
left join company_profiles cp on cp.user_id = u.id

union all

select
    u.id as user_id,
    u.email,
    coalesce(cp.company_name, u.company_name) as company_name,
    'TZ_UPLOADED' as action_type,
    p.created_at as action_at,
    p.tender_id,
    t.external_id,
    t.title as tender_title,
    p.id as proposal_id,
    null::uuid as analysis_id,
    jsonb_build_object(
        'uploaded_tz_path', p.structured_data ->> 'uploaded_tz_path',
        'extracted_text_chars', length(coalesce(p.structured_data ->> 'uploaded_tz_text', ''))
    ) as details,
    null::text as cryptographic_hash,
    null::text as previous_hash,
    false as is_hash_chained
from proposals p
join users u on u.id = p.user_id
join tenders t on t.id = p.tender_id
left join company_profiles cp on cp.user_id = u.id
where p.structured_data::jsonb ? 'uploaded_tz_path'

union all

select
    ca.user_id,
    ca.email,
    ca.company_name,
    'COMPLIANCE_ANALYZED' as action_type,
    ca.created_at as action_at,
    ca.tender_id,
    ca.external_id,
    ca.tender_title,
    p.id as proposal_id,
    ca.analysis_id,
    jsonb_build_object(
        'is_compliant', ca.is_compliant,
        'status_message', ca.compliance_status_message,
        'met_requirement_count', ca.met_requirement_count,
        'missing_requirement_count', ca.missing_requirement_count,
        'unmapped_requirement_count', ca.unmapped_requirement_count,
        'override_seal', ca.override_seal
    ) as details,
    ca.content_hash as cryptographic_hash,
    null::text as previous_hash,
    false as is_hash_chained
from monitor_compliance_analyses ca
left join proposals p
    on p.user_id = ca.user_id
   and p.tender_id = ca.tender_id

union all

select
    rol.user_id,
    u.email,
    coalesce(cp.company_name, u.company_name) as company_name,
    'RISK_OVERRIDE_ACCEPTED' as action_type,
    rol.created_at as action_at,
    rol.tender_id,
    t.external_id,
    t.title as tender_title,
    p.id as proposal_id,
    rol.analysis_id,
    jsonb_build_object(
        'missing_node_id', rol.missing_node_id,
        'missing_requirement', tn.name,
        'justification', rol.justification
    ) as details,
    rol.state_hash as cryptographic_hash,
    null::text as previous_hash,
    false as is_hash_chained
from risk_override_logs rol
join users u on u.id = rol.user_id
join tenders t on t.id = rol.tender_id
join taxonomy_nodes tn on tn.id = rol.missing_node_id
left join company_profiles cp on cp.user_id = u.id
left join proposals p
    on p.user_id = rol.user_id
   and p.tender_id = rol.tender_id

union all

select
    case
        when al.user_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        then al.user_id::uuid
        else null
    end as user_id,
    u.email,
    coalesce(cp.company_name, u.company_name) as company_name,
    al.action_type,
    al.timestamp as action_at,
    ta.tender_id,
    t.external_id,
    t.title as tender_title,
    p.id as proposal_id,
    al.analysis_id,
    jsonb_build_object(
        'risk_type', al.risk_type,
        'audit_log_id', al.id
    ) as details,
    al.current_hash as cryptographic_hash,
    al.previous_hash,
    true as is_hash_chained
from audit_logs al
join tender_analyses ta on ta.id = al.analysis_id
join tenders t on t.id = ta.tender_id
left join users u
    on u.id = case
        when al.user_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        then al.user_id::uuid
        else null
    end
left join company_profiles cp on cp.user_id = u.id
left join proposals p
    on p.user_id = u.id
   and p.tender_id = ta.tender_id
where al.user_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
order by action_at desc;

create or replace view monitor_activity_summary as
select 'users' as metric, count(*)::bigint as value from users
union all
select 'tenders', count(*)::bigint from tenders
union all
select 'tender_documents', count(*)::bigint from tender_documents
union all
select 'parsed_tender_documents', count(*)::bigint
from tender_documents
where parsed_text is not null and length(trim(parsed_text)) > 0
union all
select 'proposals', count(*)::bigint from proposals
union all
select 'user_uploaded_tz', count(*)::bigint
from proposals
where structured_data::jsonb ? 'uploaded_tz_path'
union all
select 'tender_analyses', count(*)::bigint from tender_analyses
union all
select 'audit_logs', count(*)::bigint from audit_logs;
