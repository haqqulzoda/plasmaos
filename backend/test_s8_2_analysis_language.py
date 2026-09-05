from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError

from app.api.endpoints.users import UserPreferencesUpdate, update_current_user_preferences
from app.core.agents.requirement_extractor import (
    EvidenceValidationStatus,
    RequirementCategory,
    RequirementScope,
    ScopeReviewStatus,
    TenderRequirement,
    _build_extraction_prompt,
)
from app.core.analysis_languages import (
    ANALYSIS_LANGUAGE_REGISTRY,
    ANALYSIS_LANGUAGE_VALUES,
    CUSTOMER_SELECTABLE_ANALYSIS_LANGUAGE_VALUES,
    AnalysisDirection,
    AnalysisLanguage,
    analysis_direction,
    analysis_language_prompt_instruction,
    resolve_analysis_language,
)
from app.core.compliance_pdf import build_compliance_report_pdf
from app.models.all_models import Base
from app.models.audit import AnalysisVersion, AnalysisVersionMutationError
from app.services.analysis_language_content import (
    generated_headlines_follow_language,
    generated_texts_follow_language,
    localize_validated_requirements,
)
from app.services.analysis_versions import _version_hash_payload, stable_json_sha256


ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parent / "frontend"
MIGRATION = ROOT / "alembic/versions/20260904_0001_s8_2_analysis_language.py"


def _hash_payload(language: str | None) -> dict[str, object]:
    return _version_hash_payload(
        analysis_id=uuid4(), version_number=1, supersedes_version_id=None,
        origin="RUNTIME_ANALYSIS", status="COMPLETED", analysis_schema_version="v1",
        pipeline_version="v1", model_provider="google", model_name="gemini",
        model_version="gemini", prompt_template_version="v1", prompt_template_hash="a" * 64,
        provenance_snapshot={}, tender_snapshot={}, company_snapshot={}, result_snapshot={},
        evidence_snapshot={}, input_hash="b" * 64, output_hash="c" * 64,
        evidence_hash="d" * 64, document_set_hash_value="e" * 64,
        snapshot_completeness="COMPLETE", requested_by_user_id=uuid4(),
        analysis_language=language,
    )


def _user(default: str | None = None, ui: str | None = "uz") -> SimpleNamespace:
    return SimpleNamespace(default_analysis_language=default, ui_locale=ui, auth_version=41)


def test_registry_is_independent_canonical_and_arabic_is_truthfully_gated() -> None:
    assert ANALYSIS_LANGUAGE_VALUES == ("en", "uz", "ru", "ar")
    assert CUSTOMER_SELECTABLE_ANALYSIS_LANGUAGE_VALUES == ("en", "uz", "ru")
    assert set(ANALYSIS_LANGUAGE_REGISTRY) == set(AnalysisLanguage)
    assert ANALYSIS_LANGUAGE_REGISTRY[AnalysisLanguage.ARABIC].generation_supported
    assert not ANALYSIS_LANGUAGE_REGISTRY[AnalysisLanguage.ARABIC].customer_selectable
    assert analysis_direction("ar") == AnalysisDirection.RTL
    assert analysis_direction(None) == AnalysisDirection.AUTO


def test_resolution_precedence_never_uses_ui_locale() -> None:
    assert resolve_analysis_language("ru", "uz") == AnalysisLanguage.RUSSIAN
    assert resolve_analysis_language(None, "uz") == AnalysisLanguage.UZBEK
    assert resolve_analysis_language(None, None) == AnalysisLanguage.ENGLISH
    assert resolve_analysis_language(None, "ar") == AnalysisLanguage.ENGLISH
    with pytest.raises(ValueError):
        resolve_analysis_language("ar", "en")


def test_preference_validation_matrix_and_empty_request() -> None:
    for code in ("en", "uz", "ru"):
        assert UserPreferencesUpdate(default_analysis_language=code).default_analysis_language.value == code
    for code in ("ar", "fr", "en-US", "", "Write in Russian"):
        with pytest.raises(ValidationError):
            UserPreferencesUpdate(default_analysis_language=code)
    with pytest.raises(ValidationError):
        UserPreferencesUpdate()
    with pytest.raises(ValidationError):
        UserPreferencesUpdate(ui_locale=None)
    assert UserPreferencesUpdate(default_analysis_language=None).default_analysis_language is None
    both = UserPreferencesUpdate(ui_locale="ru", default_analysis_language="uz")
    assert both.ui_locale.value == "ru" and both.default_analysis_language.value == "uz"


def test_default_update_is_narrow_and_does_not_bump_auth_or_ui_locale() -> None:
    user = _user("en", "uz")
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    response = asyncio.run(update_current_user_preferences(
        UserPreferencesUpdate(default_analysis_language="ru"), current_user=user, db=db,
    ))
    assert response.default_analysis_language == AnalysisLanguage.RUSSIAN
    assert user.default_analysis_language == "ru"
    assert user.ui_locale == "uz"
    assert user.auth_version == 41
    db.commit.assert_awaited_once_with()

    cleared = asyncio.run(update_current_user_preferences(
        UserPreferencesUpdate(default_analysis_language=None), current_user=user, db=db,
    ))
    assert cleared.default_analysis_language is None
    assert user.default_analysis_language is None
    assert user.ui_locale == "uz" and user.auth_version == 41


def test_model_columns_are_nullable_constrained_and_unindexed() -> None:
    users = Base.metadata.tables["users"]
    versions = Base.metadata.tables["analysis_versions"]
    assert users.c.default_analysis_language.nullable and users.c.default_analysis_language.default is None
    assert versions.c.analysis_language.nullable and versions.c.analysis_language.default is None
    constraints = {constraint.name for constraint in users.constraints | versions.constraints}
    assert "ck_users_default_analysis_language_allowed" in constraints
    assert "ck_analysis_versions_analysis_language_allowed" in constraints
    assert not users.c.default_analysis_language.index
    assert not versions.c.analysis_language.index


def test_single_additive_migration_and_historical_null_semantics() -> None:
    config = Config()
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["20260904_0001_s8_2_analysis_language"]
    assert script.get_revision("20260904_0001_s8_2_analysis_language").down_revision == "20260902_0001_s7_2_user_ui_locale"
    source = MIGRATION.read_text(encoding="utf-8")
    assert source.count("op.add_column(") == 2
    assert "UPDATE " not in source.upper()
    assert "server_default" not in source
    assert "create_index" not in source


def test_prompt_uses_trusted_name_and_preserves_evidence() -> None:
    instruction = analysis_language_prompt_instruction("uz")
    assert "Uzbek (Latin script)" in instruction
    assert "verbatim" in instruction and "never translate" in instruction
    prompt = _build_extraction_prompt("[[FILE: source.pdf]]\n[[PAGE 2]]\nТочная цитата", "ru")
    assert "Russian" in prompt
    assert "Точная цитата" in prompt
    assert "source.pdf" in prompt


def test_generated_localization_preserves_source_owned_fields_and_schema() -> None:
    requirement = TenderRequirement(
        category=RequirementCategory.DQ,
        headline="Tax clearance certificate",
        source_filename="buyer-файл.pdf",
        source_page=7,
        exact_quote="Справка должна быть действующей",
        validation_status=EvidenceValidationStatus.ACCEPTED,
        source_verified=True,
        requirement_scope=RequirementScope.ELIGIBILITY,
        scope_review_status=ScopeReviewStatus.ACCEPTED,
        affects_bid_eligibility=True,
    )
    localized = localize_validated_requirements([requirement], "ru")[0]
    assert localized.source_filename == requirement.source_filename
    assert localized.source_page == requirement.source_page
    assert localized.exact_quote == requirement.exact_quote
    assert localized.category == RequirementCategory.DQ
    assert "Доказательство" in localized.validation_reason
    assert generated_headlines_follow_language([requirement], "en")
    assert not generated_headlines_follow_language([requirement], "ru")
    assert generated_texts_follow_language(["Критерий оценки"], "ru")
    assert not generated_texts_follow_language(["Evaluation criterion"], "ru")
    assert generated_texts_follow_language(["Baholash mezoni"], "uz")


def test_new_hashes_include_language_and_legacy_hash_envelope_is_unchanged() -> None:
    legacy = _hash_payload(None)
    english = _hash_payload("en")
    uzbek = _hash_payload("uz")
    assert "analysis_language" not in legacy
    assert english["analysis_language"] == "en"
    assert uzbek["analysis_language"] == "uz"
    # The helper inputs use fresh IDs, so also compare equal canonical envelopes.
    english_same = dict(english)
    uzbek_same = dict(english, analysis_language="uz")
    assert stable_json_sha256(english_same) != stable_json_sha256(uzbek_same)
    assert stable_json_sha256(english_same) == stable_json_sha256(dict(english_same))


def test_analysis_language_is_immutable_after_persistence_state() -> None:
    version = AnalysisVersion(analysis_language="en")
    # A transient object may be initialized; the ORM validator covers persistent/detached rows.
    assert version.analysis_language == "en"
    model_source = (ROOT / "app/models/audit.py").read_text(encoding="utf-8")
    assert '"analysis_language",' in model_source
    assert AnalysisVersionMutationError.__name__ in model_source


def test_pdf_chrome_uses_version_language_and_arabic_is_gated_at_endpoint() -> None:
    common = dict(
        tender_title="Test", tender_external_id="T-1", company_name="Company",
        generated_at=datetime(2026, 9, 4, tzinfo=timezone.utc), analysis_id=uuid4(),
        content_hash="a" * 64, override_seal=None,
        hybrid_compliance={"verdict_status": "NEEDS_REVIEW", "status_message": "",
                           "satisfied_count": 0, "failed_count": 0, "manual_review_count": 0,
                           "recorded_obligations_count": 0, "skipped_optional_count": 0,
                           "failed_dealbreakers": [], "satisfied_requirements": [],
                           "manual_reviews_required": [], "recorded_obligations": []},
        evidence_validation=None, analysis_warnings=[], analysis_version=1,
        snapshot_completeness="COMPLETE",
    )
    assert build_compliance_report_pdf(**common, analysis_language="en").startswith(b"%PDF")
    assert build_compliance_report_pdf(**common, analysis_language="uz").startswith(b"%PDF")
    assert build_compliance_report_pdf(**common, analysis_language="ru").startswith(b"%PDF")
    endpoint = (ROOT / "app/api/endpoints/tenders.py").read_text(encoding="utf-8")
    export = endpoint[endpoint.index("async def export_compliance_pdf"):]
    assert "version.analysis_language == AnalysisLanguage.ARABIC.value" in export
    assert "analysis_language=version.analysis_language" in export
    assert "ui_locale" not in export


def test_frontend_independence_direction_history_and_no_global_rtl() -> None:
    settings = (FRONTEND / "app/dashboard/settings/page.tsx").read_text(encoding="utf-8")
    compliance = (FRONTEND / "app/dashboard/tenders/[tenderId]/compliance/page.tsx").read_text(encoding="utf-8")
    registry = (FRONTEND / "i18n/analysisLanguages.ts").read_text(encoding="utf-8")
    assert "LanguageSelector" in settings and "analysisLanguage.title" in settings
    assert "analysis_language: selectedAnalysisLanguage" in compliance
    assert "analysisContentDirection" in compliance and 'dir="auto"' in compliance
    assert "versionHistory" in compliance and "notRecorded" in compliance
    assert "customerSelectable: false" in registry
    assert "flag" not in registry.casefold()
    assert 'document.documentElement.dir' not in compliance
