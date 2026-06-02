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

    def test_compiled_text_has_dedicated_authenticated_route(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")

        self.assertIn('"/{tender_id}/compiled-text"', tenders)
        self.assertRegex(
            tenders,
            r"async def get_tender_compiled_text[\s\S]+?_ensure_tender_access",
        )
        self.assertRegex(
            tenders,
            r"get_tender_compiled_text[\s\S]+?current_user: User = Depends\(get_current_user\)",
        )

    def test_analysis_and_override_routes_are_owner_gated(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")

        for name in ("analyze_tender", "get_latest_analysis", "override_risk", "get_risk_overrides"):
            self.assertIn("_ensure_tender_access", function_block(tenders, name), name)

        self.assertIn("async def _get_owned_analysis", tenders)
        self.assertRegex(
            tenders,
            r"TenderAnalysis\.id == analysis_id,[\s\S]+?"
            r"TenderAnalysis\.tender_id == tender_id,[\s\S]+?"
            r"TenderAnalysis\.company_name == owner_key",
        )

    def test_debug_rejected_requirements_are_scrubbed_from_customer_payloads(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")

        self.assertIn("def _public_evidence_validation_payload", tenders)
        self.assertIn('payload.pop("rejected_requirements", None)', tenders)

    def test_admin_and_audit_routes_are_gated(self) -> None:
        tenders = read("app/api/endpoints/tenders.py")
        users = read("app/api/endpoints/users.py")
        audit = read("app/api/routers/audit.py")

        for route in ("test-scrape", "proxy-download", "refresh", "seed"):
            self.assertRegex(
                tenders,
                rf'@router\.post\("/{route}"[\s\S]+?Depends\(require_admin\)',
                route,
            )

        self.assertIn("Depends(require_admin)", users)
        self.assertIn("current_user: User = Depends(get_current_user)", audit)
        self.assertIn("user_id=str(current_user.id)", audit)
        self.assertNotIn("user_id=request.user_id", audit)

    def test_proposal_response_scrubs_uploaded_tz_internals(self) -> None:
        proposals = read("app/api/endpoints/proposals.py")

        self.assertIn("SENSITIVE_STRUCTURED_DATA_KEYS", proposals)
        self.assertIn('"uploaded_tz_path"', proposals)
        self.assertIn('"uploaded_tz_text"', proposals)
        self.assertIn("structured_data=_public_structured_data", proposals)


if __name__ == "__main__":
    unittest.main()
