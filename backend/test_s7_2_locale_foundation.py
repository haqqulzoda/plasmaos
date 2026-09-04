from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock
from uuid import uuid4

from pydantic import ValidationError

from app.api.endpoints.users import (
    UserPreferencesUpdate,
    UserResponse,
    update_current_user_preferences,
)
from app.core.locales import (
    CUSTOMER_SELECTABLE_UI_LOCALE_VALUES,
    KNOWN_UI_LOCALES,
    UiLocale,
)
from app.models.base import SubscriptionTier
from app.models.user import User


ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parent / "frontend"


def make_user(*, locale: str | None = None, approval_status: str = "approved"):
    return SimpleNamespace(
        id=uuid4(),
        google_id="google-id",
        email="pilot@example.com",
        name="Pilot",
        avatar_url=None,
        subscription_tier=SubscriptionTier.SCOUT,
        is_admin=False,
        approval_status=approval_status,
        platform_role="pilot_user",
        auth_version=17,
        ui_locale=locale,
    )


class LocaleContractTests(TestCase):
    def test_registry_knows_arabic_but_customer_api_only_accepts_en_uz_ru(self):
        self.assertEqual(KNOWN_UI_LOCALES, ("en", "uz", "ru", "ar"))
        self.assertEqual(CUSTOMER_SELECTABLE_UI_LOCALE_VALUES, ("en", "uz", "ru"))
        for locale in CUSTOMER_SELECTABLE_UI_LOCALE_VALUES:
            self.assertEqual(UserPreferencesUpdate(ui_locale=locale).ui_locale.value, locale)

        for locale in ("ar", "fr", "uz-Cyrl-UZ", "", None, 7):
            with self.subTest(locale=locale), self.assertRaises(ValidationError) as raised:
                UserPreferencesUpdate(ui_locale=locale)
            self.assertEqual(raised.exception.errors()[0]["type"], "unsupported_ui_locale")

    def test_preference_payload_is_narrow_and_rejects_extra_fields(self):
        with self.assertRaises(ValidationError) as raised:
            UserPreferencesUpdate(ui_locale="uz", auth_version=999)
        self.assertEqual(raised.exception.errors()[0]["type"], "extra_forbidden")

    def test_current_user_schema_preserves_null_and_serializes_saved_locale(self):
        expected = {
            None: None,
            "en": UiLocale.ENGLISH,
            "uz": UiLocale.UZBEK,
            "ru": UiLocale.RUSSIAN,
        }
        for raw, locale in expected.items():
            with self.subTest(locale=raw):
                self.assertEqual(UserResponse.model_validate(make_user(locale=raw)).ui_locale, locale)

    def test_model_and_migration_keep_historical_null_semantics(self):
        locale_column = User.__table__.c.ui_locale
        self.assertTrue(locale_column.nullable)
        self.assertIsNone(locale_column.default)
        migration = (ROOT / "alembic/versions/20260902_0001_s7_2_user_ui_locale.py").read_text()
        self.assertIn('nullable=True', migration)
        self.assertNotIn('UPDATE users', migration)
        self.assertNotIn('server_default', migration)
        self.assertIn("'en', 'uz', 'ru', 'ar'", migration)

    def test_locale_is_absent_from_auth_and_company_authority_contracts(self):
        auth = (ROOT / "app/api/endpoints/auth.py").read_text()
        security = (ROOT / "app/core/security/__init__.py").read_text()
        users = (ROOT / "app/api/endpoints/users.py").read_text()
        company_block = users.split("class CompanyProfileResponse", 1)[1]
        self.assertNotIn("ui_locale", auth)
        self.assertNotIn("ui_locale", security)
        self.assertNotIn("ui_locale", company_block)

    def test_frontend_has_one_registry_and_no_locale_route_or_local_storage_authority(self):
        source_files = []
        for source_root in ("app", "components", "i18n", "lib", "types"):
            source_files.extend((FRONTEND / source_root).rglob("*.ts"))
            source_files.extend((FRONTEND / source_root).rglob("*.tsx"))
        source_files.extend((FRONTEND / name) for name in ("middleware.ts", "auth.ts"))
        combined = "\n".join(path.read_text(encoding="utf-8") for path in source_files)
        self.assertEqual(combined.count("export const PRODUCT_LOCALE_CODES"), 1)
        self.assertNotIn("localStorage.setItem('ui_locale'", combined)
        self.assertNotIn('localStorage.setItem("ui_locale"', combined)
        self.assertFalse(any("[locale]" in path.parts or "[lang]" in path.parts for path in source_files))


class LocaleUpdateTests(IsolatedAsyncioTestCase):
    async def test_each_selectable_locale_updates_the_current_user(self):
        for locale in CUSTOMER_SELECTABLE_UI_LOCALE_VALUES:
            with self.subTest(locale=locale):
                user = make_user(locale=None)
                db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
                response = await update_current_user_preferences(
                    UserPreferencesUpdate(ui_locale=locale),
                    current_user=user,
                    db=db,
                )
                self.assertEqual(user.ui_locale, locale)
                self.assertEqual(response.ui_locale.value, locale)

    async def test_update_changes_only_locale_and_keeps_auth_version(self):
        user = make_user(locale="en")
        before = vars(user).copy()
        db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

        response = await update_current_user_preferences(
            UserPreferencesUpdate(ui_locale="uz"),
            current_user=user,
            db=db,
        )

        self.assertEqual(response.ui_locale, UiLocale.UZBEK)
        self.assertEqual(user.ui_locale, "uz")
        self.assertEqual(user.auth_version, before["auth_version"])
        self.assertEqual(
            {key: value for key, value in vars(user).items() if key != "ui_locale"},
            {key: value for key, value in before.items() if key != "ui_locale"},
        )
        db.commit.assert_awaited_once_with()
        db.refresh.assert_awaited_once_with(user)

    async def test_pending_authenticated_user_can_update_without_domain_writes(self):
        user = make_user(locale=None, approval_status="pending")
        db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
        await update_current_user_preferences(
            UserPreferencesUpdate(ui_locale="ru"),
            current_user=user,
            db=db,
        )
        self.assertEqual(user.ui_locale, "ru")
        self.assertEqual(user.approval_status, "pending")


if __name__ == "__main__":
    import unittest

    unittest.main()
