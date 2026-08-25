-- PlasmaOS immutable PostgreSQL schema baseline.
-- Physical schema cutoff: Alembic revision 20260824_0002_s0_4c.
-- Structure only: no application rows, ownership, ACLs, credentials, or paths.
-- Generated from the forensically verified PostgreSQL 16.12 local 0.4c schema;
-- normalized with pg_dump 16.15. Apply only through bootstrap_database.py.

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--


--
-- Name: proposal_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.proposal_status AS ENUM (
    'DRAFT',
    'GENERATING',
    'COMPLETED',
    'SUBMITTED'
);


--
-- Name: subscription_tier; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.subscription_tier AS ENUM (
    'SCOUT',
    'AGENT',
    'ENTERPRISE'
);


--
-- Name: taxonomy_category; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.taxonomy_category AS ENUM (
    'LICENSE',
    'CERTIFICATION',
    'FINANCIAL',
    'ESG',
    'TECHNICAL',
    'PERSONNEL'
);


--
-- Name: tender_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.tender_status AS ENUM (
    'OPEN',
    'CLOSED',
    'CANCELLED',
    'UNKNOWN'
);


--
-- Name: tender_sync_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.tender_sync_status AS ENUM (
    'PENDING',
    'IN_PROGRESS',
    'SUCCESS',
    'FAILED'
);


--
-- Name: admin_activity_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.admin_activity_events (
    id uuid NOT NULL,
    action character varying(100) NOT NULL,
    actor_user_id uuid,
    actor_label character varying(255),
    target_user_id uuid,
    target_email character varying(255) NOT NULL,
    reason text,
    metadata_json jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(128) NOT NULL
);


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id uuid NOT NULL,
    analysis_id uuid NOT NULL,
    user_id character varying(255) NOT NULL,
    action_type character varying(100) NOT NULL,
    risk_type character varying(255) NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    previous_hash character varying(64),
    current_hash character varying(64) NOT NULL
);


--
-- Name: certifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.certifications (
    id uuid NOT NULL,
    company_id uuid NOT NULL,
    cert_type character varying(100) NOT NULL,
    issue_date date NOT NULL,
    expiry_date date NOT NULL
);


--
-- Name: company_credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_credentials (
    id uuid NOT NULL,
    company_profile_id uuid NOT NULL,
    taxonomy_node_id uuid NOT NULL,
    value character varying(255),
    expiration_date date
);


--
-- Name: company_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_profiles (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    company_name character varying(255),
    director_name character varying(255),
    address text,
    phone_contact character varying(50),
    bank_name character varying(255),
    mfo character varying(10),
    account_number character varying(30),
    inn character varying(15),
    industry character varying(255),
    website character varying(500),
    target_regions json,
    target_countries json,
    target_services json,
    pilot_status character varying(30) DEFAULT 'scoped_pilot'::character varying NOT NULL,
    approval_status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    created_by_user_id uuid,
    approved_at timestamp with time zone,
    approved_by_user_id uuid,
    rejected_at timestamp with time zone,
    rejection_reason text,
    notes text,
    CONSTRAINT ck_company_profiles_approval_status_allowed CHECK (((approval_status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'disabled'::character varying])::text[]))),
    CONSTRAINT ck_company_profiles_pilot_status_allowed CHECK (((pilot_status)::text = ANY ((ARRAY['lead'::character varying, 'scoped_pilot'::character varying, 'active_pilot'::character varying, 'at_risk'::character varying, 'converted'::character varying, 'paused'::character varying])::text[])))
);


--
-- Name: financial_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.financial_history (
    id uuid NOT NULL,
    company_id uuid NOT NULL,
    year integer NOT NULL,
    turnover_uzs bigint NOT NULL
);


--
-- Name: licenses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.licenses (
    id uuid NOT NULL,
    company_id uuid NOT NULL,
    license_name character varying(255) NOT NULL,
    is_active boolean NOT NULL
);


--
-- Name: proposals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.proposals (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    tender_id uuid NOT NULL,
    status public.proposal_status NOT NULL,
    ai_confidence_score integer NOT NULL,
    structured_data json,
    final_pdf_url character varying(500),
    margin_percent double precision NOT NULL,
    include_vat boolean NOT NULL,
    currency character varying(10) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tender_analyses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tender_analyses (
    id uuid NOT NULL,
    tender_id uuid NOT NULL,
    tender_file_name character varying(512) NOT NULL,
    company_name character varying(255) NOT NULL,
    raw_extracted_text text NOT NULL,
    analysis_json jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    content_hash character varying(64),
    override_seal character varying(64)
);


--
-- Name: COLUMN tender_analyses.override_seal; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tender_analyses.override_seal IS 'SHA-256 seal incorporating override state. Null when no overrides have been applied.';


--
-- Name: tender_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tender_documents (
    id uuid NOT NULL,
    tender_id uuid NOT NULL,
    file_url character varying(500) NOT NULL,
    file_type character varying(50) NOT NULL,
    parsed_text text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    storage_path character varying(1000),
    file_size integer,
    source_document_url character varying(1000),
    source_document_type character varying(100),
    download_status character varying(50),
    download_error text,
    external_file_id character varying(200),
    mime_type character varying(150),
    sha256 character varying(64)
);


--
-- Name: tenders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenders (
    id uuid NOT NULL,
    external_id character varying(100) NOT NULL,
    source_url character varying(500) NOT NULL,
    title character varying(500) NOT NULL,
    description text,
    compiled_master_text text,
    budget double precision NOT NULL,
    currency character varying(10) NOT NULL,
    deadline timestamp with time zone,
    region character varying(100),
    status public.tender_status NOT NULL,
    category character varying(50) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    source_system character varying(50) DEFAULT 'uzex'::character varying NOT NULL,
    canonical_source_key character varying(200) NOT NULL,
    country character varying(100),
    sector character varying(500),
    buyer character varying(300),
    procurement_category character varying(100),
    procurement_method character varying(150),
    notice_type character varying(150),
    project_id character varying(100),
    publication_date timestamp with time zone,
    source_metadata_json json,
    scrape_status character varying(50),
    last_synced_at timestamp with time zone,
    CONSTRAINT ck_tenders_source_system_allowed CHECK (((source_system)::text = ANY ((ARRAY['uzex'::character varying, 'world_bank'::character varying, 'adb'::character varying, 'giz'::character varying, 'ebrd'::character varying])::text[])))
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid NOT NULL,
    company_name character varying(255),
    director_name character varying(255),
    address character varying(500),
    phone_contact character varying(50),
    bank_name character varying(255),
    mfo character varying(10),
    account_number character varying(30),
    inn character varying(15),
    subscription_tier public.subscription_tier NOT NULL,
    is_admin boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    google_id character varying(255) NOT NULL,
    email character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    avatar_url character varying(500),
    approval_status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    platform_role character varying(30) DEFAULT 'pilot_user'::character varying NOT NULL,
    approved_at timestamp with time zone,
    approved_by_user_id uuid,
    rejected_at timestamp with time zone,
    rejection_reason text,
    disabled_at timestamp with time zone,
    auth_version integer DEFAULT 0 NOT NULL,
    CONSTRAINT ck_users_approval_status_allowed CHECK (((approval_status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'disabled'::character varying])::text[]))),
    CONSTRAINT ck_users_platform_role_allowed CHECK (((platform_role)::text = ANY ((ARRAY['admin'::character varying, 'operator'::character varying, 'pilot_user'::character varying])::text[])))
);


--
-- Name: monitor_activity_summary; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_activity_summary AS
 SELECT 'users'::text AS metric,
    count(*) AS value
   FROM public.users
UNION ALL
 SELECT 'tenders'::text AS metric,
    count(*) AS value
   FROM public.tenders
UNION ALL
 SELECT 'tender_documents'::text AS metric,
    count(*) AS value
   FROM public.tender_documents
UNION ALL
 SELECT 'parsed_tender_documents'::text AS metric,
    count(*) AS value
   FROM public.tender_documents
  WHERE ((tender_documents.parsed_text IS NOT NULL) AND (length(TRIM(BOTH FROM tender_documents.parsed_text)) > 0))
UNION ALL
 SELECT 'proposals'::text AS metric,
    count(*) AS value
   FROM public.proposals
UNION ALL
 SELECT 'user_uploaded_tz'::text AS metric,
    count(*) AS value
   FROM public.proposals
  WHERE ((proposals.structured_data)::jsonb ? 'uploaded_tz_path'::text)
UNION ALL
 SELECT 'tender_analyses'::text AS metric,
    count(*) AS value
   FROM public.tender_analyses
UNION ALL
 SELECT 'audit_logs'::text AS metric,
    count(*) AS value
   FROM public.audit_logs;


--
-- Name: monitor_company_tender_audit_trail; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_company_tender_audit_trail AS
 WITH normalized_analyses AS (
         SELECT ta_1.id,
            ta_1.tender_id,
            ta_1.tender_file_name,
            ta_1.company_name,
            ta_1.raw_extracted_text,
            ta_1.analysis_json,
            ta_1.created_at,
            ta_1.content_hash,
            ta_1.override_seal,
                CASE
                    WHEN ((ta_1.company_name)::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:'::text) THEN (split_part((ta_1.company_name)::text, ':'::text, 1))::uuid
                    ELSE NULL::uuid
                END AS owner_user_id
           FROM public.tender_analyses ta_1
        )
 SELECT ta.tender_id,
    t.external_id,
    t.title AS tender_title,
    ta.id AS analysis_id,
    ta.company_name AS analysis_owner_key,
    ta.owner_user_id AS user_id,
    u.email,
    COALESCE(cp.company_name, u.company_name) AS company_name,
    al.id AS audit_log_id,
    al.action_type,
    al.risk_type,
    al.previous_hash,
    al.current_hash,
    al."timestamp"
   FROM ((((normalized_analyses ta
     JOIN public.tenders t ON ((t.id = ta.tender_id)))
     LEFT JOIN public.users u ON ((u.id = ta.owner_user_id)))
     LEFT JOIN public.company_profiles cp ON ((cp.user_id = u.id)))
     JOIN public.audit_logs al ON ((al.analysis_id = ta.id)))
  ORDER BY al."timestamp" DESC;


--
-- Name: taxonomy_nodes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.taxonomy_nodes (
    id uuid NOT NULL,
    category public.taxonomy_category NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    impact_weight integer NOT NULL,
    is_fatal boolean NOT NULL,
    CONSTRAINT ck_taxonomy_nodes_impact_weight_range CHECK (((impact_weight >= 0) AND (impact_weight <= 100)))
);


--
-- Name: tender_requirements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tender_requirements (
    id uuid NOT NULL,
    tender_id uuid NOT NULL,
    taxonomy_node_id uuid NOT NULL,
    is_mandatory boolean NOT NULL
);


--
-- Name: monitor_company_tender_compliance_requirements; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_company_tender_compliance_requirements AS
 SELECT p.user_id,
    u.email,
    COALESCE(cp.company_name, u.company_name) AS company_name,
    p.id AS proposal_id,
    p.tender_id,
    t.external_id,
    t.title AS tender_title,
    tr.id AS tender_requirement_id,
    tn.id AS taxonomy_node_id,
    tn.category,
    tn.name AS requirement_name,
    tn.description,
    tn.impact_weight,
    tn.is_fatal,
    tr.is_mandatory,
    (cc.id IS NOT NULL) AS company_has_credential,
    cc.value AS company_credential_value,
    cc.expiration_date AS company_credential_expiration
   FROM ((((((public.proposals p
     JOIN public.users u ON ((u.id = p.user_id)))
     JOIN public.tenders t ON ((t.id = p.tender_id)))
     LEFT JOIN public.company_profiles cp ON ((cp.user_id = u.id)))
     JOIN public.tender_requirements tr ON ((tr.tender_id = p.tender_id)))
     JOIN public.taxonomy_nodes tn ON ((tn.id = tr.taxonomy_node_id)))
     LEFT JOIN public.company_credentials cc ON (((cc.company_profile_id = cp.id) AND (cc.taxonomy_node_id = tr.taxonomy_node_id))))
  ORDER BY p.created_at DESC, tn.is_fatal DESC, tn.impact_weight DESC, tn.name;


--
-- Name: monitor_company_tender_documents; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_company_tender_documents AS
 SELECT p.user_id,
    u.email,
    COALESCE(cp.company_name, u.company_name) AS company_name,
    p.id AS proposal_id,
    p.tender_id,
    t.external_id,
    t.title AS tender_title,
    td.id AS document_id,
    td.file_type,
    td.file_size,
    td.storage_path,
    td.file_url,
        CASE
            WHEN ((td.parsed_text IS NULL) OR (length(TRIM(BOTH FROM td.parsed_text)) = 0)) THEN false
            ELSE true
        END AS has_parsed_text,
    length(COALESCE(td.parsed_text, ''::text)) AS parsed_text_chars,
    td.created_at AS document_created_at
   FROM ((((public.proposals p
     JOIN public.users u ON ((u.id = p.user_id)))
     JOIN public.tenders t ON ((t.id = p.tender_id)))
     LEFT JOIN public.company_profiles cp ON ((cp.user_id = u.id)))
     JOIN public.tender_documents td ON ((td.tender_id = p.tender_id)))
  ORDER BY p.created_at DESC, td.created_at;


--
-- Name: risk_override_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_override_logs (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    tender_id uuid NOT NULL,
    missing_node_id uuid NOT NULL,
    justification text,
    state_hash character varying(128) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    analysis_id uuid
);


--
-- Name: tender_recommendations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tender_recommendations (
    id uuid NOT NULL,
    tender_id uuid NOT NULL,
    company_profile_id uuid NOT NULL,
    match_score integer NOT NULL,
    strategic_rationale text NOT NULL,
    is_dismissed boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_tender_recommendations_match_score_range CHECK (((match_score >= 0) AND (match_score <= 100)))
);


--
-- Name: monitor_company_tender_dossier; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_company_tender_dossier AS
 SELECT u.id AS user_id,
    u.email,
    u.name AS user_name,
    COALESCE(cp.company_name, u.company_name) AS company_name,
    cp.id AS company_profile_id,
    t.id AS tender_id,
    t.external_id,
    t.title AS tender_title,
    t.budget,
    t.currency,
    t.deadline,
    t.region,
    t.status AS tender_status,
    p.id AS proposal_id,
    p.status AS proposal_status,
    p.ai_confidence_score,
    p.final_pdf_url,
    (p.structured_data ->> 'strategic_summary'::text) AS strategic_summary,
    (p.structured_data ->> 'uploaded_tz_path'::text) AS uploaded_tz_path,
    (p.structured_data ->> 'our_price'::text) AS proposed_price,
    (p.structured_data ->> 'delivery_days'::text) AS delivery_days,
    latest_analysis.id AS latest_analysis_id,
    latest_analysis.created_at AS latest_analysis_at,
    latest_analysis.content_hash,
    latest_analysis.override_seal,
    (latest_analysis.analysis_json -> 'evaluation'::text) AS compliance_evaluation,
    (latest_analysis.analysis_json -> 'strategy_intelligence'::text) AS strategy_intelligence,
    COALESCE(doc_stats.document_count, (0)::bigint) AS document_count,
    COALESCE(doc_stats.parsed_document_count, (0)::bigint) AS parsed_document_count,
    COALESCE(doc_stats.total_file_size, (0)::bigint) AS total_document_bytes,
    COALESCE(override_stats.override_count, (0)::bigint) AS override_count,
    rec.match_score AS recommendation_match_score,
    rec.strategic_rationale AS recommendation_rationale,
    rec.is_dismissed AS recommendation_dismissed,
    p.created_at AS proposal_created_at
   FROM (((((((public.proposals p
     JOIN public.users u ON ((u.id = p.user_id)))
     JOIN public.tenders t ON ((t.id = p.tender_id)))
     LEFT JOIN public.company_profiles cp ON ((cp.user_id = u.id)))
     LEFT JOIN LATERAL ( SELECT ta.id,
            ta.tender_id,
            ta.tender_file_name,
            ta.company_name,
            ta.raw_extracted_text,
            ta.analysis_json,
            ta.created_at,
            ta.content_hash,
            ta.override_seal
           FROM public.tender_analyses ta
          WHERE ((ta.tender_id = p.tender_id) AND ((ta.company_name)::text = (((u.id)::text || ':'::text) || COALESCE((cp.id)::text, 'no-profile'::text))))
          ORDER BY ta.created_at DESC
         LIMIT 1) latest_analysis ON (true))
     LEFT JOIN LATERAL ( SELECT count(*) AS document_count,
            count(*) FILTER (WHERE ((td.parsed_text IS NOT NULL) AND (length(TRIM(BOTH FROM td.parsed_text)) > 0))) AS parsed_document_count,
            COALESCE(sum(td.file_size), (0)::bigint) AS total_file_size
           FROM public.tender_documents td
          WHERE (td.tender_id = p.tender_id)) doc_stats ON (true))
     LEFT JOIN LATERAL ( SELECT count(*) AS override_count
           FROM public.risk_override_logs rol
          WHERE ((rol.user_id = p.user_id) AND (rol.tender_id = p.tender_id))) override_stats ON (true))
     LEFT JOIN public.tender_recommendations rec ON (((rec.tender_id = p.tender_id) AND (rec.company_profile_id = cp.id))))
  ORDER BY p.created_at DESC;


--
-- Name: monitor_company_tender_overrides; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_company_tender_overrides AS
 SELECT rol.id,
    rol.user_id,
    u.email,
    COALESCE(cp.company_name, u.company_name) AS company_name,
    rol.tender_id,
    t.external_id,
    t.title AS tender_title,
    rol.analysis_id,
    rol.missing_node_id,
    tn.category,
    tn.name AS missing_requirement,
    tn.is_fatal,
    tn.impact_weight,
    rol.justification,
    rol.state_hash,
    rol.created_at
   FROM ((((public.risk_override_logs rol
     JOIN public.users u ON ((u.id = rol.user_id)))
     JOIN public.tenders t ON ((t.id = rol.tender_id)))
     JOIN public.taxonomy_nodes tn ON ((tn.id = rol.missing_node_id)))
     LEFT JOIN public.company_profiles cp ON ((cp.user_id = u.id)))
  ORDER BY rol.created_at DESC;


--
-- Name: monitor_compliance_analyses; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_compliance_analyses AS
 WITH normalized_analyses AS (
         SELECT ta_1.id,
            ta_1.tender_id,
            ta_1.tender_file_name,
            ta_1.company_name,
            ta_1.raw_extracted_text,
            ta_1.analysis_json,
            ta_1.created_at,
            ta_1.content_hash,
            ta_1.override_seal,
                CASE
                    WHEN ((ta_1.company_name)::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:'::text) THEN (split_part((ta_1.company_name)::text, ':'::text, 1))::uuid
                    ELSE NULL::uuid
                END AS owner_user_id,
                CASE
                    WHEN (split_part((ta_1.company_name)::text, ':'::text, 2) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'::text) THEN (NULLIF(split_part((ta_1.company_name)::text, ':'::text, 2), ''::text))::uuid
                    ELSE NULL::uuid
                END AS owner_company_profile_id
           FROM public.tender_analyses ta_1
        )
 SELECT ta.id AS analysis_id,
    ta.tender_id,
    t.external_id,
    t.title AS tender_title,
    ta.owner_user_id AS user_id,
    u.email,
    u.name AS user_name,
    COALESCE(cp.company_name, u.company_name, ((ta.analysis_json ->> 'tenant_company_name'::text))::character varying) AS company_name,
    ta.owner_company_profile_id AS company_profile_id,
    ((ta.analysis_json #>> '{evaluation,is_compliant}'::text[]))::boolean AS is_compliant,
    (ta.analysis_json #>> '{evaluation,status_message}'::text[]) AS compliance_status_message,
    jsonb_array_length(COALESCE((ta.analysis_json #> '{evaluation,met_requirements}'::text[]), '[]'::jsonb)) AS met_requirement_count,
    jsonb_array_length(COALESCE((ta.analysis_json #> '{evaluation,missing_requirements}'::text[]), '[]'::jsonb)) AS missing_requirement_count,
    jsonb_array_length(COALESCE((ta.analysis_json #> '{evaluation,unmapped_requirements}'::text[]), '[]'::jsonb)) AS unmapped_requirement_count,
    (ta.analysis_json -> 'evaluation'::text) AS compliance_evaluation,
    (ta.analysis_json -> 'hybrid_compliance'::text) AS hybrid_compliance,
    (ta.analysis_json -> 'strategy_intelligence'::text) AS strategy_intelligence,
    ta.content_hash,
    ta.override_seal,
    ta.created_at
   FROM (((normalized_analyses ta
     JOIN public.tenders t ON ((t.id = ta.tender_id)))
     LEFT JOIN public.users u ON ((u.id = ta.owner_user_id)))
     LEFT JOIN public.company_profiles cp ON ((cp.id = ta.owner_company_profile_id)))
  ORDER BY ta.created_at DESC;


--
-- Name: monitor_compliance_met_requirements; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_compliance_met_requirements AS
 SELECT ca.analysis_id,
    ca.tender_id,
    ca.external_id,
    ca.tender_title,
    ca.user_id,
    ca.email,
    ca.company_name,
    (item.value ->> 'uuid'::text) AS taxonomy_node_id,
    (item.value ->> 'name'::text) AS requirement_name,
    ca.created_at AS analysis_created_at
   FROM (public.monitor_compliance_analyses ca
     CROSS JOIN LATERAL jsonb_array_elements(COALESCE((ca.compliance_evaluation -> 'met_requirements'::text), '[]'::jsonb)) item(value))
  ORDER BY ca.created_at DESC, (item.value ->> 'name'::text);


--
-- Name: monitor_compliance_missing_requirements; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_compliance_missing_requirements AS
 SELECT ca.analysis_id,
    ca.tender_id,
    ca.external_id,
    ca.tender_title,
    ca.user_id,
    ca.email,
    ca.company_name,
    (item.value ->> 'uuid'::text) AS taxonomy_node_id,
    (item.value ->> 'name'::text) AS requirement_name,
    (NULLIF((item.value ->> 'impact_weight'::text), ''::text))::integer AS impact_weight,
    (NULLIF((item.value ->> 'is_fatal'::text), ''::text))::boolean AS is_fatal,
    ca.created_at AS analysis_created_at
   FROM (public.monitor_compliance_analyses ca
     CROSS JOIN LATERAL jsonb_array_elements(COALESCE((ca.compliance_evaluation -> 'missing_requirements'::text), '[]'::jsonb)) item(value))
  ORDER BY ca.created_at DESC, (NULLIF((item.value ->> 'is_fatal'::text), ''::text))::boolean DESC, (NULLIF((item.value ->> 'impact_weight'::text), ''::text))::integer DESC;


--
-- Name: monitor_compliance_unmapped_requirements; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_compliance_unmapped_requirements AS
 SELECT ca.analysis_id,
    ca.tender_id,
    ca.external_id,
    ca.tender_title,
    ca.user_id,
    ca.email,
    ca.company_name,
    (item.value #>> '{}'::text[]) AS requirement_text,
    ca.created_at AS analysis_created_at
   FROM (public.monitor_compliance_analyses ca
     CROSS JOIN LATERAL jsonb_array_elements(COALESCE((ca.compliance_evaluation -> 'unmapped_requirements'::text), '[]'::jsonb)) item(value))
  ORDER BY ca.created_at DESC;


--
-- Name: monitor_proposals; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_proposals AS
 SELECT p.id,
    p.user_id,
    u.email,
    u.name,
    p.tender_id,
    t.external_id,
    t.title AS tender_title,
    p.status,
    p.ai_confidence_score,
    p.final_pdf_url,
    p.created_at
   FROM ((public.proposals p
     JOIN public.users u ON ((u.id = p.user_id)))
     JOIN public.tenders t ON ((t.id = p.tender_id)))
  ORDER BY p.created_at DESC;


--
-- Name: monitor_tender_documents; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_tender_documents AS
 SELECT td.id,
    td.tender_id,
    t.external_id,
    t.title AS tender_title,
    td.file_type,
    td.file_size,
    td.storage_path,
    td.file_url,
        CASE
            WHEN ((td.parsed_text IS NULL) OR (length(TRIM(BOTH FROM td.parsed_text)) = 0)) THEN false
            ELSE true
        END AS has_parsed_text,
    length(COALESCE(td.parsed_text, ''::text)) AS parsed_text_chars,
    td.created_at
   FROM (public.tender_documents td
     JOIN public.tenders t ON ((t.id = td.tender_id)))
  ORDER BY td.created_at DESC;


--
-- Name: tender_sync_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tender_sync_jobs (
    id uuid NOT NULL,
    job_id character varying(100) NOT NULL,
    tender_id uuid NOT NULL,
    user_id uuid NOT NULL,
    status public.tender_sync_status NOT NULL,
    progress integer DEFAULT 0 NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_tender_sync_jobs_progress_range CHECK (((progress >= 0) AND (progress <= 100)))
);


--
-- Name: monitor_tender_sync_jobs; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_tender_sync_jobs AS
 SELECT tsj.id,
    tsj.job_id,
    tsj.user_id,
    u.email,
    tsj.tender_id,
    t.title AS tender_title,
    tsj.status,
    tsj.progress,
    tsj.error_message,
    tsj.created_at,
    tsj.updated_at
   FROM ((public.tender_sync_jobs tsj
     JOIN public.users u ON ((u.id = tsj.user_id)))
     JOIN public.tenders t ON ((t.id = tsj.tender_id)))
  ORDER BY tsj.updated_at DESC;


--
-- Name: monitor_user_activity_timeline; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_user_activity_timeline AS
 SELECT u.id AS user_id,
    u.email,
    COALESCE(cp.company_name, u.company_name) AS company_name,
    'USER_SIGNED_UP'::text AS action_type,
    u.created_at AS action_at,
    NULL::uuid AS tender_id,
    NULL::text AS external_id,
    NULL::text AS tender_title,
    NULL::uuid AS proposal_id,
    NULL::uuid AS analysis_id,
    jsonb_build_object('name', u.name, 'subscription_tier', u.subscription_tier, 'is_admin', u.is_admin) AS details,
    NULL::text AS cryptographic_hash,
    NULL::text AS previous_hash,
    false AS is_hash_chained
   FROM (public.users u
     LEFT JOIN public.company_profiles cp ON ((cp.user_id = u.id)))
UNION ALL
 SELECT u.id AS user_id,
    u.email,
    COALESCE(cp.company_name, u.company_name) AS company_name,
    'PROPOSAL_CREATED'::text AS action_type,
    p.created_at AS action_at,
    p.tender_id,
    t.external_id,
    t.title AS tender_title,
    p.id AS proposal_id,
    NULL::uuid AS analysis_id,
    jsonb_build_object('proposal_status', p.status, 'ai_confidence_score', p.ai_confidence_score, 'final_pdf_url', p.final_pdf_url) AS details,
    NULL::text AS cryptographic_hash,
    NULL::text AS previous_hash,
    false AS is_hash_chained
   FROM (((public.proposals p
     JOIN public.users u ON ((u.id = p.user_id)))
     JOIN public.tenders t ON ((t.id = p.tender_id)))
     LEFT JOIN public.company_profiles cp ON ((cp.user_id = u.id)))
UNION ALL
 SELECT u.id AS user_id,
    u.email,
    COALESCE(cp.company_name, u.company_name) AS company_name,
    'TZ_UPLOADED'::text AS action_type,
    p.created_at AS action_at,
    p.tender_id,
    t.external_id,
    t.title AS tender_title,
    p.id AS proposal_id,
    NULL::uuid AS analysis_id,
    jsonb_build_object('uploaded_tz_path', (p.structured_data ->> 'uploaded_tz_path'::text), 'extracted_text_chars', length(COALESCE((p.structured_data ->> 'uploaded_tz_text'::text), ''::text))) AS details,
    NULL::text AS cryptographic_hash,
    NULL::text AS previous_hash,
    false AS is_hash_chained
   FROM (((public.proposals p
     JOIN public.users u ON ((u.id = p.user_id)))
     JOIN public.tenders t ON ((t.id = p.tender_id)))
     LEFT JOIN public.company_profiles cp ON ((cp.user_id = u.id)))
  WHERE ((p.structured_data)::jsonb ? 'uploaded_tz_path'::text)
UNION ALL
 SELECT ca.user_id,
    ca.email,
    ca.company_name,
    'COMPLIANCE_ANALYZED'::text AS action_type,
    ca.created_at AS action_at,
    ca.tender_id,
    ca.external_id,
    ca.tender_title,
    p.id AS proposal_id,
    ca.analysis_id,
    jsonb_build_object('is_compliant', ca.is_compliant, 'status_message', ca.compliance_status_message, 'met_requirement_count', ca.met_requirement_count, 'missing_requirement_count', ca.missing_requirement_count, 'unmapped_requirement_count', ca.unmapped_requirement_count, 'override_seal', ca.override_seal) AS details,
    ca.content_hash AS cryptographic_hash,
    NULL::text AS previous_hash,
    false AS is_hash_chained
   FROM (public.monitor_compliance_analyses ca
     LEFT JOIN public.proposals p ON (((p.user_id = ca.user_id) AND (p.tender_id = ca.tender_id))))
UNION ALL
 SELECT rol.user_id,
    u.email,
    COALESCE(cp.company_name, u.company_name) AS company_name,
    'RISK_OVERRIDE_ACCEPTED'::text AS action_type,
    rol.created_at AS action_at,
    rol.tender_id,
    t.external_id,
    t.title AS tender_title,
    p.id AS proposal_id,
    rol.analysis_id,
    jsonb_build_object('missing_node_id', rol.missing_node_id, 'missing_requirement', tn.name, 'justification', rol.justification) AS details,
    rol.state_hash AS cryptographic_hash,
    NULL::text AS previous_hash,
    false AS is_hash_chained
   FROM (((((public.risk_override_logs rol
     JOIN public.users u ON ((u.id = rol.user_id)))
     JOIN public.tenders t ON ((t.id = rol.tender_id)))
     JOIN public.taxonomy_nodes tn ON ((tn.id = rol.missing_node_id)))
     LEFT JOIN public.company_profiles cp ON ((cp.user_id = u.id)))
     LEFT JOIN public.proposals p ON (((p.user_id = rol.user_id) AND (p.tender_id = rol.tender_id))))
UNION ALL
 SELECT
        CASE
            WHEN ((al.user_id)::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'::text) THEN (al.user_id)::uuid
            ELSE NULL::uuid
        END AS user_id,
    u.email,
    COALESCE(cp.company_name, u.company_name) AS company_name,
    al.action_type,
    al."timestamp" AS action_at,
    ta.tender_id,
    t.external_id,
    t.title AS tender_title,
    p.id AS proposal_id,
    al.analysis_id,
    jsonb_build_object('risk_type', al.risk_type, 'audit_log_id', al.id) AS details,
    al.current_hash AS cryptographic_hash,
    al.previous_hash,
    true AS is_hash_chained
   FROM (((((public.audit_logs al
     JOIN public.tender_analyses ta ON ((ta.id = al.analysis_id)))
     JOIN public.tenders t ON ((t.id = ta.tender_id)))
     LEFT JOIN public.users u ON ((u.id =
        CASE
            WHEN ((al.user_id)::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'::text) THEN (al.user_id)::uuid
            ELSE NULL::uuid
        END)))
     LEFT JOIN public.company_profiles cp ON ((cp.user_id = u.id)))
     LEFT JOIN public.proposals p ON (((p.user_id = u.id) AND (p.tender_id = ta.tender_id))))
  WHERE ((al.user_id)::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'::text)
  ORDER BY 5 DESC;


--
-- Name: monitor_user_uploaded_tz; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_user_uploaded_tz AS
 SELECT p.id AS proposal_id,
    p.user_id,
    u.email,
    u.name,
    p.tender_id,
    t.title AS tender_title,
    (p.structured_data ->> 'uploaded_tz_path'::text) AS uploaded_tz_path,
        CASE
            WHEN (COALESCE((p.structured_data ->> 'uploaded_tz_text'::text), ''::text) = ''::text) THEN false
            ELSE true
        END AS has_extracted_text,
    length(COALESCE((p.structured_data ->> 'uploaded_tz_text'::text), ''::text)) AS extracted_text_chars,
    p.created_at
   FROM ((public.proposals p
     JOIN public.users u ON ((u.id = p.user_id)))
     JOIN public.tenders t ON ((t.id = p.tender_id)))
  WHERE ((p.structured_data)::jsonb ? 'uploaded_tz_path'::text)
  ORDER BY p.created_at DESC;


--
-- Name: monitor_users; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.monitor_users AS
SELECT
    NULL::uuid AS id,
    NULL::character varying(255) AS email,
    NULL::character varying(255) AS name,
    NULL::public.subscription_tier AS subscription_tier,
    NULL::boolean AS is_admin,
    NULL::character varying(255) AS company_name,
    NULL::character varying(50) AS phone_contact,
    NULL::timestamp with time zone AS created_at,
    NULL::bigint AS proposal_count,
    NULL::bigint AS analysis_count;


--
-- Name: readiness_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.readiness_documents (
    id uuid NOT NULL,
    company_profile_id uuid NOT NULL,
    document_type character varying(50) NOT NULL,
    document_name character varying(255) NOT NULL,
    document_number character varying(100),
    issuer character varying(255),
    issue_date date,
    expiry_date date,
    status character varying(20) DEFAULT 'unknown'::character varying NOT NULL,
    related_service character varying(100),
    notes text,
    optional_file_url character varying(1000),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ck_readiness_documents_status_allowed CHECK (((status)::text = ANY ((ARRAY['available'::character varying, 'missing'::character varying, 'expired'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT ck_readiness_documents_type_allowed CHECK (((document_type)::text = ANY ((ARRAY['license'::character varying, 'certificate'::character varying, 'tax_clearance'::character varying, 'financial_statement'::character varying, 'registration_document'::character varying, 'power_of_attorney'::character varying, 'personnel_document'::character varying, 'other'::character varying])::text[])))
);


--
-- Name: source_refresh_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_refresh_jobs (
    id uuid NOT NULL,
    source_system character varying(50) NOT NULL,
    requested_by_user_id uuid,
    status character varying(30) NOT NULL,
    force boolean NOT NULL,
    created_count integer NOT NULL,
    updated_count integer NOT NULL,
    failed_count integer NOT NULL,
    message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    fetched_count integer DEFAULT 0 NOT NULL,
    skipped_count integer DEFAULT 0 NOT NULL,
    rejected_count integer DEFAULT 0 NOT NULL,
    fallback_used boolean DEFAULT false NOT NULL,
    skip_reasons json,
    failure_class character varying(100),
    failure_stage character varying(100),
    retryable boolean,
    elapsed_ms integer,
    source_newest_published_at timestamp with time zone,
    source_oldest_published_at timestamp with time zone,
    execution_health character varying(30),
    freshness_health character varying(30),
    coverage_health character varying(30),
    CONSTRAINT ck_source_refresh_jobs_status_allowed CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'completed'::character varying, 'partial'::character varying, 'source_unavailable'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: admin_activity_events admin_activity_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_activity_events
    ADD CONSTRAINT admin_activity_events_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: audit_logs audit_logs_current_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_current_hash_key UNIQUE (current_hash);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: certifications certifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.certifications
    ADD CONSTRAINT certifications_pkey PRIMARY KEY (id);


--
-- Name: company_credentials company_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_credentials
    ADD CONSTRAINT company_credentials_pkey PRIMARY KEY (id);


--
-- Name: company_profiles company_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_profiles
    ADD CONSTRAINT company_profiles_pkey PRIMARY KEY (id);


--
-- Name: company_profiles company_profiles_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_profiles
    ADD CONSTRAINT company_profiles_user_id_key UNIQUE (user_id);


--
-- Name: financial_history financial_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.financial_history
    ADD CONSTRAINT financial_history_pkey PRIMARY KEY (id);


--
-- Name: licenses licenses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.licenses
    ADD CONSTRAINT licenses_pkey PRIMARY KEY (id);


--
-- Name: proposals proposals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT proposals_pkey PRIMARY KEY (id);


--
-- Name: readiness_documents readiness_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.readiness_documents
    ADD CONSTRAINT readiness_documents_pkey PRIMARY KEY (id);


--
-- Name: risk_override_logs risk_override_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_override_logs
    ADD CONSTRAINT risk_override_logs_pkey PRIMARY KEY (id);


--
-- Name: source_refresh_jobs source_refresh_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_refresh_jobs
    ADD CONSTRAINT source_refresh_jobs_pkey PRIMARY KEY (id);


--
-- Name: taxonomy_nodes taxonomy_nodes_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxonomy_nodes
    ADD CONSTRAINT taxonomy_nodes_name_key UNIQUE (name);


--
-- Name: taxonomy_nodes taxonomy_nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxonomy_nodes
    ADD CONSTRAINT taxonomy_nodes_pkey PRIMARY KEY (id);


--
-- Name: tender_analyses tender_analyses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_analyses
    ADD CONSTRAINT tender_analyses_pkey PRIMARY KEY (id);


--
-- Name: tender_documents tender_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_documents
    ADD CONSTRAINT tender_documents_pkey PRIMARY KEY (id);


--
-- Name: tender_recommendations tender_recommendations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_recommendations
    ADD CONSTRAINT tender_recommendations_pkey PRIMARY KEY (id);


--
-- Name: tender_requirements tender_requirements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_requirements
    ADD CONSTRAINT tender_requirements_pkey PRIMARY KEY (id);


--
-- Name: tender_sync_jobs tender_sync_jobs_job_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_sync_jobs
    ADD CONSTRAINT tender_sync_jobs_job_id_key UNIQUE (job_id);


--
-- Name: tender_sync_jobs tender_sync_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_sync_jobs
    ADD CONSTRAINT tender_sync_jobs_pkey PRIMARY KEY (id);


--
-- Name: tenders tenders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenders
    ADD CONSTRAINT tenders_pkey PRIMARY KEY (id);


--
-- Name: company_credentials uq_company_credentials_profile_taxonomy_node; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_credentials
    ADD CONSTRAINT uq_company_credentials_profile_taxonomy_node UNIQUE (company_profile_id, taxonomy_node_id);


--
-- Name: financial_history uq_financial_history_company_year; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.financial_history
    ADD CONSTRAINT uq_financial_history_company_year UNIQUE (company_id, year);


--
-- Name: proposals uq_proposals_user_tender; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT uq_proposals_user_tender UNIQUE (user_id, tender_id);


--
-- Name: tender_recommendations uq_tender_recommendations_tender_profile; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_recommendations
    ADD CONSTRAINT uq_tender_recommendations_tender_profile UNIQUE (tender_id, company_profile_id);


--
-- Name: tender_requirements uq_tender_requirements_tender_taxonomy_node; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_requirements
    ADD CONSTRAINT uq_tender_requirements_tender_taxonomy_node UNIQUE (tender_id, taxonomy_node_id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_google_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_google_id_key UNIQUE (google_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_admin_activity_events_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_admin_activity_events_action ON public.admin_activity_events USING btree (action);


--
-- Name: ix_admin_activity_events_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_admin_activity_events_created_at ON public.admin_activity_events USING btree (created_at);


--
-- Name: ix_admin_activity_events_target_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_admin_activity_events_target_email ON public.admin_activity_events USING btree (target_email);


--
-- Name: ix_admin_activity_events_target_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_admin_activity_events_target_user_id ON public.admin_activity_events USING btree (target_user_id);


--
-- Name: ix_audit_logs_current_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_audit_logs_current_hash ON public.audit_logs USING btree (current_hash);


--
-- Name: ix_audit_logs_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_timestamp ON public.audit_logs USING btree ("timestamp");


--
-- Name: ix_certifications_company_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_certifications_company_id ON public.certifications USING btree (company_id);


--
-- Name: ix_company_credentials_company_profile_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_company_credentials_company_profile_id ON public.company_credentials USING btree (company_profile_id);


--
-- Name: ix_company_credentials_taxonomy_node_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_company_credentials_taxonomy_node_id ON public.company_credentials USING btree (taxonomy_node_id);


--
-- Name: ix_company_profiles_approval_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_company_profiles_approval_status ON public.company_profiles USING btree (approval_status);


--
-- Name: ix_company_profiles_pilot_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_company_profiles_pilot_status ON public.company_profiles USING btree (pilot_status);


--
-- Name: ix_company_profiles_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_company_profiles_user_id ON public.company_profiles USING btree (user_id);


--
-- Name: ix_financial_history_company_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_financial_history_company_id ON public.financial_history USING btree (company_id);


--
-- Name: ix_financial_history_year; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_financial_history_year ON public.financial_history USING btree (year);


--
-- Name: ix_licenses_company_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_licenses_company_id ON public.licenses USING btree (company_id);


--
-- Name: ix_proposals_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposals_status ON public.proposals USING btree (status);


--
-- Name: ix_proposals_tender_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposals_tender_id ON public.proposals USING btree (tender_id);


--
-- Name: ix_proposals_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proposals_user_id ON public.proposals USING btree (user_id);


--
-- Name: ix_readiness_documents_company_profile_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_readiness_documents_company_profile_id ON public.readiness_documents USING btree (company_profile_id);


--
-- Name: ix_readiness_documents_document_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_readiness_documents_document_type ON public.readiness_documents USING btree (document_type);


--
-- Name: ix_readiness_documents_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_readiness_documents_status ON public.readiness_documents USING btree (status);


--
-- Name: ix_risk_override_logs_analysis_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_risk_override_logs_analysis_id ON public.risk_override_logs USING btree (analysis_id);


--
-- Name: ix_risk_override_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_risk_override_logs_created_at ON public.risk_override_logs USING btree (created_at);


--
-- Name: ix_risk_override_logs_missing_node_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_risk_override_logs_missing_node_id ON public.risk_override_logs USING btree (missing_node_id);


--
-- Name: ix_risk_override_logs_tender_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_risk_override_logs_tender_id ON public.risk_override_logs USING btree (tender_id);


--
-- Name: ix_risk_override_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_risk_override_logs_user_id ON public.risk_override_logs USING btree (user_id);


--
-- Name: ix_source_refresh_jobs_source_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_refresh_jobs_source_created ON public.source_refresh_jobs USING btree (source_system, created_at);


--
-- Name: ix_taxonomy_nodes_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_taxonomy_nodes_category ON public.taxonomy_nodes USING btree (category);


--
-- Name: ix_taxonomy_nodes_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_taxonomy_nodes_name ON public.taxonomy_nodes USING btree (name);


--
-- Name: ix_tender_analyses_tender_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tender_analyses_tender_id ON public.tender_analyses USING btree (tender_id);


--
-- Name: ix_tender_documents_tender_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tender_documents_tender_id ON public.tender_documents USING btree (tender_id);


--
-- Name: ix_tender_recommendations_company_profile_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tender_recommendations_company_profile_id ON public.tender_recommendations USING btree (company_profile_id);


--
-- Name: ix_tender_recommendations_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tender_recommendations_created_at ON public.tender_recommendations USING btree (created_at);


--
-- Name: ix_tender_recommendations_tender_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tender_recommendations_tender_id ON public.tender_recommendations USING btree (tender_id);


--
-- Name: ix_tender_requirements_taxonomy_node_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tender_requirements_taxonomy_node_id ON public.tender_requirements USING btree (taxonomy_node_id);


--
-- Name: ix_tender_requirements_tender_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tender_requirements_tender_id ON public.tender_requirements USING btree (tender_id);


--
-- Name: ix_tender_sync_jobs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tender_sync_jobs_status ON public.tender_sync_jobs USING btree (status);


--
-- Name: ix_tender_sync_jobs_tender_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tender_sync_jobs_tender_id ON public.tender_sync_jobs USING btree (tender_id);


--
-- Name: ix_tender_sync_jobs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tender_sync_jobs_user_id ON public.tender_sync_jobs USING btree (user_id);


--
-- Name: ix_tenders_canonical_source_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_tenders_canonical_source_key ON public.tenders USING btree (canonical_source_key);


--
-- Name: ix_tenders_deadline; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tenders_deadline ON public.tenders USING btree (deadline);


--
-- Name: ix_tenders_external_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tenders_external_id ON public.tenders USING btree (external_id);


--
-- Name: ix_tenders_source_system; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tenders_source_system ON public.tenders USING btree (source_system);


--
-- Name: ix_tenders_source_system_external_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_tenders_source_system_external_id ON public.tenders USING btree (source_system, external_id);


--
-- Name: ix_tenders_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tenders_status ON public.tenders USING btree (status);


--
-- Name: ix_users_approval_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_approval_status ON public.users USING btree (approval_status);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_google_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_google_id ON public.users USING btree (google_id);


--
-- Name: ix_users_platform_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_platform_role ON public.users USING btree (platform_role);


--
-- Name: uq_source_refresh_jobs_active_source; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_source_refresh_jobs_active_source ON public.source_refresh_jobs USING btree (source_system) WHERE ((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying])::text[]));


--
-- Name: uq_tender_sync_jobs_active_user_tender; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_tender_sync_jobs_active_user_tender ON public.tender_sync_jobs USING btree (user_id, tender_id) WHERE (status = ANY (ARRAY['PENDING'::public.tender_sync_status, 'IN_PROGRESS'::public.tender_sync_status]));


--
-- Name: monitor_users _RETURN; Type: RULE; Schema: public; Owner: -
--

CREATE OR REPLACE VIEW public.monitor_users AS
 SELECT u.id,
    u.email,
    u.name,
    u.subscription_tier,
    u.is_admin,
    u.company_name,
    u.phone_contact,
    u.created_at,
    count(DISTINCT p.id) AS proposal_count,
    count(DISTINCT ta.id) AS analysis_count
   FROM ((public.users u
     LEFT JOIN public.proposals p ON ((p.user_id = u.id)))
     LEFT JOIN public.tender_analyses ta ON (((ta.company_name)::text ~~ ((u.id)::text || ':%'::text))))
  GROUP BY u.id
  ORDER BY u.created_at DESC;


--
-- Name: audit_logs audit_logs_analysis_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_analysis_id_fkey FOREIGN KEY (analysis_id) REFERENCES public.tender_analyses(id) ON DELETE CASCADE;


--
-- Name: certifications certifications_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.certifications
    ADD CONSTRAINT certifications_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company_profiles(id) ON DELETE CASCADE;


--
-- Name: company_credentials company_credentials_company_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_credentials
    ADD CONSTRAINT company_credentials_company_profile_id_fkey FOREIGN KEY (company_profile_id) REFERENCES public.company_profiles(id) ON DELETE CASCADE;


--
-- Name: company_credentials company_credentials_taxonomy_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_credentials
    ADD CONSTRAINT company_credentials_taxonomy_node_id_fkey FOREIGN KEY (taxonomy_node_id) REFERENCES public.taxonomy_nodes(id) ON DELETE CASCADE;


--
-- Name: company_profiles company_profiles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_profiles
    ADD CONSTRAINT company_profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: financial_history financial_history_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.financial_history
    ADD CONSTRAINT financial_history_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company_profiles(id) ON DELETE CASCADE;


--
-- Name: admin_activity_events fk_admin_activity_events_actor_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_activity_events
    ADD CONSTRAINT fk_admin_activity_events_actor_user_id_users FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: admin_activity_events fk_admin_activity_events_target_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_activity_events
    ADD CONSTRAINT fk_admin_activity_events_target_user_id_users FOREIGN KEY (target_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: company_profiles fk_company_profiles_approved_by_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_profiles
    ADD CONSTRAINT fk_company_profiles_approved_by_user_id_users FOREIGN KEY (approved_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: company_profiles fk_company_profiles_created_by_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_profiles
    ADD CONSTRAINT fk_company_profiles_created_by_user_id_users FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: users fk_users_approved_by_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_users_approved_by_user_id_users FOREIGN KEY (approved_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: licenses licenses_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.licenses
    ADD CONSTRAINT licenses_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company_profiles(id) ON DELETE CASCADE;


--
-- Name: proposals proposals_tender_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT proposals_tender_id_fkey FOREIGN KEY (tender_id) REFERENCES public.tenders(id) ON DELETE CASCADE;


--
-- Name: proposals proposals_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT proposals_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: readiness_documents readiness_documents_company_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.readiness_documents
    ADD CONSTRAINT readiness_documents_company_profile_id_fkey FOREIGN KEY (company_profile_id) REFERENCES public.company_profiles(id) ON DELETE CASCADE;


--
-- Name: risk_override_logs risk_override_logs_analysis_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_override_logs
    ADD CONSTRAINT risk_override_logs_analysis_id_fkey FOREIGN KEY (analysis_id) REFERENCES public.tender_analyses(id) ON DELETE CASCADE;


--
-- Name: risk_override_logs risk_override_logs_missing_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_override_logs
    ADD CONSTRAINT risk_override_logs_missing_node_id_fkey FOREIGN KEY (missing_node_id) REFERENCES public.taxonomy_nodes(id) ON DELETE CASCADE;


--
-- Name: risk_override_logs risk_override_logs_tender_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_override_logs
    ADD CONSTRAINT risk_override_logs_tender_id_fkey FOREIGN KEY (tender_id) REFERENCES public.tenders(id) ON DELETE CASCADE;


--
-- Name: risk_override_logs risk_override_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_override_logs
    ADD CONSTRAINT risk_override_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: source_refresh_jobs source_refresh_jobs_requested_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_refresh_jobs
    ADD CONSTRAINT source_refresh_jobs_requested_by_user_id_fkey FOREIGN KEY (requested_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: tender_analyses tender_analyses_tender_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_analyses
    ADD CONSTRAINT tender_analyses_tender_id_fkey FOREIGN KEY (tender_id) REFERENCES public.tenders(id) ON DELETE CASCADE;


--
-- Name: tender_documents tender_documents_tender_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_documents
    ADD CONSTRAINT tender_documents_tender_id_fkey FOREIGN KEY (tender_id) REFERENCES public.tenders(id) ON DELETE CASCADE;


--
-- Name: tender_recommendations tender_recommendations_company_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_recommendations
    ADD CONSTRAINT tender_recommendations_company_profile_id_fkey FOREIGN KEY (company_profile_id) REFERENCES public.company_profiles(id) ON DELETE CASCADE;


--
-- Name: tender_recommendations tender_recommendations_tender_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_recommendations
    ADD CONSTRAINT tender_recommendations_tender_id_fkey FOREIGN KEY (tender_id) REFERENCES public.tenders(id) ON DELETE CASCADE;


--
-- Name: tender_requirements tender_requirements_taxonomy_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_requirements
    ADD CONSTRAINT tender_requirements_taxonomy_node_id_fkey FOREIGN KEY (taxonomy_node_id) REFERENCES public.taxonomy_nodes(id) ON DELETE CASCADE;


--
-- Name: tender_requirements tender_requirements_tender_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_requirements
    ADD CONSTRAINT tender_requirements_tender_id_fkey FOREIGN KEY (tender_id) REFERENCES public.tenders(id) ON DELETE CASCADE;


--
-- Name: tender_sync_jobs tender_sync_jobs_tender_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_sync_jobs
    ADD CONSTRAINT tender_sync_jobs_tender_id_fkey FOREIGN KEY (tender_id) REFERENCES public.tenders(id) ON DELETE CASCADE;


--
-- Name: tender_sync_jobs tender_sync_jobs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tender_sync_jobs
    ADD CONSTRAINT tender_sync_jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
--
