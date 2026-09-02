"""Static P0 security regression checks.

These tests intentionally avoid importing the FastAPI app so they can run in a
minimal environment where backend dependencies are not installed.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def function_block(source: str, name: str) -> str:
    start = source.index(f"async def {name}")
    next_route = source.find("\n\n@", start + 1)
    if next_route == -1:
        return source[start:]
    return source[start:next_route]


class P0SecurityStaticTests(unittest.TestCase):
    def test_default_tender_response_excludes_compiled_text(self) -> None:
        schema = read("app/schemas/tender.py")
        tender_response = schema.split("class TenderDocumentResponse", 1)[0]

        self.assertIn("class TenderResponse", tender_response)
        self.assertNotIn("compiled_master_text", tender_response)
        self.assertNotIn("source_metadata_json", tender_response)
        self.assertNotIn("scrape_status", tender_response)
        self.assertNotIn("last_synced_at", tender_response)

    def test_document_response_excludes_raw_document_sources(self) -> None:
        schema = read("app/schemas/tender.py")
        document_response = schema.split("class TenderDocumentResponse", 1)[1]

        self.assertNotIn("file_url:", document_response)
        self.assertNotIn("source_document_url", document_response)
        self.assertNotIn("storage_path", document_response)
        self.assertNotIn("parsed_text", document_response)
        self.assertIn("download_url", document_response)
        self.assertIn("download_status", document_response)

    def test_tender_response_has_safe_int4_summary_fields_only(self) -> None:
        schema = read("app/schemas/tender.py")
        tender_response = schema.split("class TenderDocumentResponse", 1)[0]

        for field in (
            "price_amount",
            "price_currency",
            "price_display",
            "has_compiled_text",
            "document_status",
            "document_count",
            "available_document_count",
            "metadata_only_document_count",
            "failed_document_count",
            "compliance_analysis_available",
            "compliance_unavailable_reason",
        ):
            self.assertIn(field, tender_response)

        self.assertNotIn("compiled_master_text:", tender_response)
        self.assertNotIn("parsed_text:", tender_response)
        self.assertNotIn("storage_path:", tender_response)
        self.assertNotIn("source_document_url", tender_response)

    def test_tender_price_fields_are_derived_from_stored_budget_safely(self) -> None:
        schema = read("app/schemas/tender.py")
        tenders = read("app/api/endpoints/tenders.py")

        self.assertIn("model_validator", schema)
        self.assertIn("def populate_price_fields", schema)
        self.assertIn("amount = float(self.budget or 0)", schema)
        self.assertIn("if amount <= 0:", schema)
        self.assertIn("self.price_display = (", schema)

        self.assertIn("def _price_fields", tenders)
        price_helper = tenders.split("def _price_fields", 1)[1].split(
            "def _serialize_tender", 1
        )[0]
        self.assertIn("amount = float(tender.budget or 0)", price_helper)
        self.assertIn("if amount <= 0:", price_helper)
        self.assertIn("return None, None, None", price_helper)
        self.assertIn('currency = (tender.currency or "").strip().upper() or None', price_helper)
        self.assertIn('f"{amount:,.2f}".rstrip("0").rstrip(".")', price_helper)

        serializer = tenders.split("def _serialize_tender", 1)[1].split(
            "def _build_company_vault_response", 1
        )[0]
        self.assertIn("payload.price_amount", serializer)
        self.assertIn("payload.price_currency", serializer)
        self.assertIn("payload.price_display", serializer)
        self.assertIn("_price_fields(tender)", serializer)

    def test_tender_list_supports_int4_filters_and_batched_summaries(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")
        list_block = function_block(tenders, "list_tenders")
        filter_block = tenders.split("def apply_explorer_tender_filters", 1)[1].split(
            "@router.get(\"/\"", 1
        )[0]

        for param in ("q:", "country:", "deadline_status:", "category:", "source_system:"):
            self.assertIn(param, list_block)

        self.assertIn('normalized_deadline_status == "active"', filter_block)
        self.assertIn("Tender.deadline >= now", filter_block)
        self.assertIn('normalized_deadline_status == "expired"', filter_block)
        self.assertIn("Tender.deadline < now", filter_block)
        self.assertIn('normalized_deadline_status == "unknown"', filter_block)
        self.assertIn("Tender.deadline.is_(None)", filter_block)
        self.assertIn("_batched_tender_summaries", list_block)
        self.assertNotIn("TenderDocument", list_block)

    def test_public_source_url_suppresses_document_like_urls(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")

        self.assertIn("def _safe_source_notice_url", tenders)
        source_url_helper = tenders.split("def _safe_source_notice_url", 1)[1].split(
            "def _serialize_tender", 1
        )[0]
        for suffix in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"):
            self.assertIn(f'"{suffix}"', source_url_helper)
        self.assertIn("payload.source_url = _safe_source_notice_url", tenders)

    def test_uzex_start_date_is_mapped_to_publication_date(self) -> None:
        scraper = read("app/core/scraper.py")
        uzex_source = read("app/services/tender_sources/uzex.py")
        tenders = read("app/api/endpoints/tenders.py")

        self.assertIn("publication_date: Optional[datetime] = None", scraper)
        self.assertIn('start_date_str = lot.get("start_date")', scraper)
        self.assertIn("publication_date = datetime.fromisoformat(start_date_str)", scraper)
        self.assertIn("publication_date=publication_date", scraper)
        self.assertIn("publication_date=raw.publication_date", uzex_source)
        self.assertIn("def _uzex_trade_list_date_map", tenders)
        self.assertIn('"https://apietender.uzex.uz/api/common/TradeList"', tenders)
        self.assertIn('row.get("start_date")', tenders)
        self.assertIn('row.get("end_date")', tenders)
        self.assertIn("await _apply_live_uzex_dates(tenders)", tenders)
        self.assertIn("await _apply_live_uzex_dates([tender])", tenders)

    def test_int42_removes_small_scale_uzex_from_customer_scope(self) -> None:
        scraper = read("app/core/scraper.py")
        tenders = read("app/api/endpoints/tenders.py")
        uzex_source = read("app/services/tender_sources/uzex.py")
        uzex_scope = read("app/services/tender_sources/uzex_scope.py")
        purge_script = read("scripts/purge_small_scale_uzex_tenders.py")
        frontend_tenders = (ROOT.parent / "frontend/app/dashboard/tenders/page.tsx").read_text(
            encoding="utf-8"
        )

        self.assertIn('UZEX_SMALL_SCALE_ROUTE = "/lots/1/"', read("app/services/tender_sources/uzex_constants.py"))
        self.assertIn('UZEX_ENTERPRISE_ROUTE = "/lots/2/"', read("app/services/tender_sources/uzex_constants.py"))
        self.assertIn("def customer_visible_tender_condition", uzex_scope)
        self.assertIn("uzex_small_scale_tender_condition", uzex_scope)
        self.assertIn("uzex_enterprise_tender_condition", uzex_scope)
        self.assertIn('tender_model.source_system != "uzex"', uzex_scope)
        self.assertIn("customer_visible_tender_condition(Tender)", function_block(tenders, "list_tenders"))
        self.assertIn("customer_visible_tender_condition(Tender)", function_block(tenders, "get_tender"))

        self.assertIn("UZEX_ENTERPRISE_TYPE_ID", scraper)
        self.assertIn('"TypeId": UZEX_ENTERPRISE_TYPE_ID', scraper)
        self.assertNotIn("for type_id in (1, 2)", scraper)
        self.assertNotIn('"TypeId": 1', scraper)
        self.assertIn('"TypeId": UZEX_ENTERPRISE_TYPE_ID', tenders)

        self.assertIn("source_metadata = uzex_source_metadata()", uzex_source)
        self.assertIn("source_metadata.update(raw.source_metadata_json)", uzex_source)
        self.assertIn("source_metadata_json=source_metadata", uzex_source)
        self.assertIn("delete(Tender)", purge_script)
        self.assertIn("UZEX_UNKNOWN", purge_script)
        self.assertIn("_fetch_live_uzex_ids", purge_script)
        self.assertIn("Dependent rows covered by tender FK cascades", purge_script)
        self.assertIn("SourceRefreshMenu", frontend_tenders)
        self.assertIn("displayNameForSource", frontend_tenders)
        self.assertNotIn("const SOURCES", frontend_tenders)
        self.assertIn('SourceDefinition("uzex", "UzEx"', read("app/services/source_registry.py"))

    def test_compiled_text_has_dedicated_authenticated_route(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")

        self.assertIn('"/{tender_id}/compiled-text"', tenders)
        self.assertRegex(
            tenders,
            r"async def get_tender_compiled_text[\s\S]+?_ensure_tender_access",
        )
        self.assertRegex(
            tenders,
            r"get_tender_compiled_text[\s\S]+?current_user: User = Depends\(require_approved_pilot_access\)",
        )

    def test_analysis_and_override_routes_are_owner_gated(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")

        for name in ("analyze_tender", "get_latest_analysis", "override_risk", "get_risk_overrides"):
            self.assertIn("_ensure_tender_access", function_block(tenders, name), name)

        ensure_access = function_block(tenders, "_ensure_tender_access")
        self.assertIn("is_operator_or_admin(current_user)", ensure_access)
        self.assertIn("Proposal.id", ensure_access)
        self.assertIn("TenderAnalysis.id", ensure_access)
        self.assertIn("TenderAnalysis.user_id == current_user.id", ensure_access)
        self.assertIn("TenderAnalysis.company_profile_id == profile.id", ensure_access)
        self.assertIn("TenderAnalysis.ownership_state == ANALYSIS_OWNERSHIP_OWNED", ensure_access)
        self.assertNotIn("TenderAnalysis.company_name", ensure_access)
        self.assertNotIn("def _claim_legacy_analysis_owner", tenders)

        self.assertIn("async def _get_owned_analysis", tenders)
        owned_analysis = function_block(tenders, "_get_owned_analysis")
        self.assertRegex(
            owned_analysis,
            r"TenderAnalysis\.id == analysis_id,[\s\S]+?"
            r"TenderAnalysis\.tender_id == tender_id,[\s\S]+?"
            r"TenderAnalysis\.user_id == current_user\.id,[\s\S]+?"
            r"TenderAnalysis\.company_profile_id == profile\.id,[\s\S]+?"
            r"TenderAnalysis\.ownership_state == ANALYSIS_OWNERSHIP_OWNED",
        )

    def test_operator_support_access_is_route_calibrated(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")

        operator_allowed_routes = (
            "analyze_tender",
            "download_document",
            "get_tender_compiled_text",
            "sync_tender_documents",
            "get_sync_status",
            "get_latest_analysis",
            "export_compliance_pdf",
        )
        for name in operator_allowed_routes:
            self.assertIn("allow_operator=True", function_block(tenders, name), name)

        for name in ("override_risk", "get_risk_overrides"):
            self.assertNotIn("allow_operator=True", function_block(tenders, name), name)

    def test_debug_rejected_requirements_are_scrubbed_from_customer_payloads(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")

        self.assertIn("def _public_evidence_validation_payload", tenders)
        self.assertIn('payload.pop("rejected_requirements", None)', tenders)

    def test_admin_and_audit_routes_are_gated(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")
        users = read("app/api/endpoints/users.py")
        audit = read("app/api/routers/audit.py")
        deps = read("app/api/deps.py")

        for route in ("test-scrape", "proxy-download", "seed"):
            self.assertRegex(
                tenders,
                rf'@router\.post\("/{route}"[\s\S]+?Depends\(require_admin\)',
                route,
            )
        self.assertRegex(
            tenders,
            r'@router\.post\("/refresh"[\s\S]+?Depends\(require_approved_user\)',
        )
        self.assertIn("Force refresh requires operator access", tenders)
        self.assertRegex(
            tenders,
            r'@router\.post\(\s*"/sources/adb/sync"[\s\S]+?Depends\(require_operator_or_admin\)',
        )
        self.assertRegex(
            tenders,
            r'@router\.post\(\s*"/sources/world-bank/sync"[\s\S]+?Depends\(require_operator_or_admin\)',
        )
        self.assertIn("async def require_operator_or_admin", deps)
        self.assertIn("PLASMA_OPERATOR_EMAILS", deps)
        self.assertIn("PLATFORM_ROLE_OPERATOR", deps)
        self.assertIn("PLATFORM_ROLE_ADMIN", deps)
        self.assertIn("Operator access required", deps)

        self.assertIn("Depends(require_admin)", users)
        self.assertIn("current_user: User = Depends(require_approved_pilot_access)", audit)
        self.assertIn("user_id=str(current_user.id)", audit)
        self.assertNotIn("user_id=request.user_id", audit)

    def test_alembic_version_table_supports_long_revision_ids(self) -> None:
        env = read("alembic/env.py")
        migration = read("alembic/versions/20260610_0001_multi_source_tender_foundation.py")

        self.assertIn("def _ensure_alembic_version_column_width", env)
        self.assertIn("ALTER TABLE alembic_version", env)
        self.assertIn("ALTER COLUMN version_num TYPE VARCHAR(128)", env)
        self.assertIn("_ensure_alembic_version_column_width(connection)", env)
        self.assertIn("connection.in_transaction()", env)
        self.assertIn("connection.commit()", env)
        self.assertIn("def _ensure_alembic_version_column_width", migration)
        self.assertIn("_ensure_alembic_version_column_width()", migration)

    def test_tender_source_refresh_controls_cover_all_supported_sources(self) -> None:
        page = read("../frontend/app/dashboard/tenders/page.tsx")
        menu = read("../frontend/components/source-refresh/SourceRefreshMenu.tsx")
        provider = read("../frontend/components/source-refresh/SourceRefreshProvider.tsx")
        client = read("../frontend/lib/sourceRefresh.ts")

        self.assertIn("SourceRefreshMenu", page)
        self.assertNotIn("SOURCE_REFRESH", page)
        self.assertNotIn("const SOURCES", page)
        self.assertIn("catalog.map", menu)
        self.assertIn("pendingSources.has(source.source_system)", menu)
        self.assertIn("!source.can_refresh", menu)
        self.assertIn("requestRefresh(source.source_system)", menu)
        self.assertIn("`/tenders/sources/${encodeURIComponent(sourceSystem)}/refresh`", client)
        self.assertIn("listSourceCatalog", provider)

    def test_tender_document_sync_enqueue_uses_heavy_queue(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")
        celery = read("app/core/celery_app.py")
        sync_block = function_block(tenders, "sync_tender_documents")

        self.assertIn('queue="heavy_dl_queue"', sync_block)
        self.assertIn('routing_key="heavy_dl_queue"', sync_block)
        self.assertIn("retry=True", sync_block)
        self.assertIn("error_type = type(exc).__name__", sync_block)
        self.assertIn("Check Redis and the heavy document worker", sync_block)
        self.assertIn("task_publish_retry=True", celery)
        self.assertIn("broker_connection_retry_on_startup=True", celery)

    def test_tender_document_sync_has_fast_production_defaults(self) -> None:
        worker = read("app/workers/tender_tasks.py")
        parser = read("app/core/parser.py")

        self.assertIn("TENDER_DOC_DOWNLOAD_JITTER_MIN_SECONDS", worker)
        self.assertIn("TENDER_DOC_DOWNLOAD_JITTER_MAX_SECONDS", worker)
        self.assertIn("DOWNLOAD_JITTER_MAX_SECONDS <= 0", worker)
        self.assertIn('TENDER_OCR_PAGE_TIMEOUT_SECONDS", 12', parser)
        self.assertIn('TENDER_OCR_MAX_PAGES", 2', parser)
        self.assertIn('TENDER_OCR_RENDER_DPI", 150', parser)
        self.assertIn("TENDER_OCR_SKIP_AFTER_TEXT_CHARS", parser)
        self.assertIn("OCR skipped after", parser)

    def test_proposal_response_scrubs_uploaded_tz_internals(self) -> None:
        proposals = read("app/api/endpoints/proposals.py")

        self.assertIn("SENSITIVE_STRUCTURED_DATA_KEYS", proposals)
        self.assertIn('"uploaded_tz_path"', proposals)
        self.assertIn('"uploaded_tz_text"', proposals)
        self.assertIn("structured_data=_public_structured_data", proposals)


if __name__ == "__main__":
    unittest.main()
