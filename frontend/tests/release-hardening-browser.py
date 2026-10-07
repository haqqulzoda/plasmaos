#!/usr/bin/env python3
"""Portable production-build Chromium gate: local fixtures and real backend guards.

Requires a build with BACKEND_INTERNAL_URL=http://127.0.0.1:8114/api/v1 and
NEXT_DIST_DIR=.next-release-test. No Windows browser paths or external services.
"""
import asyncio
from collections import Counter
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import traceback
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
from unittest.mock import AsyncMock, patch

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
FRONT = Path(os.environ.get("PLASMA_FRONTEND_TEST_ROOT", str(ROOT / "frontend")))
OUT = Path(os.environ.get("PLASMA_BROWSER_RESULTS", str(ROOT / "docs/audits/s9_3/browser")))
BROWSER_PORT = int(os.environ.get("PLASMA_RELEASE_BROWSER_PORT", "3114"))
BROWSER_HOST = os.environ.get("PLASMA_RELEASE_BROWSER_HOST", "localhost")
BASE = f"http://{BROWSER_HOST}:{BROWSER_PORT}"
CONNECT_HOST = os.environ.get("PLASMA_RELEASE_BROWSER_CONNECT_HOST", BROWSER_HOST)
PROBE_BASE = f"http://{CONNECT_HOST}:{BROWSER_PORT}"
BACKEND_BIND_HOST = os.environ.get("PLASMA_BROWSER_BACKEND_BIND", "127.0.0.1")
NPM = os.environ.get("NPM_BIN") or ("npm.cmd" if os.name == "nt" else "npm")
NODE = os.environ.get("NODE_BIN") or ("node" if shutil.which("node") else "node.exe")
AXE_SCRIPT = FRONT / "node_modules" / "axe-core" / "axe.min.js"


def load_fixture():
    spec = importlib.util.spec_from_file_location("release_ui_fixture", Path(__file__).with_name("s8-3-arabic-rtl-browser-acceptance.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fixture = load_fixture()
    s72 = fixture.s72
    s72.State.active = False
    requests = []
    controls = {
        "outage": False, "pagination": False, "revoked": False, "w5": False,
        "candidate_search_created": False, "w6": False,
        "participation_created": False, "availability_created": False,
        "w7": False, "scenario_titles": [], "w8": False,
        "w8_pack_created": False, "w8_seal_payload": None,
        "p0_attention": False, "p0_context_conflict": False,
        "p1_running": False, "p1_failed": False,
        "source_pursuit_created": False,
        # D2-02 library fixture: the own firm starts "not set up yet" (GET 404).
        "d202": False, "d202_self_firm": None, "d202_analysis": False,
        # D2-05: a full SOURCE analysis, EOI suggestions and drafts.
        "d205": False, "d205_drafts": [], "d205_posts": [], "d205_reviews": [],
    }
    rows = []
    # D1-06 one door: the SOURCE pursuit the Explorer/Tender Details CTA creates or resolves.
    SOURCE_PURSUIT_ID = "73000000-0000-4000-8000-000000000110"
    W3_PURSUIT_ID = "73000000-0000-4000-8000-000000000010"
    ORGANIZATION_ID = "73000000-0000-4000-8000-000000000001"

    def w3_context():
        source_buyer = "Town of University Park" if controls["p0_context_conflict"] else "Synthetic Transport Authority"
        source_deadline = "2012-02-17T16:00:00-05:00" if controls["p0_context_conflict"] else "2026-12-30T10:00:00Z"
        return {
            "pursuit_id": "73000000-0000-4000-8000-000000000010",
            "title": "Synthetic transport modernization procurement",
            "buyer": "Synthetic Transport Authority",
            "declared_funder": "Synthetic Development Partner",
            "country": "Uzbekistan",
            "reference": "W3-REF-1",
            "procurement_stage": "Request for proposals",
            "external_deadline": "2026-12-30T10:00:00Z",
            "deadline_timezone": "Asia/Tashkent",
            "source_url": None,
            "confirmed_fields": ["title", "buyer", "declared_funder", "country"],
            "field_provenance": [
                {"field_name":"title","provenance_state":"USER_CONFIRMED","source_value":"Synthetic transport modernization procurement","user_confirmed_value":"Synthetic transport modernization procurement"},
                {"field_name":"buyer","provenance_state":"USER_OVERRIDE_CONFLICTS_WITH_SOURCE" if controls["p0_context_conflict"] else "USER_CONFIRMED","source_value":source_buyer,"user_confirmed_value":"Synthetic Transport Authority"},
                {"field_name":"declared_funder","provenance_state":"USER_CONFIRMED","source_value":None,"user_confirmed_value":"Synthetic Development Partner"},
                {"field_name":"country","provenance_state":"USER_CONFIRMED","source_value":None,"user_confirmed_value":"Uzbekistan"},
                {"field_name":"reference","provenance_state":"SOURCE_DETECTED","source_value":"W3-REF-1","user_confirmed_value":None},
                {"field_name":"procurement_stage","provenance_state":"UNKNOWN","source_value":None,"user_confirmed_value":None},
                {"field_name":"external_deadline","provenance_state":"USER_OVERRIDE_CONFLICTS_WITH_SOURCE" if controls["p0_context_conflict"] else "USER_CONFIRMED","source_value":source_deadline,"user_confirmed_value":"2026-12-30T10:00:00Z"},
                {"field_name":"deadline_timezone","provenance_state":"USER_CONFIRMED","source_value":None,"user_confirmed_value":"Asia/Tashkent"},
                {"field_name":"source_url","provenance_state":"UNKNOWN","source_value":None,"user_confirmed_value":None},
            ],
        }

    def w3_pursuit():
        return {
            "pursuit_id": "73000000-0000-4000-8000-000000000010",
            "organization_id": "73000000-0000-4000-8000-000000000001",
            "source_tender_id": None,
            "origin": "UPLOAD",
            "owner_membership_id": "73000000-0000-4000-8000-000000000003",
            "stage": "SAVED",
            "created_at": "2026-09-26T08:00:00Z",
            "updated_at": "2026-09-26T08:15:00Z",
            "stage_changed_at": "2026-09-26T08:00:00Z",
            "tender_title": None,
            "source_deadline": None,
            **w3_context(),
            "processing_state": "READY",
            "file_count": 1,
            "processed_count": 1,
            "failed_count": 0,
            "owner_name": "Synthetic Pilot",
        }

    def w3_document():
        return {
            "document_id": "73000000-0000-4000-8000-000000000011",
            "current_version_id": "73000000-0000-4000-8000-000000000012",
            "role": "RFP",
            "display_name": "synthetic-rfp.pdf",
            "version_number": 1,
            "media_type": "application/pdf",
            "byte_size": 184320,
            "sha256": "a" * 64,
            "processing_state": "READY",
            "page_count": 12,
            "page_count_known": True,
            "retry_allowed": False,
            "error_code": None,
            "created_at": "2026-09-26T08:00:00Z",
            "updated_at": "2026-09-26T08:15:00Z",
        }

    def w6_participation():
        availability = ({
            "fact_id":"73000000-0000-4000-8000-000000000061","status":"AVAILABLE",
            "effective_status":"AVAILABLE","is_expired":False,"window_start":None,"window_end":None,
            "effort_percent":None,"capacity_description":"One delivery team","location_travel_constraints":None,
            "confirmation_source":"CALL","observed_at":"2026-09-26T09:00:00Z",
            "valid_until":"2026-10-03T09:00:00Z","supporting_document_version_id":None,
            "supersedes_fact_id":None,"actor_membership_id":"73000000-0000-4000-8000-000000000003",
            "created_at":"2026-09-26T09:00:00Z",
        } if controls["availability_created"] else None)
        history = ([{
            "event_kind":"AVAILABILITY","event_id":availability["fact_id"],"recorded_state":"AVAILABLE",
            "confirmation_source":"CALL","observed_at":availability["observed_at"],
            "actor_membership_id":"73000000-0000-4000-8000-000000000003","supersedes_id":None,
            "created_at":availability["created_at"],
        }] if availability else [])
        return {
            "participation_record_id":"73000000-0000-4000-8000-000000000060",
            "organization_id":"73000000-0000-4000-8000-000000000001",
            "pursuit_id":"73000000-0000-4000-8000-000000000010",
            "candidate_match_id":"73000000-0000-4000-8000-000000000053",
            "shortlist_decision_id":"73000000-0000-4000-8000-000000000054",
            "effective_shortlist_decision_id":"73000000-0000-4000-8000-000000000054",
            "effective_shortlist_state":"SHORTLISTED",
            "candidate_search_run_id":"73000000-0000-4000-8000-000000000051",
            "analysis_run_id":"73000000-0000-4000-8000-000000000030",
            "gap_id":"73000000-0000-4000-8000-000000000035","candidate_kind":"FIRM",
            "candidate_id":"73000000-0000-4000-8000-000000000050","candidate_name":"Aqua Advisory",
            "proposed_contribution":"JV member for comparable contracts","w5_qualification_state":"PARTIAL",
            "w5_candidate_evidence_state":"REVIEWED","w5_strongest_evidence":[],
            "w5_missing_or_weak_evidence":["Contract value is not recorded."],"assignment_dates":None,
            "assignment_window_coverage":"UNKNOWN_DATES","latest_availability":availability,
            "latest_interest":None,"latest_participation":None,"upstream_stale":False,
            "upstream_stale_reason":None,"same_candidate_record_ids":[],"history":history,
            "created_by_membership_id":"73000000-0000-4000-8000-000000000003",
            "created_at":"2026-09-26T08:45:00Z",
        }

    def w7_scenario(title, index):
        suffix = f"{70 + index:012d}"
        scenario_id = f"73000000-0000-4000-8000-{suffix}"
        revision_id = f"73000000-0000-4000-8001-{suffix}"
        participant_id = f"73000000-0000-4000-8002-{suffix}"
        contribution_id = f"73000000-0000-4000-8003-{suffix}"
        issue_id = f"73000000-0000-4000-8004-{suffix}"
        revision = {
            "revision_id":revision_id,"version_number":1,
            "analysis_run_id":"73000000-0000-4000-8000-000000000030",
            "analysis_pack_id":"73000000-0000-4000-8000-000000000031",
            "selection_sha256":"d"*64,"assessment_schema_version":"w7-team-scenario-v1",
            "assessment_state":"NEEDS_REVIEW","current_assessment_state":"NEEDS_REVIEW",
            "scenario_current":True,"stale_reasons":[],"gap_count":2,"covered_gap_count":0,
            "unresolved_gap_count":2,"participant_count":1,"confirmed_participant_count":0,
            "issue_count":2,"blocking_issue_count":0,"unresolved_later_stage_count":0,
            "source_provenance_count":0,"private_provenance_count":1,
            "participants":[{"participant_id":participant_id,"participant_type":"PARTNER_FIRM",
                "candidate_id":"73000000-0000-4000-8000-000000000050","display_name":"Aqua Advisory",
                "contributions":[{"contribution_id":contribution_id,
                    "candidate_match_id":"73000000-0000-4000-8000-000000000053",
                    "participation_record_id":"73000000-0000-4000-8000-000000000060",
                    "gap_id":"73000000-0000-4000-8000-000000000035",
                    "requirement_id":"73000000-0000-4000-8000-000000000033","position_id":None,
                    "shortlist_decision_id":"73000000-0000-4000-8000-000000000054",
                    "shortlist_decision_state":"SHORTLISTED",
                    "proposed_contribution":"JV member for comparable contracts",
                    "contribution_rule":"Joint venture members collectively may satisfy this requirement",
                    "qualification_state":"PARTIAL","candidate_evidence_state":"REVIEWED",
                    "evidence_identities":[],"strongest_evidence":[],"availability_fact_id":None,
                    "availability_recorded_state":None,"availability_effective_state":None,
                    "availability_window_start":None,"availability_window_end":None,
                    "availability_effort_percent":None,"availability_capacity":None,
                    "availability_valid_until":None,"interest_fact_id":None,
                    "interest_recorded_state":None,"interest_effective_state":None,
                    "interest_conditions":None,"participation_decision_id":None,
                    "participation_recorded_state":None,"participation_effective_state":None,
                    "confirmation_source":None,"confirmation_observed_at":None,"reconfirm_by":None,
                    "confirmation_conditions":None,"assignment_dates":None,
                    "assignment_window_result":"UNKNOWN_DATES","upstream_stale":False}]}],
            "gap_assessments":[
                {"gap_assessment_id":f"73000000-0000-4000-8005-{suffix}",
                 "gap_id":"73000000-0000-4000-8000-000000000035",
                 "requirement_id":"73000000-0000-4000-8000-000000000033","position_id":None,
                 "review_assertion_id":"73000000-0000-4000-8000-000000000052",
                 "w4_coverage_state":"EVIDENCE_MISSING","w4_review_state":"CONFIRMED",
                 "resolution_category":"PARTNER_FIRM",
                 "state":"PARTIAL","is_current_stage":True,"is_blocking":True,
                 "rationale_code":"CANDIDATE_EVIDENCE_INCOMPLETE"},
                {"gap_assessment_id":f"73000000-0000-4000-8006-{suffix}",
                 "gap_id":"73000000-0000-4000-8000-000000000036","requirement_id":None,
                 "position_id":"73000000-0000-4000-8000-000000000034",
                 "review_assertion_id":"73000000-0000-4000-8000-000000000052",
                 "w4_coverage_state":"GAP","w4_review_state":"CONFIRMED",
                 "resolution_category":"EXPERT",
                 "state":"UNRESOLVED",
                 "is_current_stage":True,"is_blocking":True,"rationale_code":"NO_SELECTED_CONTRIBUTION"}],
            "issues":[{"issue_id":issue_id,"issue_code":"PARTIAL_CANDIDATE_EVIDENCE",
                "severity":"REVIEW","gap_id":"73000000-0000-4000-8000-000000000035",
                "participant_id":participant_id,"contribution_id":contribution_id,"details":{}},
                {"issue_id":f"73000000-0000-4000-8007-{suffix}","issue_code":"UNRESOLVED_GAP",
                "severity":"REVIEW","gap_id":"73000000-0000-4000-8000-000000000036",
                "participant_id":None,"contribution_id":None,"details":{}}],
            "decisions":[],"created_by_membership_id":"73000000-0000-4000-8000-000000000003",
            "created_at":"2026-09-26T10:00:00Z",
        }
        return {"scenario_id":scenario_id,"organization_id":"73000000-0000-4000-8000-000000000001",
            "pursuit_id":"73000000-0000-4000-8000-000000000010",
            "lead_organization_id":"73000000-0000-4000-8000-000000000001","title":title,
            "archived_at":None,"latest_revision":revision,"revisions":[revision],
            "created_by_membership_id":"73000000-0000-4000-8000-000000000003",
            "created_at":"2026-09-26T10:00:00Z"}

    def w8_scenario():
        scenario = w7_scenario("Approved delivery team", 8)
        revision = scenario["revisions"][0]
        revision.update({
            "assessment_state":"VIABLE", "current_assessment_state":"VIABLE",
            "gap_count":1, "covered_gap_count":1, "unresolved_gap_count":0,
            "confirmed_participant_count":1, "issue_count":0,
            "blocking_issue_count":0, "unresolved_later_stage_count":1,
            "issues":[],
        })
        revision["gap_assessments"] = [{
            **revision["gap_assessments"][0], "state":"COVERED",
            "is_blocking":False, "rationale_code":"SELECTED_CONTRIBUTION_COVERS_GAP",
        }]
        revision["decisions"] = [{
            "decision_id":"73000000-0000-4000-8006-000000000078",
            "revision_id":revision["revision_id"], "decision":"APPROVED_FOR_PROPOSAL",
            "reason":"Explicit browser fixture approval", "explicit_confirmation":True,
            "actor_membership_id":"73000000-0000-4000-8000-000000000003",
            "created_at":"2026-09-26T10:05:00Z",
        }]
        scenario["latest_revision"] = revision
        return scenario

    def w8_pack():
        scenario = w8_scenario()
        revision = scenario["revisions"][0]
        base = {
            "review_state":"CONFIRMED", "evidence_state":"REVIEWED",
            "requirement_id":None, "position_id":None, "gap_id":None,
            "source_sha256":None, "source_version":None,
        }
        raw_items = [
            ("REQUIREMENT", "PursuitRequirement", "73000000-0000-4000-8000-000000000033", "SEALED_W4", "Requirement matrix row", {
                "reviewed_label":"At least three similar contracts", "original_language_requirement":"at least three similar contracts",
                "source_locator":{"page_number":4,"paragraph_number":12}, "effective_review_state":"CONFIRMED",
                "scenario_gap_outcome":"COVERED", "remaining_condition":"Confirm final reference formatting",
                "contributors":[{"display_name":"Aqua Advisory","evidence_state":"REVIEWED","participation_state":"CONFIRMED"}],
            }),
            ("FIRM", "Organization", "73000000-0000-4000-8000-000000000001", "ORGANIZATION_AUTHORITY", "Lead organization", {
                "role":"LEAD_ORGANIZATION", "display_name":"Synthetic Organization", "contributions":[],
            }),
            ("FIRM", "Firm", "73000000-0000-4000-8000-000000000050", "SEALED_W5_VIA_W7", "Partner firm", {
                "role":"PARTNER_FIRM", "display_name":"Aqua Advisory", "contributions":[{
                    "proposed_contribution":"JV member for comparable contracts", "qualification_state":"QUALIFIED",
                    "evidence_state":"REVIEWED",
                }],
            }),
            ("PROJECT_REFERENCE", "ProjectReference", "73000000-0000-4000-8000-000000000091", "REVIEWED_STRUCTURED_REFERENCE", "Firm reference", {
                "project":"Regional water network", "display_name":"Regional water network", "role":"JV_MEMBER",
                "value_basis":"TOTAL_CONTRACT", "value_is_firm_share":False,
            }),
            ("PARTICIPATION_CONFIRMATION", "CandidateParticipationRecord", "73000000-0000-4000-8000-000000000060", "SEALED_W6_VIA_W7", "Exact participation facts", {
                "display_name":"Aqua Advisory participation", "participation_effective_state":"CONFIRMED",
                "provenance_independently_verified":False,
            }),
            ("PRIVATE_DOCUMENT", "PrivateDocumentVersion", "73000000-0000-4000-8000-000000000012", "ORGANIZATION_PRIVATE_UPLOAD", "Sealed input document", {
                "display_name":"synthetic-rfp.pdf", "role":"RFP",
            }),
            ("LATER_STAGE_OBLIGATION", "PursuitGap", "73000000-0000-4000-8000-000000000099", "SEALED_W4", "Future-stage obligation", {
                "label":"Obtain power of attorney before submission", "stage_scope":"SUBMISSION",
            }),
            ("FORM_OR_REQUIRED_ARTIFACT", "PursuitRequirement", "73000000-0000-4000-8000-000000000098", "SEALED_W4", "Required form checklist", {
                "label":"Signed technical proposal form", "completion_state":"REQUIRED",
            }),
        ]
        items = []
        for ordinal, (category, authority, identity, provenance, purpose, payload) in enumerate(raw_items, 1):
            items.append({
                "item_id":f"73000000-0000-4000-8007-{ordinal:012d}", "ordinal":ordinal,
                "category":category, "source_authority_type":authority, "source_identity":identity,
                "provenance":provenance, "purpose":purpose, "payload":payload, **base,
            })
        return {
            "pack_id":"73000000-0000-4000-8008-000000000001",
            "workspace_id":"73000000-0000-4000-8008-000000000002",
            "organization_id":"73000000-0000-4000-8000-000000000001",
            "pursuit_id":"73000000-0000-4000-8000-000000000010", "pack_version":1,
            "scenario_id":scenario["scenario_id"], "scenario_revision_id":revision["revision_id"],
            "approval_decision_id":revision["decisions"][0]["decision_id"],
            "analysis_run_id":revision["analysis_run_id"], "analysis_pack_id":revision["analysis_pack_id"],
            "schema_version":"w8-proposal-evidence-pack-v1", "manifest_sha256":"e"*64,
            "pack_state":"SEALED", "scenario_title":scenario["title"],
            "pursuit_title":"Synthetic transport modernization procurement",
            "item_count":len(items), "matrix_row_count":1, "participant_count":1,
            "later_stage_count":1, "checklist_count":1, "pack_current":True,
            "stale_reasons":[], "items":items, "artifacts":[],
            "sealed_by_membership_id":"73000000-0000-4000-8000-000000000003",
            "created_at":"2026-09-26T10:06:00Z",
        }

    D202_SELF_FIRM_ID = "73000000-0000-4000-8000-000000000201"
    D202_PARTNER_ID = "73000000-0000-4000-8000-000000000202"
    D202_EXPERT_ID = "73000000-0000-4000-8000-000000000203"

    def d202_reference(reference_id, firm_id, name, **values):
        return {
            "reference_id": reference_id, "firm_id": firm_id, "project_name": name,
            "client_name": "Regional grid company", "country": "Uzbekistan", "service": "Detailed design",
            "sector": "Energy", "role": "LEAD", "contract_share_percent": None, "contract_value": "250000.00",
            "contract_currency": "USD", "value_basis": "CONTRACT_TOTAL", "start_date": "2021-03-01",
            "completion_date": "2022-11-30", "completion_state": "COMPLETED",
            "relevant_scope": "Design of two 110 kV substations", "evidence_provenance": {},
            "evidence_state": "UNVERIFIED", "evidence_basis": "METADATA_ONLY", "supersedes_reference_id": None,
            "archived_at": None, "created_at": "2026-09-30T08:00:00Z", **values,
        }

    def d202_firm(firm_id, name, references, **values):
        return {
            "firm_id": firm_id, "is_self_firm": False, "scope": "ORGANIZATION_PRIVATE", "canonical_name": name,
            "display_name": name, "legal_name": None, "country": "Kazakhstan", "regions": [], "services": ["Substation design"],
            "capabilities": [], "sectors": ["Energy"], "source_type": "MANUAL", "source_provenance": {},
            "evidence_state": "UNVERIFIED", "project_references": references,
            "created_at": "2026-09-30T08:00:00Z", "updated_at": "2026-09-30T08:00:00Z", **values,
        }

    def d202_cv(version):
        return {
            "cv_version_id": f"73000000-0000-4000-8000-00000000021{version}", "expert_id": D202_EXPERT_ID,
            "version_number": version, "education": [{"degree": "MSc Electrical Engineering"}], "qualifications": [],
            "certifications": [], "assignments": [{"role": "Team Leader", "client": "Grid company", "start": "2020-01"}] * version,
            "languages": [{"language": "English"}], "evidence_provenance": {}, "evidence_state": "UNVERIFIED",
            "structured_sha256": f"{version}" * 64, "created_at": f"2026-09-2{version}T08:00:00Z",
        }

    def d202_library():
        return {
            "self_firm": controls["d202_self_firm"],
            "firms": [d202_firm(D202_PARTNER_ID, "Grid Partner LLP", [
                d202_reference("73000000-0000-4000-8000-000000000204", D202_PARTNER_ID, "Almaty substation design"),
            ])],
            "experts": [{
                "expert_id": D202_EXPERT_ID, "scope": "ORGANIZATION_PRIVATE", "display_name": "Aziza Karimova",
                "qualifications": ["MSc Electrical Engineering"], "languages": ["English", "Russian"],
                "specializations": ["Substation design"], "consent_state": "NOT_REQUIRED_PRIVATE",
                "evidence_state": "UNVERIFIED", "source_provenance": {}, "cv_versions": [d202_cv(1), d202_cv(2)],
                "created_at": "2026-09-20T08:00:00Z", "updated_at": "2026-09-22T08:00:00Z",
            }],
        }

    D205_RUN_ID = "73000000-0000-4000-8000-000000000150"
    D205_OWN_REF = "73000000-0000-4000-8000-000000000300"
    D205_OWN_REF_2 = "73000000-0000-4000-8000-000000000301"
    D205_PARTNER_REF = "73000000-0000-4000-8000-000000000204"
    D205_REQ_EXPERIENCE = "73000000-0000-4000-8000-000000000151"
    D205_REQ_LICENSE = "73000000-0000-4000-8000-000000000152"
    D205_REQ_LATER = "73000000-0000-4000-8000-000000000153"
    D205_NOTE = "73000000-0000-4000-8000-000000000154"
    D205_NOTE_INFO = "73000000-0000-4000-8000-000000000155"

    def d205_requirement(requirement_id, statement, quote, state, **values):
        return {
            "requirement_id": requirement_id, "pack_item_id": "73000000-0000-4000-8000-000000000156",
            "original_quote": quote, "source_context": None, "normalized_requirement": statement,
            "effective_normalized_requirement": statement, "category": "EXPERIENCE", "requirement_type": "QUALIFICATION",
            "stage_scope": "EXPRESSION_OF_INTEREST", "distinction": "MANDATORY", "predicate": None, "contribution_rule": None,
            "coverage_state": state, "effective_coverage_state": state, "review_state": "PROVISIONAL",
            "effective_review_state": "PROVISIONAL", "source_locator": {"page_number": None, "paragraph_number": 4},
            "generated_interpretation": None, "matched_reference_ids": [], **values,
        }

    def d205_analysis():
        experience = d205_requirement(D205_REQ_EXPERIENCE, "At least two completed substation design contracts in the last 10 years",
            "Successful completion of at least two contracts within the last 10 years involving detailed engineering designs for substations.",
            "PARTIAL", matched_reference_ids=[D205_OWN_REF], generated_interpretation="Two comparable completed contracts are expected.")
        license_row = d205_requirement(D205_REQ_LICENSE, "Valid licenses for high-complexity facility design",
            "The firm must hold valid licenses specified in Articles 8.1.3.1 and 8.1.14.7 of the Law of Mongolia on Permits.",
            "EVIDENCE_MISSING", category="LEGAL", requirement_type="CERTIFICATION")
        later = d205_requirement(D205_REQ_LATER, "Prepare detailed designs for 12 sub-projects",
            "The Consultant shall prepare comprehensive detailed engineering designs for 12 identified sub-projects.",
            "LATER_STAGE_OBLIGATION", stage_scope="CONTRACT_EXECUTION")
        notes = [
            {**d205_requirement(D205_NOTE, "Deliver the expression of interest by e-mail by 16 October 2026",
                "Expressions of interest must be delivered in written form via e-mail no later than 16 October 2026.",
                "NOT_APPLICABLE", requirement_type="SUBMISSION_INSTRUCTION"), "note_kind": "SUBMISSION_INSTRUCTION"},
            {**d205_requirement(D205_NOTE_INFO, "Key Experts will not be evaluated during the shortlisting stage",
                "Key Experts will not be evaluated during the shortlisting stage.", "NOT_APPLICABLE",
                distinction="INFORMATIONAL"), "note_kind": "INFORMATIONAL"},
        ]
        gap = lambda gap_id, requirement_id, state, statement: {
            "gap_id": gap_id, "requirement_id": requirement_id, "position_id": None,
            "source_pack_item_id": "73000000-0000-4000-8000-000000000156", "missing_contribution": statement,
            "coverage_state": state, "effective_coverage_state": state, "resolution_category": "COMPANY_EVIDENCE",
            "effective_resolution_category": "COMPANY_EVIDENCE", "review_state": "PROVISIONAL",
            "effective_review_state": "PROVISIONAL", "rationale": "Synthetic.",
        }
        return {
            "analysis_run_id": D205_RUN_ID, "analysis_pack_id": "73000000-0000-4000-8000-000000000157", "status": "COMPLETED",
            "result_completeness": "FULL", "analysis_language": "en", "model_provider": "google-gemini",
            "quality_state": "READY_FOR_REVIEW", "quality_summary": "Extraction is materially populated and ready for human review.",
            "model_name": "gemini-3.8-flash", "prompt_version": "pursuit_analysis_d2_v1", "schema_version": "pursuit_analysis_output_p0_v2",
            "pipeline_version": "pursuit_analysis_pipeline_d2_v1", "created_at": "2026-09-30T08:00:00Z",
            "completed_at": "2026-09-30T08:01:00Z", "failure_stage": None, "failure_reason": None, "inputs_changed": False,
            "stale_reason": None, "page_count_known": False,
            "limit_disclosure": "Rendered page count could not be measured; admitted under the character limit.",
            "pack_items": [{"pack_item_id": "73000000-0000-4000-8000-000000000156", "item_kind": "SOURCE",
                            "provenance": "SHARED_SOURCE", "display_name": "Official notice text", "role": "OFFICIAL_NOTICE",
                            "version_number": None, "page_count": None, "page_count_known": False, "content_sha256": "a" * 64,
                            "source_url": "https://example.invalid/notice"}],
            "requirements": [experience, license_row, later], "positions": [],
            "gaps": [gap("73000000-0000-4000-8000-000000000158", D205_REQ_EXPERIENCE, "PARTIAL", experience["effective_normalized_requirement"]),
                     gap("73000000-0000-4000-8000-000000000159", D205_REQ_LICENSE, "EVIDENCE_MISSING", license_row["effective_normalized_requirement"])],
            "submission_and_notes": notes,
        }

    def d205_reference(reference_id, name, matched, rank, **values):
        return {**{key: value for key, value in d202_reference(reference_id, D202_SELF_FIRM_ID, name).items()
                   if key not in {"firm_id", "evidence_provenance", "supersedes_reference_id", "archived_at", "created_at"}},
                "matched_requirement_ids": matched, "suggested": bool(matched), "rank": rank, **values}

    def d205_suggestions():
        return {
            "analysis_run_id": D205_RUN_ID, "run_current": True,
            "defaults": {"assignment_title": "LOT-4 Detailed design SHINE project", "reference_no": "OP00468882",
                         "addressee_organization": "Ministry of Energy, Mongolia", "addressee_name": "Munkhbadral Purevsuren",
                         "addressee_email": "procurement@example.invalid", "firm_name": "Synthetic Organization", "firm_country": "Uzbekistan"},
            "criteria": [{"requirement_id": item["requirement_id"], "statement": item["effective_normalized_requirement"],
                          "original_quote": item["original_quote"], "locator": {"page_number": None, "paragraph_number": 4},
                          "effective_coverage_state": item["effective_coverage_state"],
                          "matched_reference_ids": [D205_OWN_REF] if item["requirement_id"] == D205_REQ_EXPERIENCE else []}
                         for item in d205_analysis()["requirements"]],  # includes a LATER_STAGE_OBLIGATION the UI must hide
            "notes": [{"requirement_id": item["requirement_id"], "note_kind": item["note_kind"],
                       "statement": item["effective_normalized_requirement"], "original_quote": item["original_quote"]}
                      for item in d205_analysis()["submission_and_notes"]],
            "own_references": [
                d205_reference(D205_OWN_REF, "Navoi substation design", [D205_REQ_EXPERIENCE], 1),
                d205_reference(D205_OWN_REF_2, "Rural water supply design", [], 2, sector="Water"),
            ],
            "partner_firms": [{"firm_id": D202_PARTNER_ID, "display_name": "Grid Partner LLP", "country": "Kazakhstan",
                               "covers_requirement_ids": [D205_REQ_EXPERIENCE, D205_REQ_LICENSE],
                               "references": [d205_reference(D205_PARTNER_REF, "Almaty substation design",
                                                             [D205_REQ_EXPERIENCE, D205_REQ_LICENSE], 1, country="Kazakhstan")]}],
        }

    def d205_draft(version, language, current, reasons=()):
        return {
            "draft_id": f"73000000-0000-4000-8000-{400 + version:012d}", "version": version,
            "created_at": f"2026-09-30T0{version}:00:00Z", "created_by_membership_id": "73000000-0000-4000-8000-000000000003",
            "analysis_run_id": D205_RUN_ID, "language": language, "current": current, "stale_reasons": list(reasons),
            "artifacts": [{"artifact_id": f"73000000-0000-4000-8000-{500 + version * 2:012d}", "format": "DOCX", "sha256": "d" * 64, "byte_size": 4096},
                          {"artifact_id": f"73000000-0000-4000-8000-{501 + version * 2:012d}", "format": "PDF", "sha256": "e" * 64, "byte_size": 8192}],
            "summary": {"criteria_total": 3, "criteria_with_references": 2, "criteria_without_references": 1,
                        "own_reference_count": 1, "partner_count": 1, "relevance_notes_generated": 1, "relevance_notes_dropped": 1},
        }

    def d202_read_json(handler):
        length = int(handler.headers.get("content-length", "0"))
        return json.loads(handler.rfile.read(length) or b"{}") if length else {}

    class Handler(fixture.Handler):
        def send_json(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            offset = int(parse_qs(urlparse(self.path).query).get("offset", ["0"])[0])
            self.send_header("X-Has-More", str(controls["pagination"] and offset == 0).lower())
            self.send_header("X-Total-Count", "26" if controls["pagination"] else "1")
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            requests.append(("GET", self.path))
            parsed_path = urlparse(self.path).path
            if controls["revoked"] and urlparse(self.path).path.startswith("/api/v1/"):
                return self.send_json(401, {"detail":"Session revoked"})
            if parsed_path == "/api/v1/explorer/tenders":
                # D1-08: a stored recommendation (score 88 + rationale) is still in the payload of
                # older backends; the UI must not render it. Facts come from profile_match.
                row = {**fixture.mixed_tender(), "notice_type": "Request for Expression of Interest"}
                return self.send_json(200, {
                    "view": "all", "items": [{
                        "tender": row,
                        "recommendation": {
                            "recommendation_id": "rec-d108", "match_score": 88,
                            "rationale_summary": "Generated rationale that must not be rendered.",
                            "is_dismissed": False, "created_at": "2026-09-02T10:00:00Z",
                        },
                        "pursuit": None,
                        "profile_match": {"country": "Uzbekistan", "services": ["consulting"]},
                    }],
                    "total": 1, "limit": 25, "offset": 0,
                    "counts": {"all_tenders": 1, "active_recommendations": 1, "dismissed_recommendations": 0},
                    "recommendation_availability": "AVAILABLE", "server_time": "2026-09-02T10:00:00Z",
                })
            if SOURCE_PURSUIT_ID in parsed_path:
                base = f"/api/v1/pursuits/{SOURCE_PURSUIT_ID}"
                if parsed_path == base:
                    return self.send_json(200, {
                        **w3_pursuit(), "pursuit_id": SOURCE_PURSUIT_ID, "origin": "SOURCE",
                        "source_tender_id": "s72-tender", "tender_title": "Source tender",
                        "title": "Source tender", "file_count": 0, "processed_count": 0, "processing_state": None,
                    })
                if parsed_path == base + "/documents":
                    return self.send_json(200, {"items": []})
                if controls["d205"] and parsed_path == base + "/analysis-runs/latest":
                    return self.send_json(200, d205_analysis())
                if controls["d205"] and parsed_path == base + "/eoi/suggestions":
                    return self.send_json(200, d205_suggestions())
                if controls["d205"] and parsed_path == base + "/eoi-drafts":
                    return self.send_json(200, sorted(controls["d205_drafts"], key=lambda item: -item["version"]))
                if controls["d205"] and parsed_path.startswith(base + "/eoi-artifacts/"):
                    body = b"PK synthetic eoi"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Disposition", 'attachment; filename="eoi-OP00468882-server.docx"')
                    self.send_header("Cache-Control", "private, no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return None
                if parsed_path == base + "/analysis-runs/latest":
                    if not controls["d202_analysis"]:
                        return self.send_json(200, None)
                    requirement = {"effective_coverage_state": "EVIDENCE_MISSING"}
                    return self.send_json(200, {
                        "analysis_run_id": "73000000-0000-4000-8000-000000000140", "status": "COMPLETED",
                        "completed_at": "2026-09-30T09:00:00Z", "requirements": [requirement, {"effective_coverage_state": "PARTIAL"}],
                        "positions": [], "gaps": [{}, {}], "submission_and_notes": [{}],
                    })
                if parsed_path == base + "/team-scenarios":
                    return self.send_json(200, [])
                if parsed_path == base + "/analysis-pack-candidate":
                    def source_document(identity, role, name):
                        return {
                            "tender_document_id": identity, "display_name": name, "role": role,
                            "snapshot_sha256": "d" * 64, "content_sha256": "e" * 64, "analyzed_text_sha256": "f" * 64,
                            "extracted_character_count": 5300, "file_type": "text/plain", "parse_ready": True,
                            "page_count": None, "page_count_known": False, "language": None,
                            "source_url": "https://example.invalid/s72", "duplicate_warning": None,
                            "provenance": "SHARED_SOURCE", "captured_at": "2026-09-26T08:16:00Z",
                        }
                    return self.send_json(200, {
                        "schema_version": "w4-analysis-pack-candidate-v1", "candidate_sha256": "c" * 64,
                        "organization_id": ORGANIZATION_ID, "pursuit_id": SOURCE_PURSUIT_ID,
                        "pursuit_origin": "SOURCE", "source_tender_id": "s72-tender", "parse_ready": True,
                        "page_count_total": None,
                        "source_documents": [
                            source_document("73000000-0000-4000-8000-000000000121", "OFFICIAL_SOURCE", "terms-of-reference.pdf"),
                            source_document("73000000-0000-4000-8000-000000000122", "OFFICIAL_NOTICE", "Official notice"),
                        ],
                        "private_versions": [], "generated_at": "2026-09-26T08:16:00Z",
                    })
                # Everything else about the pursuit behaves like the W3 fixture pursuit.
                self.path = self.path.replace(SOURCE_PURSUIT_ID, W3_PURSUIT_ID)
                parsed_path = urlparse(self.path).path
            if parsed_path == "/api/v1/organizations":
                return self.send_json(200, [{
                    "organization_id":"73000000-0000-4000-8000-000000000001",
                    "legacy_company_profile_id":"73000000-0000-4000-8000-000000000002",
                    "display_name":"Synthetic Organization","membership_id":"73000000-0000-4000-8000-000000000003",
                    "membership_role":"OWNER","membership_state":"ACTIVE",
                }])
            if parsed_path == "/api/v1/pursuits":
                pursuit = w3_pursuit()
                items = [pursuit]
                if controls["d202_analysis"]:
                    items.append({**pursuit, "pursuit_id": SOURCE_PURSUIT_ID, "origin": "SOURCE",
                        "source_tender_id": "s72-tender", "title": "Source tender", "external_deadline": "2026-12-15T12:00:00Z"})
                return self.send_json(200, {"items":items,"total":len(items),"limit":100,"offset":0})
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/documents":
                return self.send_json(200, {"items":[w3_document()]})
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/context":
                return self.send_json(200, {**w3_context(), "suggestions":[{
                    "suggestion_id":"73000000-0000-4000-8000-000000000020","field_name":"reference",
                    "suggested_value":"W3-REF-1","document_version_id":"73000000-0000-4000-8000-000000000012",
                    "page_number":1,"evidence_span":"Reference: W3-REF-1","confidence":0.55,"review_state":"PROVISIONAL",
                    "provenance_state":"SOURCE_DETECTED","user_confirmed_value":None,
                }]})
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/analysis-pack-candidate":
                return self.send_json(200, {
                    "schema_version":"w4-analysis-pack-candidate-v1","candidate_sha256":"c"*64,
                    "organization_id":"73000000-0000-4000-8000-000000000001",
                    "pursuit_id":"73000000-0000-4000-8000-000000000010","pursuit_origin":"UPLOAD",
                    "source_tender_id":None,"parse_ready":True,"page_count_total":12,
                    "source_documents":[],"private_versions":[{
                        "private_document_id":"73000000-0000-4000-8000-000000000011",
                        "document_version_id":"73000000-0000-4000-8000-000000000012",
                        "display_name":"synthetic-rfp.pdf","version_number":1,"role":"RFP","content_sha256":"a"*64,
                        "processing_result_id":"73000000-0000-4000-8000-000000000013",
                        "processing_result_sha256":"b"*64,"extracted_character_count":4200,
                        "processing_state":"READY","parse_ready":True,"page_count":12,"page_count_known":True,
                        "language":None,"malware_scan_status":"CLEAN","duplicate_warning":None,
                        "provenance":"ORGANIZATION_PRIVATE_UPLOAD",
                    }],"generated_at":"2026-09-26T08:16:00Z",
                })
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/analysis-runs/latest":
                analysis_status = "RUNNING" if controls["p1_running"] else "FAILED" if controls["p1_failed"] else "COMPLETED"
                analysis_quality = "FAILED" if controls["p1_failed"] else "NEEDS_ATTENTION" if controls["p1_running"] or controls["p0_attention"] else "READY_FOR_REVIEW"
                reviewable = analysis_status == "COMPLETED" and analysis_quality == "READY_FOR_REVIEW"
                return self.send_json(200, {
                    "analysis_run_id":"73000000-0000-4000-8000-000000000030",
                    "analysis_pack_id":"73000000-0000-4000-8000-000000000031","status":analysis_status,
                    "result_completeness":"FULL" if reviewable else "NONE","analysis_language":"en","model_provider":"google-gemini",
                    "quality_state":analysis_quality,
                    "quality_summary":"Analysis is still running." if controls["p1_running"] else "Analysis could not be completed." if controls["p1_failed"] else "Extraction needs review." if controls["p0_attention"] else "Extraction is materially populated and ready for human review.",
                    "model_name":"gemini-3.1-pro-preview","prompt_version":"pursuit_analysis_w4_v1",
                    "schema_version":"pursuit_analysis_output_w4_v1","pipeline_version":"pursuit_analysis_pipeline_w4_v1",
                    "created_at":"2026-09-26T08:20:00Z","completed_at":None if controls["p1_running"] else "2026-09-26T08:21:00Z",
                    "failure_stage":"MODEL_OUTPUT" if controls["p1_failed"] else None,"failure_reason":"Synthetic fixture failure" if controls["p1_failed"] else None,"inputs_changed":not controls["w5"],
                    "stale_reason":None if controls["w5"] else "Current candidate identities or content differ from the sealed pack.",
                    "page_count_known":True,"limit_disclosure":"Exact rendered page total 12/500.",
                    "pack_items":[{"pack_item_id":"73000000-0000-4000-8000-000000000032","item_kind":"PRIVATE",
                        "provenance":"ORGANIZATION_PRIVATE_UPLOAD","display_name":"synthetic-rfp.pdf","role":"RFP",
                        "version_number":1,"page_count":12,"page_count_known":True,"content_sha256":"a"*64,"source_url":None}],
                    "requirements":[{"requirement_id":"73000000-0000-4000-8000-000000000033",
                        "pack_item_id":"73000000-0000-4000-8000-000000000032","original_quote":"at least three similar contracts",
                        "normalized_requirement":"At least three similar contracts","effective_normalized_requirement":"At least three similar contracts",
                        "category":"EXPERIENCE","requirement_type":"CORPORATE_EXPERIENCE","stage_scope":"ELIGIBILITY",
                        "distinction":"MANDATORY","predicate":{"operator":">=","threshold":3,"unit":"contracts"},
                        "contribution_rule":"Joint venture members collectively may satisfy this requirement","coverage_state":"EVIDENCE_MISSING","effective_coverage_state":"EVIDENCE_MISSING",
                        "review_state":"PROVISIONAL","effective_review_state":"CONFIRMED" if controls["w5"] else "PROVISIONAL",
                        "source_locator":{"page_number":4,"paragraph_number":12},"generated_interpretation":"Recorded proof is missing."}] if reviewable else [],
                    "positions":[{"position_id":"73000000-0000-4000-8000-000000000034",
                        "pack_item_id":"73000000-0000-4000-8000-000000000032","title":"Team Leader","effective_title":"Team Leader",
                        "quantity":1,"distinction":"MANDATORY","education_qualification":"Engineering degree",
                        "general_experience":"Ten years","specific_experience":"Three similar assignments","relevant_assignments":None,
                        "languages":["English"],"certifications":[],"location_travel":None,"expected_effort":None,
                        "qualification_criteria":[],
                        "assignment_dates":None,"original_quote":"Team Leader with ten years experience",
                        "coverage_state":"EVIDENCE_MISSING","effective_coverage_state":"EVIDENCE_MISSING",
                        "review_state":"PROVISIONAL","effective_review_state":"PROVISIONAL",
                        "source_locator":{"page_number":8,"paragraph_number":3},"generated_interpretation":None}] if reviewable else [],
                    "gaps":([] if not reviewable else [{"gap_id":"73000000-0000-4000-8000-000000000035",
                        "requirement_id":"73000000-0000-4000-8000-000000000033","position_id":None,
                        "source_pack_item_id":"73000000-0000-4000-8000-000000000032",
                        "missing_contribution":"At least three similar contracts","coverage_state":"EVIDENCE_MISSING",
                        "effective_coverage_state":"EVIDENCE_MISSING","resolution_category":"PARTNER_FIRM","effective_resolution_category":"PARTNER_FIRM",
                        "review_state":"PROVISIONAL","effective_review_state":"CONFIRMED",
                        "rationale":"A reviewed partner contribution is needed."},{
                        "gap_id":"73000000-0000-4000-8000-000000000036",
                        "requirement_id":None,"position_id":"73000000-0000-4000-8000-000000000034",
                        "source_pack_item_id":"73000000-0000-4000-8000-000000000032",
                        "missing_contribution":"Team Leader","coverage_state":"EVIDENCE_MISSING",
                        "effective_coverage_state":"EVIDENCE_MISSING","resolution_category":"EXPERT","effective_resolution_category":"EXPERT",
                        "review_state":"PROVISIONAL","effective_review_state":"CONFIRMED",
                        "rationale":"A reviewed expert contribution is needed."}] if controls["w5"] else [{
                        "gap_id":"73000000-0000-4000-8000-000000000035",
                        "requirement_id":"73000000-0000-4000-8000-000000000033","position_id":None,
                        "source_pack_item_id":"73000000-0000-4000-8000-000000000032",
                        "missing_contribution":"At least three similar contracts","coverage_state":"EVIDENCE_MISSING",
                        "effective_coverage_state":"EVIDENCE_MISSING","resolution_category":"COMPANY_EVIDENCE","effective_resolution_category":"COMPANY_EVIDENCE",
                        "review_state":"PROVISIONAL","effective_review_state":"PROVISIONAL",
                        "rationale":"No current company record proves or disproves this requirement."}]),
                })
            if parsed_path == "/api/v1/candidates/self-firm":
                firm = controls["d202_self_firm"]
                return self.send_json(200, firm) if firm else self.send_json(404, {"detail": "Self firm not found"})
            if parsed_path == "/api/v1/candidates" and controls["d202"]:
                return self.send_json(200, d202_library())
            if parsed_path == "/api/v1/candidates":
                return self.send_json(200, {"firms":[{"firm_id":"73000000-0000-4000-8000-000000000050"}] if controls["w5"] else [],"experts":[]})
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/candidate-search-runs":
                if not controls["candidate_search_created"]:
                    return self.send_json(200, [])
                return self.send_json(200, [{
                    "candidate_search_run_id":"73000000-0000-4000-8000-000000000051",
                    "organization_id":"73000000-0000-4000-8000-000000000001",
                    "pursuit_id":"73000000-0000-4000-8000-000000000010",
                    "analysis_run_id":"73000000-0000-4000-8000-000000000030",
                    "gap_id":"73000000-0000-4000-8000-000000000035","target_kind":"FIRM",
                    "requirement_id":"73000000-0000-4000-8000-000000000033","position_id":None,
                    "review_assertion_id":"73000000-0000-4000-8000-000000000052",
                    "effective_coverage_state":"EVIDENCE_MISSING","effective_review_state":"CONFIRMED",
                    "resolution_category":"PARTNER_FIRM",
                    "contribution_rule":"Joint venture members collectively may satisfy this requirement",
                    "search_version":"w5-postgres-structured-v1","search_parameters":{"source":"POSTGRES_ONLY"},
                    "result_limit":10,"status":"COMPLETED","created_at":"2026-09-26T08:30:00Z",
                    "completed_at":"2026-09-26T08:30:00Z","is_stale":False,"stale_reason":None,
                    "matches":[{"candidate_match_id":"73000000-0000-4000-8000-000000000053",
                        "gap_id":"73000000-0000-4000-8000-000000000035","candidate_kind":"FIRM",
                        "candidate_id":"73000000-0000-4000-8000-000000000050","candidate_name":"Aqua Advisory",
                        "candidate_scope":"ORGANIZATION_PRIVATE","candidate_evidence_state":"REVIEWED",
                        "proposed_contribution":"JV member for comparable contracts",
                        "strongest_evidence":[{"type":"PROJECT_REFERENCE","project_name":"Regional water network","role":"JV_MEMBER","completion_state":"COMPLETED","evidence_state":"VERIFIED"}],
                        "relevant_evidence":[],"missing_or_weak_evidence":["Contract value is not recorded."],
                        "qualification_state":"PARTIAL","rationale":"Reviewed exact-gap evidence is available.",
                        "provenance":{"candidate_scope":"ORGANIZATION_PRIVATE"},"retrieval_rank":1,
                        "latest_review":({"decision_id":"73000000-0000-4000-8000-000000000054",
                            "candidate_search_run_id":"73000000-0000-4000-8000-000000000051",
                            "candidate_match_id":"73000000-0000-4000-8000-000000000053","decision":"SHORTLISTED",
                            "corrected_contribution":None,"reason":"Evidence supports participation follow-up.",
                            "actor_membership_id":"73000000-0000-4000-8000-000000000003",
                            "created_at":"2026-09-26T08:40:00Z"} if controls["w6"] else None)}]
                }])
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/participation-records":
                return self.send_json(200, [w6_participation()] if controls["participation_created"] else [])
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/team-scenarios":
                if controls["w8"]:
                    return self.send_json(200, [w8_scenario()])
                return self.send_json(200, [w7_scenario(title, index) for index,title in enumerate(controls["scenario_titles"])])
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/proposal-workspace":
                pack = w8_pack() if controls["w8_pack_created"] else None
                return self.send_json(200, {
                    "workspace_id":pack["workspace_id"] if pack else None,
                    "organization_id":"73000000-0000-4000-8000-000000000001",
                    "pursuit_id":"73000000-0000-4000-8000-000000000010",
                    "created_by_membership_id":"73000000-0000-4000-8000-000000000003" if pack else None,
                    "created_at":pack["created_at"] if pack else None,
                    "updated_at":pack["created_at"] if pack else None,
                    "legacy_proposal_id":None, "packs":[pack] if pack else [],
                })
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010":
                return self.send_json(200, w3_pursuit())
            if urlparse(self.path).path == "/api/v1/tenders/documents/missing-fixture/download":
                return self.send_json(404, {"detail":"Document file is not stored"})
            if controls["outage"] and urlparse(self.path).path in {"/api/v1/users/me", "/api/v1/users/me/access-status"}:
                return self.send_json(503, {"detail": "Controlled temporary outage"})
            return super().do_GET()
        def do_POST(self):
            requests.append(("POST", self.path))
            parsed_path = urlparse(self.path).path
            if controls["d205"] and parsed_path == f"/api/v1/pursuits/{SOURCE_PURSUIT_ID}/eoi-drafts":
                body = d202_read_json(self)
                controls["d205_posts"].append(body)
                time.sleep(1.5)  # generation takes a while; the UI shows progress
                draft = d205_draft(len(controls["d205_drafts"]) + 1, body.get("language", "en"), True)
                controls["d205_drafts"].append(draft)
                return self.send_json(201, draft)
            if controls["d205"] and parsed_path == f"/api/v1/pursuits/{SOURCE_PURSUIT_ID}/analysis-runs/{D205_RUN_ID}/reviews":
                body = d202_read_json(self)
                controls["d205_reviews"].append(body)
                return self.send_json(201, {"assertion_id": str(len(controls["d205_reviews"])), **body})
            if parsed_path == f"/api/v1/candidates/firms/{D202_SELF_FIRM_ID}/project-references":
                body = d202_read_json(self)
                firm = controls["d202_self_firm"]
                if firm is None:
                    return self.send_json(404, {"detail": "Firm not found"})
                reference = d202_reference(f"73000000-0000-4000-8000-{300 + len(firm['project_references']):012d}", D202_SELF_FIRM_ID,
                    body.get("project_name", ""), **{key: value for key, value in body.items() if key != "project_name"})
                firm["project_references"].append(reference)
                return self.send_json(201, reference)
            if parsed_path == "/api/v1/pursuits/source":
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                if self.headers.get("X-Organization-ID") != ORGANIZATION_ID or body.get("tender_id") != "s72-tender":
                    return self.send_json(409, {"detail": "Organization context required"})
                created = not controls["source_pursuit_created"]
                controls["source_pursuit_created"] = True
                # Idempotent: 201 the first time, 200 for the existing pursuit afterwards.
                return self.send_json(201 if created else 200, {
                    **w3_pursuit(), "pursuit_id": SOURCE_PURSUIT_ID, "origin": "SOURCE", "source_tender_id": "s72-tender",
                })
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/analysis-runs":
                length = int(self.headers.get("content-length", "0"))
                if length:
                    self.rfile.read(length)
                return self.send_json(202, {"analysis_run_id":"73000000-0000-4000-8000-000000000040",
                    "analysis_pack_id":"73000000-0000-4000-8000-000000000041","status":"QUEUED",
                    "selected_pack_sha256":"d"*64,"page_count_known":True,"total_known_pages":12,
                    "limit_disclosure":"Exact rendered page total 12/500."})
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/candidate-search-runs":
                length = int(self.headers.get("content-length", "0"))
                if length:
                    self.rfile.read(length)
                controls["candidate_search_created"] = True
                return self.send_json(201, {"status":"COMPLETED"})
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/candidate-matches/73000000-0000-4000-8000-000000000053/participation-record":
                length = int(self.headers.get("content-length", "0"))
                if length:
                    self.rfile.read(length)
                controls["participation_created"] = True
                return self.send_json(201, w6_participation())
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/participation-records/73000000-0000-4000-8000-000000000060/availability-facts":
                length = int(self.headers.get("content-length", "0"))
                if length:
                    self.rfile.read(length)
                controls["availability_created"] = True
                return self.send_json(201, w6_participation())
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/team-scenarios":
                length = int(self.headers.get("content-length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                controls["scenario_titles"].append(payload.get("title", "Scenario"))
                return self.send_json(201, w7_scenario(controls["scenario_titles"][-1], len(controls["scenario_titles"]) - 1))
            if parsed_path == "/api/v1/pursuits/73000000-0000-4000-8000-000000000010/proposal-evidence-packs":
                length = int(self.headers.get("content-length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                controls["w8_seal_payload"] = payload
                controls["w8_pack_created"] = True
                return self.send_json(201, w8_pack())
            return super().do_POST()
        def do_PATCH(self):
            requests.append(("PATCH", self.path))
            return super().do_PATCH()
        def do_PUT(self):
            requests.append(("PUT", self.path))
            if urlparse(self.path).path == "/api/v1/candidates/self-firm":
                body = d202_read_json(self)
                if controls["d202_self_firm"] is None:
                    controls["d202_self_firm"] = d202_firm(D202_SELF_FIRM_ID, "Synthetic Organization", [],
                        is_self_firm=True, country=None, services=[], sectors=[])
                controls["d202_self_firm"].update({key: value for key, value in body.items()})
                return self.send_json(200, controls["d202_self_firm"])
            return super().do_PUT()

    server = ThreadingHTTPServer((BACKEND_BIND_HOST, 8114), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = os.environ.copy()
    release_dist = os.environ.get("PLASMA_RELEASE_BROWSER_DIST", ".next-release-test")
    env.update(AUTH_SECRET="s72-browser-secret", AUTH_URL=BASE, NEXTAUTH_URL=BASE,
        AUTH_TRUST_HOST="true", NODE_ENV="production", NEXT_DIST_DIR=release_dist,
        BACKEND_INTERNAL_URL="http://127.0.0.1:8114/api/v1")
    log = (OUT / "frontend.log").open("w")
    proc = subprocess.Popen(
        [NPM, "run", "start", "--", "-p", str(BROWSER_PORT)],
        cwd=FRONT,
        env=env,
        stdout=log,
        stderr=log,
        start_new_session=os.name == "posix",
    )
    api_server = None
    external = []

    def case(name, action):
        selected = os.environ.get("PLASMA_BROWSER_CASE_FILTER")
        if selected and selected not in name:
            return
        try:
            evidence = action()
            rows.append({"case": name, "status": "PASS", "evidence": evidence})
        except Exception as error:
            rows.append({
                "case": name,
                "status": "FAIL",
                "error": "".join(traceback.format_exception(error))[-4000:],
            })
        print(rows[-1]["status"], name, flush=True)

    try:
        for _ in range(90):
            try:
                urlopen(PROBE_BASE, timeout=2)
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("Local production frontend did not start")
        def session_token(salt, access_token="s72-token-a"):
            token_js = f"""import {{encode}} from 'next-auth/jwt'; console.log(await encode({{secret:'s72-browser-secret',salt:'{salt}',token:{{name:'Synthetic Pilot',email:'pilot@example.invalid',sub:'72000000-0000-4000-8000-000000000001',accessToken:{json.dumps(access_token)},approval_status:'approved',platform_role:'pilot_user'}},maxAge:3600}}));"""
            return subprocess.check_output(
                [NODE, "--input-type=module", "-e", token_js],
                cwd=FRONT, env=env, text=True,
            ).strip()
        with sync_playwright() as pw:
            browser_args = ["--no-sandbox"]
            if CONNECT_HOST != BROWSER_HOST:
                browser_args.append(f"--host-resolver-rules=MAP {BROWSER_HOST} {CONNECT_HOST}")
            browser = pw.chromium.launch(headless=True, args=browser_args)
            context = browser.new_context(viewport={"width":390,"height":844})
            context.add_cookies([
                {"name":"__Secure-authjs.session-token","value":session_token("__Secure-authjs.session-token"),"url":BASE.replace("http://", "https://", 1),"secure":True,"httpOnly":True,"sameSite":"Lax"},
                {"name":"authjs.session-token","value":session_token("authjs.session-token"),"url":BASE,"httpOnly":True,"sameSite":"Lax"},
            ])
            def network(route):
                if urlparse(route.request.url).hostname not in {"localhost", "127.0.0.1", BROWSER_HOST, CONNECT_HOST}:
                    external.append(route.request.url.split("?")[0])
                    route.abort()
                else:
                    route.continue_()
            context.route("**/*", network)
            context.add_init_script(path=str(AXE_SCRIPT))
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            core_surfaces = [("explorer","tenders?view=all"),("my-tenders","my-tenders"),("bid-preparation","bid-preparation")]
            w3_surfaces = [
                ("uploaded-tenders", "uploaded-tenders"),
                ("upload-tender", "uploaded-tenders/upload"),
                ("pursuit-workspace", "pursuits/73000000-0000-4000-8000-000000000010?organization_id=73000000-0000-4000-8000-000000000001"),
            ]
            surfaces = core_surfaces + w3_surfaces
            def load(path, locale, width):
                controls["outage"] = False
                s72.State.users["s72-token-a"]["ui_locale"] = locale
                page.set_viewport_size({"width":width,"height":900})
                start_external = len(external)
                for attempt in range(3):
                    errors.clear()
                    before = len(requests)
                    try:
                        response = page.goto(BASE + "/dashboard/" + path, wait_until="networkidle")
                    except Exception:
                        if attempt == 2:
                            raise
                        page.wait_for_timeout(300)
                        continue
                    if response.status == 503 and attempt < 2:
                        page.wait_for_timeout(300)
                        continue
                    try:
                        expect(page.locator('h1').first).to_be_visible(timeout=15000)
                    except AssertionError:
                        if attempt == 2:
                            raise
                        page.wait_for_timeout(300)
                        continue
                    break
                page.wait_for_load_state('networkidle')
                page.wait_for_timeout(200)
                assert response.status == 200 and "/dashboard/" in page.url, {
                    "status": response.status,
                    "url": page.url,
                    "requests": requests[before:],
                }
                dom = page.evaluate("""() => ({lang:document.documentElement.lang, dir:document.documentElement.dir,
                    width:innerWidth, scroll:document.documentElement.scrollWidth,
                    heading:document.querySelector('h1')?.textContent,
                    controls:[...document.querySelectorAll('input,select,button')].filter(x=>x.getBoundingClientRect().width>0 && x.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})).map(x=>({tag:x.tagName,id:x.id,text:x.textContent?.slice(0,120),class:x.className,left:x.getBoundingClientRect().left,right:x.getBoundingClientRect().right}))})""")
                assert dom["lang"] == locale and dom["dir"] == ("rtl" if locale == "ar" else "ltr")
                assert dom["heading"] and dom["scroll"] <= width + 1, dom
                assert not errors, errors
                assert len(external) == start_external
                assert all(method == "GET" or path == "/api/v1/auth/refresh" for method,path in requests[before:]), requests[before:]
                counts = Counter(path.split('?')[0] for _,path in requests[before:])
                # Session refresh may repeat one access check on a slow local browser bridge.
                budgets = {'/api/v1/users/me':8,'/api/v1/users/me/access-status':5,'/api/v1/auth/refresh':6}
                assert len(requests[before:]) <= 30, counts
                assert all(counts[path] <= limit for path,limit in budgets.items()), counts
                return {"dom":dom,"requests":dict(Counter(str(item) for item in requests[before:])),"request_budgets":{**budgets,'total':30}}
            for locale in ("en","uz","ru","ar"):
                for width in (320,390,768,1440):
                    for name,path in surfaces:
                        def mobile(path=path, locale=locale, width=width, name=name):
                            evidence = load(path, locale, width)
                            if name == "pursuit-workspace":
                                axe = page.evaluate("""async () => {
                                    const result = await window.axe.run(document);
                                    const violations = result.violations.filter(item => ['serious', 'critical'].includes(item.impact));
                                    return {violations: violations.map(item => ({id:item.id, impact:item.impact, nodes:item.nodes.length})), passes:result.passes.length};
                                }""")
                                assert not axe["violations"], axe
                                evidence["axe"] = {"serious_or_critical": 0, "passes": axe["passes"]}
                            if width <= 390:
                                page.screenshot(path=str(OUT / f"{locale}-{name}-{width}.png"), full_page=True)
                            for control in evidence["dom"]["controls"]:
                                assert control["left"] >= -1 and control["right"] <= width + 1, control
                            if name == "explorer":
                                menu = page.locator('.customer-page .ds-popover-wrap').first
                                menu.locator('button[aria-expanded]').click()
                                assert menu.evaluate("""x => [...x.querySelectorAll('button')].filter(b=>b.checkVisibility()).every(b=>{const r=b.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth;})""")
                                menu.locator('button[aria-expanded]').click()
                            if name == "bid-preparation":
                                assert page.evaluate("""() => {const h=document.querySelector('h1').getBoundingClientRect();const badges=[...document.querySelectorAll('.rounded-full')];return badges.every(b=>{const r=b.getBoundingClientRect();return r.right<=h.left||r.left>=h.right||r.bottom<=h.top||r.top>=h.bottom;});}""")
                            if width == 320:
                                page.screenshot(path=str(OUT / f"{locale}-{name}-320.png"), full_page=True)
                            page.keyboard.press("Tab")
                            assert page.evaluate("document.activeElement !== document.body")
                            return evidence
                        case(f"mobile/{locale}/{width}/{name}", mobile)
                    def recovery(locale=locale,width=width):
                        controls["outage"] = True
                        response = page.goto(BASE + "/dashboard/tenders?view=all", wait_until="networkidle")
                        assert response.status == 503 and "pending-approval" not in page.url
                        assert page.locator('html').get_attribute('lang') == locale
                        assert page.locator('a[href=""]').is_visible()
                        controls["outage"] = False
                        with page.expect_navigation(wait_until='domcontentloaded') as retry:
                            page.locator('a[href=""]').click()
                        assert retry.value is not None and retry.value.status == 200
                        expect(page.locator('h1').first).to_be_visible(timeout=30000)
                        assert "/dashboard/tenders" in page.url and "view=all" in page.url
                        return {"outage_status":503,"retry_url":page.url}
                    case(f"session/{locale}/{width}/outage-retry", recovery)
            def w4_requirements_review():
                load("pursuits/73000000-0000-4000-8000-000000000010?organization_id=73000000-0000-4000-8000-000000000001", "en", 390)
                page.get_by_role("tab", name="Requirements", exact=True).click()
                expect(page.get_by_text("Documents changed — analysis may be out of date", exact=True)).to_be_visible()
                expect(page.locator("[data-requirement-group='attention'] .analysis-group-header").get_by_text("Needs your attention")).to_be_visible()
                expect(page.get_by_text("Required positions", exact=True)).to_be_visible()
                requirement = page.locator("[data-requirement-group='attention'] .analysis-requirement-card").first
                # The original quote and locator are shown directly, not behind a click.
                expect(requirement.get_by_text("at least three similar contracts", exact=True)).to_be_visible()
                expect(requirement.locator("[data-locator]")).to_be_visible()
                expect(requirement.locator("[data-generated-interpretation]")).to_contain_text("Generated interpretation")
                assert page.get_by_text("Find Partner", exact=True).count() == 0
                assert page.get_by_text("Find Expert", exact=True).count() == 0
                pack_review = page.locator(".analysis-pack-review")
                if not pack_review.get_attribute("open"):
                    pack_review.locator("summary").click()
                checkbox = page.locator(".analysis-candidate-row input[type=checkbox]").first
                checkbox.uncheck()
                expect(page.get_by_role("button", name="Analyze selected", exact=True)).to_be_disabled()
                checkbox.check()
                before = len(requests)
                page.get_by_role("button", name="Analyze selected", exact=True).click()
                # Wait for the POST itself (a fixed 500 ms was too short under load and the late POST
                # then leaked into the next case's request log).
                for _ in range(100):
                    if any(method == "POST" and path.split("?")[0].endswith("/analysis-runs") for method,path in requests[before:]):
                        break
                    page.wait_for_timeout(100)
                assert any(method == "POST" and path.split("?")[0].endswith("/analysis-runs") for method,path in requests[before:])
                page.wait_for_load_state("networkidle")
                return {"stale_banner":True,"source_first":True,"explicit_selection":True,"post_count":len(requests[before:])}
            case("w4/requirements-pack-review", w4_requirements_review)
            def p1_async_analysis_states():
                controls["p1_running"] = False
                controls["p1_failed"] = False
                try:
                    load("pursuits/73000000-0000-4000-8000-000000000010?organization_id=73000000-0000-4000-8000-000000000001", "en", 390)
                    page.get_by_role("tab", name="Requirements", exact=True).click()
                    requirement_row = page.locator(".analysis-requirement-card").filter(has_text="At least three similar contracts").first
                    expect(requirement_row).to_be_visible()
                    controls["p1_running"] = True
                    page.get_by_role("button", name="Refresh analysis", exact=True).click()
                    expect(page.get_by_text("Analysis is in progress", exact=True)).to_be_visible()
                    expect(page.get_by_text("Showing the last successful analysis while the latest attempt is not reviewable.", exact=True)).to_be_visible()
                    expect(requirement_row).to_be_visible()
                    page.get_by_role("tab", name="Overview", exact=True).click()
                    expect(page.get_by_role("button", name="Analysis is in progress.", exact=True)).to_be_visible()
                    page.get_by_role("tab", name="Requirements", exact=True).click()
                    expect(page.get_by_text("Analysis is in progress", exact=True)).to_be_visible()
                    controls["p1_running"] = False
                    controls["p1_failed"] = True
                    page.get_by_role("button", name="Refresh analysis", exact=True).click()
                    expect(page.get_by_text("Analysis failed.", exact=True)).to_be_visible()
                    expect(page.get_by_role("button", name="Retry analysis", exact=True)).to_be_visible()
                    expect(page.get_by_text("Showing the last successful analysis while the latest attempt is not reviewable.", exact=True)).to_be_visible()
                    expect(page.locator(".analysis-requirement-card").filter(has_text="At least three similar contracts").first).to_be_visible()
                    assert page.get_by_text("Synthetic fixture failure", exact=True).count() == 0
                    return {"running_nonblocking":True,"failure_retry":True,"previous_success_retained":True,"failure_details_hidden":True}
                finally:
                    controls["p1_running"] = False
                    controls["p1_failed"] = False
            case("p1/async-analysis-running-failed-retention", p1_async_analysis_states)
            def p0_extraction_trust_gate():
                controls["p0_attention"] = True
                controls["p0_context_conflict"] = True
                try:
                    load("pursuits/73000000-0000-4000-8000-000000000010?organization_id=73000000-0000-4000-8000-000000000001", "en", 390)
                    expect(page.get_by_role("button", name="Analysis needs attention — review or rerun.", exact=True)).to_be_visible()
                    expect(page.get_by_text("Source conflicts need review", exact=True)).to_be_visible()
                    expect(page.get_by_text("Town of University Park", exact=True)).to_be_visible()
                    expect(page.locator(".pursuit-historical-deadline")).to_contain_text("Historical RFP · deadline passed")
                    page.get_by_role("tab", name="Requirements", exact=True).click()
                    expect(page.locator('.analysis-stale[role="alert"] strong').filter(has_text="Analysis needs attention")).to_be_visible()
                    assert page.get_by_text("No current items need attention.", exact=True).count() == 0
                    expect(page.get_by_role("button", name="Rerun analysis", exact=True)).to_be_visible()
                    return {"quality_gate":True,"false_no_gaps_absent":True,"context_conflict":True,"next_action_authoritative":True}
                finally:
                    controls["p0_attention"] = False
                    controls["p0_context_conflict"] = False
            case("p0/extraction-trust-gate", p0_extraction_trust_gate)
            def w5_team_candidates():
                controls["w5"] = True
                controls["candidate_search_created"] = False
                try:
                    before = len(requests)
                    load("pursuits/73000000-0000-4000-8000-000000000010?organization_id=73000000-0000-4000-8000-000000000001", "en", 390)
                    page.get_by_role("tab", name="Team", exact=True).click()
                    assert not any(method == "POST" and path.split("?")[0].endswith("/candidate-search-runs") for method,path in requests[before:])
                    expect(page.get_by_text("Partners", exact=True)).to_be_visible()
                    expect(page.get_by_text("Experts", exact=True)).to_be_visible()
                    expect(page.get_by_role("link", name="Open Partners & Experts library", exact=True)).to_be_visible()
                    buttons = page.get_by_role("button", name="Find candidates", exact=True)
                    assert buttons.count() == 2
                    before_search = len(requests)
                    buttons.first.click()
                    expect(page.get_by_text("Aqua Advisory", exact=True)).to_be_visible(timeout=15000)
                    expect(page.get_by_text("Regional water network · Jv member · Completed · Verified", exact=True)).to_be_visible()
                    assert any(method == "POST" and path.split("?")[0].endswith("/candidate-search-runs") for method,path in requests[before_search:])
                    body = page.locator("body").inner_text()
                    for forbidden in ("Availability", "Commitment", "TeamScenario"):
                        assert forbidden not in body
                    return {"explicit_search":True,"candidate":"Aqua Advisory","external_requests":len(external)}
                finally:
                    controls["w5"] = False
                    controls["candidate_search_created"] = False
            case("w5/team-candidate-retrieval", w5_team_candidates)
            def w6_participation_history():
                controls["w5"] = True
                controls["w6"] = True
                controls["candidate_search_created"] = True
                controls["participation_created"] = False
                controls["availability_created"] = False
                try:
                    load("pursuits/73000000-0000-4000-8000-000000000010?organization_id=73000000-0000-4000-8000-000000000001", "en", 390)
                    page.get_by_role("tab", name="Team", exact=True).click()
                    start_tracking = page.get_by_role("button", name="Start participation tracking", exact=True)
                    expect(start_tracking).to_be_visible()
                    expect(start_tracking).to_be_enabled(timeout=15000)
                    before = len(requests)
                    start_tracking.click()
                    expect(page.get_by_text("AVAILABILITY", exact=True)).to_be_visible(timeout=15000)
                    expect(page.get_by_text("INTEREST", exact=True)).to_be_visible()
                    expect(page.get_by_text("PARTICIPATION", exact=True)).to_be_visible()
                    assert any(path.split("?")[0].endswith("/participation-record") for method,path in requests[before:] if method == "POST")
                    action = page.locator("details.participation-action").filter(has_text="Record availability")
                    action.locator("summary").click()
                    action.locator("select").first.select_option("AVAILABLE")
                    before_fact = len(requests)
                    action.get_by_role("button", name="Record availability", exact=True).click()
                    expect(page.get_by_text("Available", exact=True).first).to_be_visible(timeout=15000)
                    assert any(path.split("?")[0].endswith("/availability-facts") for method,path in requests[before_fact:] if method == "POST")
                    expect(page.get_by_text("Participation history", exact=False)).to_be_visible()
                    body = page.locator("body").inner_text()
                    for forbidden in ("Send invitation", "Send email", "TeamScenario"):
                        assert forbidden not in body
                    return {"shortlist_bound":True,"availability_recorded":True,"outbound":False}
                finally:
                    controls["w5"] = False
                    controls["w6"] = False
                    controls["candidate_search_created"] = False
                    controls["participation_created"] = False
                    controls["availability_created"] = False
            case("w6/participation-history", w6_participation_history)
            def w7_team_scenarios():
                controls["w5"] = True
                controls["w6"] = True
                controls["w7"] = True
                controls["candidate_search_created"] = True
                controls["participation_created"] = True
                controls["scenario_titles"] = []
                try:
                    load("pursuits/73000000-0000-4000-8000-000000000010?organization_id=73000000-0000-4000-8000-000000000001", "en", 390)
                    page.get_by_role("tab", name="Team", exact=True).click()
                    expect(page.get_by_text("Team options", exact=True)).to_be_visible()
                    name = page.get_by_label("Team option name")
                    selection = page.locator(".scenario-create input[type=checkbox]").first
                    name.fill("Delivery team A")
                    selection.check()
                    before = len(requests)
                    page.get_by_role("button", name="Create team option", exact=True).click()
                    expect(page.get_by_text("Delivery team A", exact=True)).to_be_visible(timeout=15000)
                    expect(page.get_by_text("Needs review", exact=True).first).to_be_visible()
                    expect(page.get_by_text("Partner Firms", exact=True).first).to_be_visible()
                    expect(page.get_by_text("Structured issues", exact=False).first).to_be_visible()
                    assert any(method == "POST" and path.split("?")[0].endswith("/team-scenarios") for method,path in requests[before:])
                    name.fill("Delivery team B")
                    page.get_by_role("button", name="Create team option", exact=True).click()
                    expect(page.get_by_text("Team option comparison", exact=True)).to_be_visible(timeout=15000)
                    body = page.locator("body").inner_text()
                    for forbidden in ("Best team", "Win probability", "Send invitation"):
                        assert forbidden not in body
                    return {"alternatives":2,"comparison":True,"outbound":False}
                finally:
                    controls["w5"] = False
                    controls["w6"] = False
                    controls["w7"] = False
                    controls["candidate_search_created"] = False
                    controls["participation_created"] = False
                    controls["scenario_titles"] = []
            case("w7/team-scenarios", w7_team_scenarios)
            def w8_proposal_evidence_pack():
                controls["w5"] = True
                controls["w6"] = True
                controls["w8"] = True
                controls["candidate_search_created"] = True
                controls["participation_created"] = True
                controls["w8_pack_created"] = False
                controls["w8_seal_payload"] = None
                try:
                    load("pursuits/73000000-0000-4000-8000-000000000010?organization_id=73000000-0000-4000-8000-000000000001", "en", 390)
                    page.get_by_role("tab", name="Proposal", exact=True).click()
                    proposal_title = page.get_by_text("Proposal preparation", exact=True).first
                    try:
                        expect(proposal_title).to_be_visible(timeout=15000)
                    except AssertionError as error:
                        raise AssertionError(f"{error}\nRendered body:\n{page.locator('body').inner_text()[-4000:]}") from error
                    approved_select = page.locator(".proposal-seal-card select")
                    expect(approved_select).to_be_visible(timeout=15000)
                    expect(approved_select).to_have_value(
                        "73000000-0000-4000-8000-000000000078:73000000-0000-4000-8001-000000000078",
                        timeout=15000,
                    )
                    confirmation = page.locator(".proposal-seal-card input[type=checkbox]")
                    confirmation.check()
                    expect(confirmation).to_be_checked(timeout=15000)
                    seal_button = page.get_by_role("button", name="Create evidence pack", exact=True)
                    expect(seal_button).to_be_enabled(timeout=15000)
                    before = len(requests)
                    seal_button.click()
                    try:
                        expect(page.get_by_text("Evidence pack 1", exact=True)).to_be_visible(timeout=15000)
                    except AssertionError:
                        # The POST can commit before a heavily loaded local Next.js
                        # proxy finishes the component's follow-up refresh. Reloading
                        # proves the persisted projection without repeating the write.
                        load("pursuits/73000000-0000-4000-8000-000000000010?organization_id=73000000-0000-4000-8000-000000000001", "en", 390)
                        page.get_by_role("tab", name="Proposal", exact=True).click()
                        expect(page.get_by_text("Evidence pack 1", exact=True)).to_be_visible(timeout=15000)
                    expect(page.get_by_text("At least three similar contracts", exact=True).first).to_be_visible()
                    expect(page.get_by_text("Aqua Advisory", exact=True).first).to_be_visible()
                    expect(page.get_by_text("Obtain power of attorney before submission", exact=True)).to_be_visible()
                    page.get_by_text("Required forms and artifacts (1)", exact=True).click()
                    expect(page.get_by_text("Signed technical proposal form", exact=True)).to_be_visible()
                    for label in ("Generate PDF", "Generate DOCX", "Evidence manifest"):
                        expect(page.get_by_role("button", name=label, exact=True)).to_be_visible()
                    assert any(method == "POST" and path.split("?")[0].endswith("/proposal-evidence-packs") for method,path in requests[before:])
                    payload = controls["w8_seal_payload"]
                    assert payload == {
                        "scenario_id":"73000000-0000-4000-8000-000000000078",
                        "revision_id":"73000000-0000-4000-8001-000000000078",
                        "approval_decision_id":"73000000-0000-4000-8006-000000000078",
                    }, payload
                    body = page.locator("body").inner_text()
                    for forbidden in ("Our price", "AI price", "Submit tender", "Win probability"):
                        assert forbidden not in body
                    return {"explicit_seal":True,"manifest":"e"*64,"price_free":True,"exports":["PDF","DOCX","JSON"]}
                finally:
                    controls["w5"] = False
                    controls["w6"] = False
                    controls["w8"] = False
                    controls["candidate_search_created"] = False
                    controls["participation_created"] = False
                    controls["w8_pack_created"] = False
                    controls["w8_seal_payload"] = None
            case("w8/proposal-evidence-pack", w8_proposal_evidence_pack)
            controls["outage"] = False
            for name,path in surfaces + [("details","tenders/s72-tender"),("compliance","tenders/s72-tender/compliance"),("readiness","readiness-vault"),("settings","settings")]:
                case(f"production-passivity/{name}", lambda path=path: load(path,"en",390))
            # D1-07: six destinations; Bid Preparation, Readiness Vault and Uploaded Tenders are routes, not menu items.
            for name,path in [("opportunities","tenders"),("pursuits","my-tenders"),("partners-experts","partners-experts"),("company","settings"),("notifications","notifications")]:
                def navigate(path=path):
                    load("settings","en",390)
                    before = len(requests)
                    page.get_by_role("button", name="Open navigation", exact=True).click()
                    page.locator(f'dialog[open] a[href="/dashboard/{path.split("?")[0]}"]').first.click()
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(300)
                    counts = Counter(str(item) for item in requests[before:])
                    assert "pending-approval" not in page.url
                    return dict(counts)
                case(f"production-client-navigation/{name}", navigate)
            navigation_keys = ["dashboard", "opportunities", "pursuits", "partnersExperts", "companyExperience", "notifications"]
            navigation_hrefs = ["/dashboard", "/dashboard/tenders", "/dashboard/my-tenders", "/dashboard/partners-experts", "/dashboard/settings", "/dashboard/notifications"]
            def messages(locale, name):
                return json.loads((FRONT / "messages" / locale / f"{name}.json").read_text(encoding="utf-8"))
            def shell_navigation(width):
                if page.locator("aside.shell-sidebar").is_visible():
                    return page.locator("aside.shell-sidebar nav.shell-navigation")
                page.locator(".shell-mobile-trigger").click()
                return page.locator("dialog[open] nav.shell-navigation")
            for locale in ("en", "ru", "uz", "ar"):
                for width in (1440, 390):
                    def d107_navigation(locale=locale, width=width):
                        labels = [messages(locale, "navigation")[key] for key in navigation_keys]
                        segments = messages(locale, "pursuits")["segments"]
                        load("my-tenders", locale, width)
                        assert page.locator("h1").first.inner_text().strip() == labels[2]
                        assert page.locator('.pursuit-segments a[aria-current="page"]').inner_text().strip() == segments["fromSources"]
                        nav = shell_navigation(width)
                        assert [text.strip() for text in nav.locator("a.shell-nav-link").all_inner_texts()] == labels
                        assert nav.locator("a.shell-nav-link").evaluate_all("els => els.map(e => e.getAttribute('href'))") == navigation_hrefs
                        assert nav.locator('a[aria-current="page"]').inner_text().strip() == labels[2]
                        assert nav.locator('a[href*="bid-preparation"], a[href*="readiness-vault"], a[href*="uploaded-tenders"]').count() == 0
                        if width <= 390:
                            page.screenshot(path=str(OUT / f"{locale}-d107-navigation-{width}.png"))
                        load("uploaded-tenders", locale, width)
                        assert page.locator('.pursuit-segments a[aria-current="page"]').inner_text().strip() == segments["uploaded"]
                        assert shell_navigation(width).locator('a[aria-current="page"]').inner_text().strip() == labels[2]
                        assert page.locator(".shell-upload-action").count() == 1  # persistent Upload Tender
                        return {"labels": labels, "active": labels[2]}
                    case(f"d1-07/navigation/{locale}/{width}", d107_navigation)
            def d106_one_door():
                controls["source_pursuit_created"] = False
                load("tenders?view=all", "en", 1440)  # load() proves the render issued GETs only
                before = len(requests)
                card = page.locator(".explorer-card").first
                expect(card.locator("[data-open-workspace] button")).to_have_text("Open workspace")
                card.locator("[data-open-workspace] button").click()
                page.wait_for_url(f"**/dashboard/pursuits/{SOURCE_PURSUIT_ID}?organization_id={ORGANIZATION_ID}")
                page.wait_for_load_state("networkidle")
                posts = [path for method, path in requests[before:] if method == "POST"]
                assert posts == ["/api/v1/pursuits/source"], posts
                assert ("GET", "/api/v1/organizations") in requests[before:]
                page.get_by_role("tab", name="Requirements", exact=True).click()
                boxes = page.locator(".analysis-candidate-row input[type=checkbox]")
                expect(boxes).to_have_count(2)
                # The OFFICIAL_NOTICE is pre-selected; the other source document is not.
                assert [boxes.nth(index).is_checked() for index in range(2)] == [False, True]
                assert page.locator(".analysis-pack-actions select").input_value() == "en"
                assert not any(method == "POST" and "/analysis-runs" in path for method, path in requests[before:])
                expect(page.get_by_role("button", name="Analyze selected", exact=True)).to_be_enabled()
                # A second click on the same tender resolves the existing pursuit (no duplicate).
                load("tenders?view=all", "en", 1440)
                again = len(requests)
                page.locator(".explorer-card").first.locator("[data-open-workspace] button").click()
                page.wait_for_url(f"**/dashboard/pursuits/{SOURCE_PURSUIT_ID}?organization_id={ORGANIZATION_ID}")
                assert [path for method, path in requests[again:] if method == "POST"] == ["/api/v1/pursuits/source"]
                return {"post_on_render": 0, "post_on_click": 1, "notice_preselected": True, "language": "en"}
            case("d1-06/one-door/source-tender-to-workspace", d106_one_door)
            def d106_language_follows_locale():
                values = {}
                for locale in ("ru", "uz", "ar"):
                    load(f"pursuits/{SOURCE_PURSUIT_ID}?organization_id={ORGANIZATION_ID}", locale, 1440)
                    page.locator("#pursuit-tab-requirements").click()
                    expect(page.locator(".analysis-pack-actions select")).to_be_visible()
                    values[locale] = page.locator(".analysis-pack-actions select").input_value()
                assert values == {"ru": "ru", "uz": "uz", "ar": "en"}, values
                return values
            case("d1-06/analysis-language-defaults-to-ui-locale", d106_language_follows_locale)
            def d108_no_score():
                evidence = {}
                for locale in ("en", "ru"):
                    load("tenders?view=all", locale, 1440)
                    text = page.locator("#customer-main").inner_text()
                    assert "88" not in text and "/100" not in text and "Generated rationale" not in text, text[:400]
                    facts = messages(locale, "explorer")["facts"]
                    chips = page.locator(".explorer-card .fact-chip")
                    kinds = chips.evaluate_all("els => els.map(e => e.dataset.fact)")
                    assert kinds == ["country", "service", "notice-type", "days-left"], kinds
                    assert chips.nth(0).inner_text().strip() == facts["countryMatch"].replace("{country}", "Uzbekistan")
                    assert chips.nth(2).inner_text().strip() == facts["noticeType"]["eoi"]
                    tabs = [item.strip() for item in page.get_by_role("tab").all_inner_texts()]
                    assert any(messages(locale, "explorer")["matches"]["tab"] in item for item in tabs), tabs
                    # All | Matches your profile: the dismissed-recommendations view is not offered.
                    assert not any(messages(locale, "explorer")["views"]["dismissed"] in item for item in tabs), tabs
                    evidence[locale] = kinds
                return evidence
            case("d1-08/no-score-fact-chips", d108_no_score)
            def d202_writes(since):
                return [(method, path.split("?")[0]) for method, path in requests[since:]
                        if method != "GET" and path != "/api/v1/auth/refresh"]
            def d202_own_first_save():
                controls.update(d202=True, d202_self_firm=None)
                load("partners-experts?tab=own", "en", 1440)
                library = messages("en", "pursuits")["library"]
                assert page.get_by_role("tab", name=library["tabs"]["own"], exact=True).get_attribute("aria-selected") == "true"
                expect(page.get_by_text(library["own"]["emptyTitle"], exact=True)).to_be_visible()
                before = len(requests)
                page.locator('[data-add-reference="own"]').click()
                form = page.locator("#library-reference-form")
                expect(form).to_be_visible()
                assert d202_writes(before) == []  # opening the form writes nothing
                form.locator('[name="project_name"]').fill("Navoi substation design")
                form.locator('[name="client_name"]').fill("Regional grid company")
                form.locator('[name="country"]').fill("Uzbekistan")
                form.locator('[name="sector"]').fill("Energy")
                form.locator('[name="service"]').fill("Detailed design")
                form.locator('[name="contract_value"]').fill("250000")
                page.locator('button[form="library-reference-form"]').click()
                # Client-side: a value needs its currency and its basis; nothing is sent.
                expect(form.locator(".ds-field-error").first).to_be_visible()
                assert d202_writes(before) == []
                form.locator('[name="contract_currency"]').fill("USD")
                form.locator('[name="value_basis"]').select_option("CONTRACT_TOTAL")
                form.locator('[name="start_date"]').fill("2021-03-01")
                form.locator('[name="completion_date"]').fill("2022-11-30")
                form.screenshot(path=str(OUT / "en-d202-reference-form-1440.png"))
                page.locator('button[form="library-reference-form"]').click()
                expect(page.locator(".library-reference")).to_have_count(1)
                writes = d202_writes(before)
                assert writes == [("PUT", "/api/v1/candidates/self-firm"),
                                  ("POST", f"/api/v1/candidates/firms/{D202_SELF_FIRM_ID}/project-references")], writes
                expect(page.locator(".library-reference h4")).to_have_text("Navoi substation design")
                return {"writes": writes}
            case("d2-02/library/own-first-save", d202_own_first_save)
            for locale in ("en", "ru"):
                for width in (1440, 390):
                    def d202_tabs(locale=locale, width=width):
                        controls.update(d202=True)
                        library = messages(locale, "pursuits")["library"]
                        load("partners-experts", locale, width)
                        before = len(requests)
                        names = [library["tabs"][key] for key in ("own", "partners", "experts")]
                        assert [text.strip() for text in page.get_by_role("tab").all_inner_texts()] == names
                        page.screenshot(path=str(OUT / f"{locale}-d202-library-own-{width}.png"), full_page=True)
                        page.get_by_role("tab", name=names[1], exact=True).click()
                        page.wait_for_url("**tab=partners")
                        expect(page.locator('[data-firm-id] .library-reference')).to_have_count(1)
                        page.screenshot(path=str(OUT / f"{locale}-d202-library-partners-{width}.png"), full_page=True)
                        page.get_by_role("tab", name=names[2], exact=True).click()
                        page.wait_for_url("**tab=experts")
                        versions = page.locator("[data-cv-version]").evaluate_all("els => els.map(e => e.dataset.cvVersion)")
                        assert versions == ["2", "1"], versions  # newest first
                        page.screenshot(path=str(OUT / f"{locale}-d202-library-experts-{width}.png"), full_page=True)
                        assert d202_writes(before) == []
                        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
                        return {"tabs": names, "cv_versions": versions}
                    case(f"d2-02/library/tabs/{locale}/{width}", d202_tabs)
            def d202_csv_preview():
                controls.update(d202=True)
                if controls["d202_self_firm"] is None:
                    controls["d202_self_firm"] = d202_firm(D202_SELF_FIRM_ID, "Synthetic Organization", [], is_self_firm=True)
                load("partners-experts?tab=own", "en", 1440)
                library = messages("en", "pursuits")["library"]
                page.get_by_role("button", name=library["import"]["open"], exact=True).first.click()
                dialog = page.locator("dialog[open]")
                columns = "project_name,client_name,country,sector,service,role,contract_share_percent,contract_value,contract_currency,value_basis,start_date,completion_date,completion_state,relevant_scope,evidence_state"
                content = "\n".join([
                    columns,
                    "CSV substation A,Grid,Uzbekistan,Energy,Design,LEAD,,,,,2020-01-01,2021-01-01,COMPLETED,,",
                    "CSV value without currency,Grid,,,,LEAD,,5000,,,,,COMPLETED,,",
                    "CSV substation B,Grid,Uzbekistan,Energy,Design,LEAD,,,,,2021-01-01,2022-01-01,COMPLETED,,",
                ])
                dialog.locator("[data-import-file]").set_input_files(files=[{"name": "refs.csv", "mimeType": "text/csv", "buffer": content.encode()}])
                expect(dialog.locator("[data-import-summary]")).to_have_text(library["import"]["summary"].replace("{valid}", "2").replace("{invalid}", "1"))
                assert dialog.locator("[data-import-row]").evaluate_all("els => els.map(e => e.dataset.valid)") == ["true", "false", "true"]
                dialog.screenshot(path=str(OUT / "en-d202-csv-preview-1440.png"))
                before = len(requests)
                dialog.locator("[data-import-start]").click()
                expect(dialog.get_by_text("Created: 2. Failed: 0. Not imported because of errors: 1.", exact=True)).to_be_visible()
                posts = [path for method, path in d202_writes(before)]
                assert posts == [f"/api/v1/candidates/firms/{D202_SELF_FIRM_ID}/project-references"] * 2, posts
                return {"posted": len(posts), "skipped": 1}
            case("d2-02/library/csv-preview", d202_csv_preview)
            def d202_dashboard():
                evidence = {}
                for locale in ("en", "ru"):
                    s72.State.users["s72-token-a"]["ui_locale"] = locale
                    page.set_viewport_size({"width": 1440, "height": 900})
                    dashboard_start = len(requests)
                    response = page.goto(BASE + "/dashboard", wait_until="networkidle")
                    assert response is not None and response.status == 200, page.url
                    expect(page.locator("[data-page='dashboard']")).to_be_visible(timeout=30000)
                    dashboard = messages(locale, "dashboard")
                    assert page.locator(".dashboard-attention, .dashboard-analyses").count() == 0
                    expect(page.locator("[data-dashboard-pursuits]")).to_be_visible()
                    expect(page.locator("[data-dashboard-pursuits] h2")).to_have_text(dashboard["pursuitsTitle"])
                    href = page.locator("[data-dashboard-pursuits] a[href*='/dashboard/pursuits/']").first.get_attribute("href")
                    assert href.endswith(f"?organization_id={ORGANIZATION_ID}"), href
                    assert page.locator("[data-company-link]").get_attribute("href") == "/dashboard/settings"
                    assert page.locator('a[href="/dashboard/readiness-vault"]').count() == 0
                    assert not any("latest-analysis" in path for _, path in requests[dashboard_start:])  # this page only
                    assert page.get_by_role("link", name=dashboard["openExplorer"]).count() >= 1
                    evidence[locale] = href
                return evidence
            case("d2-02/dashboard/pursuits-no-legacy-widgets", d202_dashboard)
            def d202_tender_details():
                card_states = {}
                for analysed in (False, True):
                    controls["d202_analysis"] = analysed
                    try:
                        load("tenders/s72-tender", "en", 1440)
                        card = page.locator("[data-analysis-card]")
                        expect(card).to_be_visible()
                        state = "ready" if analysed else "none"
                        expect(card.locator(f'[data-analysis-state="{state}"]')).to_be_visible()
                        card_states[state] = card.inner_text()
                    finally:
                        controls["d202_analysis"] = False
                assert page.locator("#bid-preparation, #s143-compliance-title").count() == 0
                assert page.locator('a[href="/dashboard/readiness-vault"]').count() == 0
                assert page.locator(".s143-utility-actions [data-open-workspace] .ds-button-primary").count() == 1
                # Stage actions are secondary (a closed confirmation dialog may hold a hidden primary).
                assert page.locator(".s143-decision-grid .ds-button-primary:visible").count() == 0
                return {"states": list(card_states)}
            case("d2-02/tender-details/analysis-card", d202_tender_details)
            controls.update(d202=False, d202_analysis=False)
            def d205_setup():
                controls.update(d202=True, d205=True, d205_posts=[], d205_reviews=[],
                                d205_drafts=[d205_draft(1, "en", False, ["REFERENCE_SUPERSEDED", "NEWER_ANALYSIS_RUN"])])
                controls["d202_self_firm"] = d202_firm(D202_SELF_FIRM_ID, "Synthetic Organization", [
                    d202_reference(D205_OWN_REF, D202_SELF_FIRM_ID, "Navoi substation design")], is_self_firm=True)
            workspace = f"pursuits/{SOURCE_PURSUIT_ID}?organization_id={ORGANIZATION_ID}"
            for locale in ("en", "ru"):
                for width in (1440, 390):
                    def d205_builder(locale=locale, width=width):
                        d205_setup()
                        eoi = messages(locale, "pursuits")["eoi"]
                        load(f"{workspace}&tab=eoi", locale, width)
                        before = len(requests)
                        expect(page.locator("[data-eoi-panel='experience']")).to_be_visible(timeout=30000)
                        expect(page.locator(f"[data-criterion-id='{D205_REQ_LATER}']")).to_have_count(0)  # later-stage: never a criterion
                        expect(page.locator("[data-criterion-id]")).to_have_count(2)
                        pursuits_messages = messages(locale, "pursuits")
                        stage = page.locator("[data-pursuit-stage]")
                        expect(stage).to_have_attribute("data-pursuit-stage", "SAVED")
                        expect(stage).to_have_text(pursuits_messages["stages"]["SAVED"])
                        header = page.locator(".ds-page-header").first.inner_text()
                        assert pursuits_messages["processing"]["CHECKING"] not in header, header
                        experience = page.locator(f"[data-criterion-id='{D205_REQ_EXPERIENCE}']")
                        expect(experience).to_have_attribute("data-addressed", "true")
                        assert page.locator(f"[data-reference-id='{D205_OWN_REF}'] input").is_checked()  # suggested: pre-checked
                        assert not page.locator(f"[data-reference-id='{D205_OWN_REF_2}'] input").is_checked()
                        page.screenshot(path=str(OUT / f"{locale}-d205-eoi-experience-{width}.png"), full_page=True)
                        page.locator(f"[data-reference-id='{D205_OWN_REF}'] input").uncheck()
                        expect(experience).to_have_attribute("data-addressed", "false")  # live, client-side
                        page.locator(f"[data-reference-id='{D205_OWN_REF}'] input").check()
                        page.locator("[data-eoi-step='partners']").click()
                        page.locator(f"[data-partner-id='{D202_PARTNER_ID}'] input[type=checkbox]").first.check()
                        page.locator(f"[data-partner-id='{D202_PARTNER_ID}'] select").select_option("SUBCONSULTANT")
                        page.locator(f"[data-partner-id='{D202_PARTNER_ID}'] .eoi-partner-references input").check()
                        page.screenshot(path=str(OUT / f"{locale}-d205-eoi-partners-{width}.png"), full_page=True)
                        page.locator("[data-eoi-step='letter']").click()
                        assert page.locator("[name='addressee_organization']").input_value() == "Ministry of Energy, Mongolia"
                        page.locator("[name='signatory_name']").fill("Aziza Karimova")
                        page.locator("[name='signatory_title']").fill("Director")
                        page.locator("[name='contact_email']").fill("eoi@example.invalid")
                        page.screenshot(path=str(OUT / f"{locale}-d205-eoi-letter-{width}.png"), full_page=True)
                        assert d202_writes(before) == []  # building writes nothing
                        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
                        return {"steps": 3, "language": page.locator("[name='language']").input_value()}
                    case(f"d2-05/eoi/builder/{locale}/{width}", d205_builder)
            def d205_generate():
                d205_setup()
                load(f"{workspace}&tab=eoi", "en", 1440)
                before = len(requests)
                page.locator("[data-eoi-step='letter']").click()
                page.locator("[name='signatory_name']").fill("Aziza Karimova")
                page.locator("[name='signatory_title']").fill("Director")
                page.locator("[name='contact_email']").fill("eoi@example.invalid")
                page.locator("[data-eoi-generate]").click()
                expect(page.locator("[data-eoi-progress]")).to_be_visible()
                expect(page.locator("[data-eoi-version='2']")).to_be_visible(timeout=20000)
                body = controls["d205_posts"][-1]
                assert body["analysis_run_id"] == D205_RUN_ID and body["own_reference_ids"] == [D205_OWN_REF], body
                assert body["include_relevance_notes"] is True and body["language"] == "en" and body["partners"] == []
                assert set(body["letter"]) == {"addressee_organization", "addressee_name", "signatory_name", "signatory_title",
                                               "contact_email", "contact_phone", "contact_address"}
                writes = d202_writes(before)
                assert writes == [("POST", f"/api/v1/pursuits/{SOURCE_PURSUIT_ID}/eoi-drafts")], writes
                assert page.locator("[data-eoi-version='2']").get_attribute("data-current") == "true"
                stale = page.locator("[data-eoi-version='1']")
                assert stale.get_attribute("data-current") == "false"
                expect(stale.locator(".eoi-stale-reasons li")).to_have_count(2)
                with page.expect_download() as download:
                    page.locator("[data-eoi-version='1'] button", has_text="DOCX").click()
                assert download.value.suggested_filename == "eoi-OP00468882-server.docx"  # the server's name
                page.locator("[data-eoi-versions]").screenshot(path=str(OUT / "en-d205-eoi-versions-1440.png"))
                return {"versions": 2, "post": 1}
            case("d2-05/eoi/generate-progress-versions", d205_generate)
            for locale in ("en", "ru"):
                for width in (1440, 390):
                    def d205_requirements(locale=locale, width=width):
                        d205_setup()
                        review = messages(locale, "pursuits")["requirements"]["review"]
                        load(f"{workspace}&tab=requirements", locale, width)
                        groups = page.locator("[data-requirement-group]").evaluate_all("els => els.map(e => e.dataset.requirementGroup)")
                        assert groups == ["attention", "partial", "notes", "later"], groups
                        ids = page.locator("[data-requirement-id]").evaluate_all("els => els.map(e => e.dataset.requirementId)")
                        assert len(ids) == len(set(ids)) == 5, ids  # one list, no duplicates
                        card = page.locator(f"[data-requirement-id='{D205_REQ_LICENSE}']")
                        expect(card.locator(".analysis-quote")).to_be_visible()  # quote not behind a click
                        expect(card.locator("[data-locator]")).to_be_visible()
                        partial = page.locator(f"[data-requirement-id='{D205_REQ_EXPERIENCE}']")
                        expect(partial.locator("[data-matched-references]")).to_contain_text("Navoi substation design")
                        expect(partial.locator("[data-generated-interpretation]")).to_contain_text(review["generatedLabel"])
                        page.screenshot(path=str(OUT / f"{locale}-d205-requirements-{width}.png"), full_page=True)
                        if locale == "en" and width == 1440:
                            before = len(requests)
                            group = page.locator("[data-requirement-group='attention']")
                            group.locator("[data-bulk-confirm] button").first.click()
                            group.locator("[data-bulk-run]").click()
                            for _ in range(50):
                                if len(controls["d205_reviews"]) >= 2:
                                    break
                                page.wait_for_timeout(100)
                            expect(group.locator("[data-bulk-confirm]")).to_contain_text(review["bulkReport"].split("{")[0].strip()[:8])
                            reviews = controls["d205_reviews"]
                            assert [item["target_kind"] for item in reviews] == ["REQUIREMENT", "GAP"], reviews
                            assert reviews[0]["new_review_state"] == "CONFIRMED" and reviews[0]["reason"].startswith("Reviewed in bulk by")
                            assert len(d202_writes(before)) == 2
                        return {"groups": groups}
                    case(f"d2-05/requirements/grouped/{locale}/{width}", d205_requirements)
            controls.update(d202=False, d205=False)
            for name,path in [("proposals","bid-preparation"),("readiness","readiness-vault")]:
                def pagination(path=path):
                    controls["pagination"] = True
                    load(path,"en",390)
                    page.get_by_role("button",name="Next",exact=True).click()
                    page.wait_for_url("**page=2")
                    page.wait_for_load_state("networkidle")
                    expect(page.get_by_role("button",name="Previous",exact=True)).to_be_enabled()
                    expect(page.get_by_role("button",name="Next",exact=True)).to_be_disabled()
                    controls["pagination"] = False
                    return {"url":page.url}
                case(f"pagination/{name}", pagination)
            def document_viewer():
                load("tenders/s72-tender","en",390)
                before = len(requests)
                results = [page.evaluate("""async path=>{const r=await fetch(path);return {status:r.status,body:await r.json()};}""",path) for path in ('/api/documents/missing-fixture','/document-preview/missing-fixture')]
                assert all(result["status"] == 404 for result in results), results
                assert not external
                assert all(method == "GET" or path == "/api/v1/auth/refresh" for method,path in requests[before:])
                return {"status":404,"source_requests":0,"requests":dict(Counter(str(x) for x in requests[before:]))}
            case("production-passivity/document-viewer-missing",document_viewer)
            def locale_spoof():
                s72.State.users['s72-token-a']['ui_locale']='uz'
                context.set_extra_http_headers({'x-plasma-persisted-ui-locale':'ar'})
                try:
                    response = page.goto(BASE+'/dashboard/settings',wait_until='domcontentloaded')
                    assert response is not None and response.status == 200
                    expect(page.locator('h1').first).to_be_visible(timeout=30000)
                    assert page.locator('html').get_attribute('lang') == 'uz'
                finally: context.set_extra_http_headers({})
                return {'persisted_locale':'uz','spoofed_locale':'ar','result':'uz'}
            case('locale/spoofed-persisted-header',locale_spoof)
            def locale_isolation():
                load('settings','en',390)
                s72.State.users['s72-token-b']['ui_locale'] = 'ru'
                other = browser.new_context(viewport={'width':390,'height':844})
                other.route('**/*',network)
                other.add_cookies([
                    {'name':'__Secure-authjs.session-token','value':session_token('__Secure-authjs.session-token','s72-token-b'),'url':BASE.replace('http://','https://',1),'secure':True,'httpOnly':True,'sameSite':'Lax'},
                    {'name':'authjs.session-token','value':session_token('authjs.session-token','s72-token-b'),'url':BASE,'httpOnly':True,'sameSite':'Lax'},
                ])
                try:
                    other_page = other.new_page()
                    other_page.goto(BASE+'/dashboard/settings',wait_until='networkidle')
                    assert other_page.locator('html').get_attribute('lang') == 'ru'
                    assert page.locator('html').get_attribute('lang') == 'en'
                finally: other.close()
                return {'user_a':'en','user_b':'ru','isolated':True}
            case('locale/two-user-isolation',locale_isolation)
            def revoked():
                load('settings','en',390)
                controls['revoked'] = True
                try:
                    for attempt in range(3):
                        response = page.goto(BASE+'/dashboard/tenders',wait_until='networkidle')
                        if urlparse(page.url).path == '/' and response.status == 200:
                            break
                        if attempt < 2:
                            page.wait_for_timeout(300)
                    assert urlparse(page.url).path == '/' and response.status == 200, {
                        'url': page.url, 'status': response.status,
                    }
                finally: controls['revoked'] = False
                return {'next_navigation':'/','authorization_ttl':0}
            case('session/revocation-next-navigation',revoked)
            def expiry():
                context.clear_cookies()
                page.goto(BASE + "/dashboard/tenders", wait_until="networkidle")
                assert urlparse(page.url).path == "/"
                assert "/login" not in page.url
                return {"path":urlparse(page.url).path}
            case("session/expired-real-sign-in", expiry)

            # Real HTTP backend route/dependency execution driven from Chromium.
            # Only database persistence and Auth.js issuance are controlled fixtures.
            sys.path.insert(0, str(ROOT / "backend"))
            import uvicorn
            from fastapi import FastAPI
            from app.api.endpoints import auth, tenders
            from app.core import auth_bridge
            from app.core.config import settings
            from app.core.security import create_access_token, get_current_user as current_account
            from app.db.session import get_db
            from test_release_security import IdentityDB, synthetic_user, proof_payload, BRIDGE_SECRET
            db = IdentityDB(synthetic_user())
            api = FastAPI()
            api.include_router(auth.router,prefix="/auth")
            api.include_router(tenders.router,prefix="/tenders")
            api.dependency_overrides[get_db] = lambda: db
            @api.get("/health")
            async def health(): return {"fixture":True}
            # Browser multipart requests exercise the real upload route with bounded
            # synthetic parser/model outcomes. Authorization is covered above.
            from types import SimpleNamespace
            from uuid import uuid4
            from tempfile import TemporaryDirectory
            from app.api.endpoints import proposals
            from app.api.deps import (
                require_active_initial_membership,
                require_approved_pilot_access,
            )
            from app.core import uploads
            from app.core.http_hardening import HardenedHTTPMiddleware
            from test_release_uploads import permit
            upload_user = SimpleNamespace(id=uuid4(),company_name='Synthetic',core_services='',past_experience='')
            upload_proposal = SimpleNamespace(id=uuid4(),structured_data={'prior':'preserved'},ai_confidence_score=10,tender=SimpleNamespace(budget=1000))
            upload_db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda:upload_proposal)),commit=AsyncMock(),rollback=AsyncMock())
            upload_api = FastAPI()
            upload_api.add_middleware(HardenedHTTPMiddleware)
            upload_api.include_router(proposals.router,prefix='/api/v1/proposals')
            upload_api.dependency_overrides[get_db] = lambda: upload_db
            upload_api.dependency_overrides[current_account] = lambda: upload_user
            upload_api.dependency_overrides[require_approved_pilot_access] = lambda: upload_user
            upload_api.dependency_overrides[require_active_initial_membership] = lambda: upload_user
            api.mount('/upload-fixture',upload_api)
            api_server = uvicorn.Server(uvicorn.Config(api,host="127.0.0.1",port=8124,log_level="critical",access_log=False))
            threading.Thread(target=api_server.run,daemon=True).start()
            for _ in range(100):
                if api_server.started: break
                time.sleep(.05)
            page.goto("http://127.0.0.1:8124/health")
            def fetch(path, headers=None, body=None):
                return page.evaluate("""async ({path,headers,body})=>{const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',...headers},body:body?JSON.stringify(body):undefined});return {status:r.status,body:await r.json()};}""", {"path":path,"headers":headers or {},"body":body})
            for route in ("", "/00000000-0000-4000-8000-000000000001", "/00000000-0000-4000-8000-000000000001/details", "/00000000-0000-4000-8000-000000000001/documents", "/00000000-0000-4000-8000-000000000001/decision-snapshot"):
                for state,expected in (("anonymous",401),("invalid",401),("pending",403),("rejected",401),("disabled",401),("stale",401),("approved",200),("operator",200),("admin",200)):
                    def authority(route=route,state=state,expected=expected):
                        db.user = synthetic_user(state=state if state in {"pending","rejected","disabled"} else "approved",role=state if state in {"operator","admin"} else "pilot_user")
                        db.reads.clear()
                        bearer = create_access_token({"sub":str(db.user.id),"auth_version":2 if state == "stale" else 3})
                        headers = {} if state == "anonymous" else {"Authorization":"Bearer " + ("invalid" if state == "invalid" else bearer)}
                        result = fetch("/tenders" + route,headers)
                        assert result["status"] == (404 if expected == 200 and route else expected), result
                        if expected != 200: assert all("FROM tenders" not in query for query in db.reads)
                        return {"status":result["status"],"domain_writes":len(db.writes)}
                    case(f"backend-auth/{state}/{route or 'list'}",authority)
            consumed = set()
            async def consume(jti):
                if jti in consumed: return False
                consumed.add(jti)
                return True
            with patch.object(settings,"AUTH_BRIDGE_SECRET",BRIDGE_SECRET), patch.object(auth_bridge,"consume_assertion",consume):
                for attack in ("approved-no-proof","admin-no-proof","operator-no-proof","forged-subject","wrong-audience","wrong-issuer","expired","tampered","email-injection"):
                    def impersonation(attack=attack):
                        payload = proof_payload()
                        if attack.endswith('no-proof'): payload.bridge_assertion = None; payload.email = attack + '@example.invalid'
                        elif attack == 'forged-subject': payload.google_id = 'forged'
                        elif attack == 'wrong-audience': payload = proof_payload(aud='wrong')
                        elif attack == 'wrong-issuer': payload = proof_payload(iss='wrong')
                        elif attack == 'expired': payload = proof_payload(iat=int(time.time())-120,exp=int(time.time())-60)
                        elif attack == 'tampered': payload.bridge_assertion += 'tamper'
                        else: payload.email = 'admin@example.invalid'
                        db.reads.clear(); before = len(db.writes)
                        result = fetch('/auth/google',body=payload.model_dump())
                        assert result['status'] == 401 and not db.reads and len(db.writes) == before
                        return {'status':401,'domain_writes':0}
                    case('impersonation/'+attack,impersonation)
                for role in ('approved','operator','admin'):
                    def login(role=role):
                        db.user = synthetic_user(role=role if role != 'approved' else 'pilot_user')
                        result = fetch('/auth/google',body=proof_payload().model_dump())
                        assert result['status'] == 200 and result['body']['access_token']
                        return {'status':200,'role':result['body']['platform_role']}
                    case('verified-login/'+role,login)
                def replay():
                    db.user = synthetic_user()
                    payload = proof_payload().model_dump()
                    assert fetch('/auth/google',body=payload)['status'] == 200
                    db.user.approval_status = 'disabled'
                    db.user.auth_version += 1
                    assert fetch('/auth/google',body=payload)['status'] == 401
                    db.user.approval_status = 'approved'
                    assert fetch('/auth/google',body=payload)['status'] == 401
                    return {'disabled_replay':401,'restored_replay':401}
                case('session/bridge-replay-after-disable-and-restore',replay)
            context.clear_cookies()  # Upload fixture uses isolated authority; no bridge cookie crosses this boundary.
            for outcome,expected in [('valid',200),('extension',415),('signature',415),('parse',422),('model',502)]:
                def multipart(outcome=outcome,expected=expected):
                    from fastapi import HTTPException
                    upload_proposal.structured_data = {'prior':'preserved'}
                    upload_proposal.ai_confidence_score = 10
                    upload_db.commit.reset_mock()
                    parser = AsyncMock(return_value='Synthetic parsed requirements')
                    model = AsyncMock(return_value={'summary':'Synthetic summary','items':[],'delivery_days':30})
                    if outcome == 'parse': parser.side_effect=HTTPException(422,'PDF could not be parsed')
                    if outcome == 'model': model.side_effect=RuntimeError('SECRET_SENTINEL CUSTOMER_TEXT_SENTINEL')
                    with TemporaryDirectory(prefix='plasma-browser-upload-') as temporary, ExitStack() as mocks:
                        mocks.enter_context(patch.object(proposals,'__file__',str(Path(temporary)/'app/api/endpoints/proposals.py')))
                        mocks.enter_context(patch.object(uploads,'upload_permit',permit))
                        mocks.enter_context(patch.object(uploads,'parse_uploaded_pdf',parser))
                        mocks.enter_context(patch.object(uploads,'analyze_uploaded_pdf',model))
                        page.evaluate("""()=>{document.body.innerHTML='<input type="file" id="upload-fixture">';}""")
                        page.locator('#upload-fixture').set_input_files({'name':'source.txt' if outcome=='extension' else '../../source.pdf','mimeType':'application/pdf','buffer':b'not-pdf' if outcome=='signature' else b'%PDF-1.4 synthetic'})
                        result=page.evaluate("""async path=>{const form=new FormData();form.append('file',document.querySelector('input').files[0]);const r=await fetch(path,{method:'POST',body:form});return {status:r.status,body:await r.text()};}""", '/upload-fixture/api/v1/proposals/'+str(upload_proposal.id)+'/upload-tz')
                        assert result['status']==expected,result
                        assert 'SENTINEL' not in result['body']
                        if outcome!='valid':
                            assert upload_proposal.structured_data=={'prior':'preserved'}
                            upload_db.commit.assert_not_awaited()
                            assert not list(Path(temporary).rglob('*.pdf'))
                        if outcome in {'extension','signature','parse'}: model.assert_not_awaited()
                        assert not list(Path(temporary).rglob('upload-*.pdf'))
                    return {'status':expected,'commits':upload_db.commit.await_count,'temporary_files_cleaned':True}
                case('upload/browser-multipart/'+outcome,multipart)
            browser.close()
    finally:
        if api_server: api_server.should_exit = True
        if os.name == 'posix':
            try: os.killpg(proc.pid,signal.SIGTERM)
            except ProcessLookupError: pass
            powershell = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
            if powershell.exists() and not os.environ.get("PLASMA_BROWSER_EXTERNAL_SERVER"):
                subprocess.run([
                    str(powershell), "-NoProfile", "-Command",
                    f"Stop-Process -Id (Get-NetTCPConnection -LocalPort {BROWSER_PORT} -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique) -Force -ErrorAction SilentlyContinue",
                ], check=False, capture_output=True)
        else:
            # npm.cmd launches a child Next.js process on Windows. Terminating
            # only the wrapper leaves the release port and native modules
            # locked, so stop the synthetic test process tree explicitly.
            if not os.environ.get("PLASMA_BROWSER_EXTERNAL_SERVER"):
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    check=False,
                    capture_output=True,
                )
                subprocess.run([
                    "powershell.exe", "-NoProfile", "-Command",
                    f"Stop-Process -Id (Get-NetTCPConnection -LocalPort {BROWSER_PORT} -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique) -Force -ErrorAction SilentlyContinue",
                ], check=False, capture_output=True)
        proc.wait(timeout=20)
        server.shutdown(); server.server_close(); log.close()
        result = {"method":"Real Chromium against local production Next.js and controlled HTTP API fixtures; backend security cases execute real route/dependency code with synthetic DB and signed assertion fixtures", "cases":rows,"external_requests":external,
                  "passed":sum(row['status']=='PASS' for row in rows),"failed":sum(row['status']=='FAIL' for row in rows)}
        (OUT/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False), encoding='utf-8')
    return 0 if len(rows) >= 100 and all(row['status']=='PASS' for row in rows) and not external else 1


if __name__ == '__main__':
    raise SystemExit(main())
