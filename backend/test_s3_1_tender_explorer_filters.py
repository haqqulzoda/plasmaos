from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


try:
    from app.api.endpoints import tenders as tender_endpoints
except ModuleNotFoundError as exc:  # pragma: no cover - local minimal env
    if exc.name in {
        "fastapi",
        "httpx",
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
    }:
        tender_endpoints = None
        HAS_BACKEND_DEPS = False
    else:
        raise
else:
    HAS_BACKEND_DEPS = True


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class S31TenderExplorerFilterStaticTests(unittest.TestCase):
    def test_tender_endpoint_exposes_s3_1_filters_and_sorting(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")
        list_route = tenders.split("async def list_tenders", 1)[1].split(
            '@router.get("/{tender_id}"',
            1,
        )[0]

        for expected in (
            "source: str | None",
            "region: list[str] | None",
            "countries: list[str] | None",
            "services: list[str] | None",
            "deadline_status: str | None",
            "deadline_from: datetime | None",
            "deadline_to: datetime | None",
            "price_min: float | None",
            "price_max: float | None",
            "document_status: str | None",
            "sort: str | None",
        ):
            self.assertIn(expected, list_route)

        for expected_sort in (
            "newest",
            "deadline_soonest",
            "highest_price",
            "document_availability",
            "source",
        ):
            self.assertIn(expected_sort, tenders)

    def test_frontend_uses_s2_taxonomies_for_tender_filters(self) -> None:
        explorer = read("../frontend/app/dashboard/tenders/page.tsx")

        self.assertIn("CENTRAL_ASIA_COUNTRIES", explorer)
        self.assertIn("DEFAULT_SERVICE_OPTIONS", explorer)
        self.assertIn("Central Asia", explorer)
        for expected in (
            "Uzbekistan",
            "Kazakhstan",
            "Kyrgyzstan",
            "Tajikistan",
            "Turkmenistan",
        ):
            self.assertIn(expected, read("../frontend/lib/geography.ts"))

        self.assertIn("useSearchParams", explorer)
        self.assertIn("query.countries", explorer)
        self.assertIn("query.services", explorer)
        self.assertIn("countries: query.countries", explorer)
        self.assertIn("services: query.services", explorer)


@unittest.skipUnless(HAS_BACKEND_DEPS, "Backend dependencies are not installed")
class S31TenderExplorerFilterBehaviorTests(unittest.TestCase):
    def test_central_asia_expands_to_required_countries(self) -> None:
        assert tender_endpoints is not None

        self.assertEqual(
            tender_endpoints._expanded_region_countries(["Central Asia"]),
            [
                "Uzbekistan",
                "Kazakhstan",
                "Kyrgyzstan",
                "Tajikistan",
                "Turkmenistan",
            ],
        )

    def test_query_value_normalizers_support_multiselect_inputs(self) -> None:
        assert tender_endpoints is not None

        self.assertEqual(
            tender_endpoints._split_query_values(["Uzbekistan,Kazakhstan", " Kyrgyzstan "]),
            ["Uzbekistan", "Kazakhstan", "Kyrgyzstan"],
        )
        self.assertEqual(
            tender_endpoints._normalize_service_filter(
                ["Construction", "equipment supply", "it"]
            ),
            ["construction", "equipment supply", "IT"],
        )

    def test_visible_corpus_guard_and_small_uzex_exclusion_remain_in_list_route(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")
        list_route = tenders.split("async def list_tenders", 1)[1].split(
            '@router.get("/{tender_id}"',
            1,
        )[0]

        self.assertIn("customer_visible_tender_condition(Tender)", list_route)
        self.assertIn('normalized_source not in {"uzex", "world_bank", "adb", "giz", "ebrd"}', tenders)


if __name__ == "__main__":
    unittest.main()
