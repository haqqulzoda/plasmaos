from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError

from app.api.endpoints.users import UserPreferencesUpdate, update_current_user_preferences
from app.core.analysis_languages import (
    CUSTOMER_SELECTABLE_ANALYSIS_LANGUAGE_VALUES,
    resolve_analysis_language,
)
from app.core.locales import CUSTOMER_SELECTABLE_UI_LOCALE_VALUES, UiLocale


ROOT = Path(__file__).resolve().parent


def test_arabic_ui_is_released_while_arabic_analysis_remains_gated() -> None:
    assert CUSTOMER_SELECTABLE_UI_LOCALE_VALUES == ("en", "uz", "ru", "ar")
    assert UserPreferencesUpdate(ui_locale="ar").ui_locale == UiLocale.ARABIC
    assert CUSTOMER_SELECTABLE_ANALYSIS_LANGUAGE_VALUES == ("en", "uz", "ru")
    with pytest.raises(ValidationError) as raised:
        UserPreferencesUpdate(default_analysis_language="ar")
    assert raised.value.errors()[0]["type"] == "unsupported_analysis_language"
    with pytest.raises(ValueError):
        resolve_analysis_language("ar", "en")


def test_arabic_ui_update_is_narrow_and_preserves_analysis_and_auth_state() -> None:
    user = SimpleNamespace(
        id="user-a",
        ui_locale="en",
        default_analysis_language="uz",
        auth_version=41,
        platform_role="pilot_user",
        approval_status="approved",
        company_profile_id="company-a",
        email="owner@example.test",
    )
    before = vars(user).copy()
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    response = asyncio.run(
        update_current_user_preferences(
            UserPreferencesUpdate(ui_locale="ar"), current_user=user, db=db,
        )
    )
    assert response.ui_locale == UiLocale.ARABIC
    assert user.ui_locale == "ar"
    assert user.default_analysis_language == "uz"
    assert user.auth_version == 41
    assert {
        key: value for key, value in vars(user).items() if key != "ui_locale"
    } == {
        key: value for key, value in before.items() if key != "ui_locale"
    }
    db.commit.assert_awaited_once_with()
    db.refresh.assert_awaited_once_with(user)


def test_sprint_8_3_adds_no_migration_and_keeps_the_s8_2_single_head() -> None:
    config = Config()
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["20260904_0001_s8_2_analysis_language"]
    assert not list((ROOT / "alembic/versions").glob("*s8_3*"))


def test_arabic_pdf_gate_and_version_language_authority_are_unchanged() -> None:
    endpoint = (ROOT / "app/api/endpoints/tenders.py").read_text(encoding="utf-8")
    assert "version.analysis_language == AnalysisLanguage.ARABIC.value" in endpoint
    assert "analysis_language=version.analysis_language" in endpoint
