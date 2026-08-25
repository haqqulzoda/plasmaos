"""Unit tests for the GIZ public tender connector."""

from __future__ import annotations

import unittest
import asyncio
from types import SimpleNamespace

from app.services.tender_sources.giz import (
    GizTenderSource,
    _discover_procedure_information_url,
    _extract_eproc_procedure_metadata,
    _parse_eproc_listing_page,
    parse_giz_tender_page,
)
from app.services.tender_sources.keys import canonical_source_key


GIZ_PAGE_FIXTURE = """
<main>
  <h1>South Africa</h1>
  <p>GIZ only accepts bids via email
    <a href="#" data-mail-to="MN_Dhbgngvba/ng/tvm/qbg/qr" data-replace-inner="@email">@email</a>
    and filetransfer.giz.de.
  </p>
  <div class="list-item__wrapper">
    <div class="list-item__meta">Deadline: 15.07.2026</div>
    <div class="list-item__content-wrapper">
      <div class="list-item__content">
        <div class="list-item__title">
          <span>Call for Proposals (7000012992): Implementation of the BioPANZA MSME Pipeline Pilot</span>
        </div>
        <div class="list-item__sub">
          <p>Download below documents for more details.</p>
        </div>
        <div class="list-item__downloads box">
          <div class="download">
            <div class="download__title"><span>7000012992-TOR.pdf</span></div>
            <div class="download__infos">
              <div class="download__info">pdf</div>
              <div class="download__info">909.16 KB</div>
            </div>
            <a download href="/sites/default/files/media/els-document/2026-06/7000012992-tor.pdf"></a>
          </div>
          <div class="download">
            <div class="download__title"><span>7000012992-price-schedule.xlsx</span></div>
            <div class="download__infos">
              <div class="download__info">xlsx</div>
              <div class="download__info">94.56 KB</div>
            </div>
            <a download href="/sites/default/files/media/els-document/2026-06/7000012992-price-schedule.xlsx"></a>
          </div>
        </div>
      </div>
    </div>
  </div>
</main>
"""


GIZ_FLAT_DOWNLOAD_FIXTURE = """
<main>
  <h1>Viet Nam</h1>
  <p>If you have questions about a concrete tender, please drop a short email to
    <a href="#" data-mail-to="IA_Dhbgngvba/ng/tvm/qbg/qr" data-replace-inner="@email">@email</a>.
  </p>
  <div class="download">
    <div class="download__title">
      <span>Deadline-5PM-23.07.2026-7000015155-Call-for-EoI-VN-EN.docx</span>
    </div>
    <div class="download__infos">
      <div class="download__info">docx</div>
      <div class="download__info">114.67 KB</div>
    </div>
    <a download href="/sites/default/files/media/els-document/2026-07/deadline-5pm-23.07.2026-7000015155-call-for-eoi-vn-en.docx"></a>
  </div>
</main>
"""


GIZ_EPROC_LIST_FIXTURE = """
<table>
  <tr><th>Veröffentlicht</th><th>Angebots- / Teilnahmefrist</th><th>Bezeichnung</th><th>Typ</th><th>Ausschreibende Stelle</th><th>Aktion</th></tr>
  <tr>
    <td>02.07.2026</td>
    <td>23.07.2026</td>
    <td>Workstations und Peripheriegeräte für Usbekistan</td>
    <td>UVgOAusschreibung</td>
    <td>Deutsche Gesellschaft für Internationale Zusammenarbeit (GIZ) GmbH</td>
    <td><a href="/Satellite/public/company/projectForwarding.do?pid=51442"></a></td>
  </tr>
  <tr>
    <td>02.07.2026</td><td>nv</td><td>Awarded thing</td><td>UVgOVergebener Auftrag</td>
    <td>GIZ</td><td><a href="/Satellite/public/company/projectForwarding.do?pid=1"></a></td>
  </tr>
</table>
"""


GIZ_EPROC_PROJECT_FIXTURE = """
<main>
  <a href="./processdata/eforms">Verfahrensangaben</a>
  <a href="./documents">Vergabeunterlagen</a>
</main>
"""


GIZ_EPROC_PROCEDURE_FIXTURE = """
<main>
  <div>VO: UVgO Vergabeart: Öffentliche Ausschreibung Status: Veröffentlicht</div>
  <div class="csx-project-form">
    <fieldset>
      <legend>Zur Angebotsabgabe / Teilnahme auffordernde Stelle</legend>
      <div class="control-group"><label class="control-label">Offizielle Bezeichnung</label><div class="controls"><span class="read-only">Deutsche Gesellschaft für Internationale Zusammenarbeit (GIZ) GmbH</span></div></div>
      <div class="control-group"><label class="control-label">Postanschrift</label><div class="controls"><span class="read-only">Dag-Hammarskjöld-Weg 1 - 5</span></div></div>
      <div class="control-group"><label class="control-label">Postleitzahl</label><div class="controls"><span class="read-only">65760</span></div></div>
      <div class="control-group"><label class="control-label">Ort</label><div class="controls"><span class="read-only">Eschborn</span></div></div>
      <div class="control-group"><label class="control-label">Land</label><div class="controls"><span class="read-only">Deutschland</span></div></div>
      <div class="control-group"><label class="control-label">Telefon</label><div class="controls"><span class="read-only">+49 6196796441</span></div></div>
      <div class="control-group"><label class="control-label">E-Mail</label><div class="controls"><span class="read-only">iana.mengel@giz.de</span></div></div>
    </fieldset>
  </div>
  <div class="csx-project-form">
    <div class="sub-headline-container"><h4 class="sub-headline">Haupterfüllungsort</h4></div>
    <p>Ort Taschkent Ergänzende Angaben Endbestimmungsland Usbekistan</p>
  </div>
  <div class="csx-project-form">
    <div class="sub-headline-container"><h4 class="sub-headline">Schlusstermin für den Eingang der Angebote</h4></div>
    <div class="control-group"><span class="read-only bold">23.07.2026</span> <span class="read-only bold">12:00</span> Uhr</div>
  </div>
  <div class="csx-project-form">
    <div class="sub-headline-container"><h4 class="sub-headline">Zusätzliche Angaben</h4></div>
    <div class="control-group"><span class="read-only read-only-textarea">Die Kommunikation findet ausschließlich über den Projektbereich des GIZ-Vergabemarktplatz statt.</span></div>
  </div>
  <p>Angebote oder Teilnahmeanträge sind einzureichen elektronisch über diese Vergabeplattform https://ausschreibungen.giz.de/Satellite/notice/CXTRYYRYT1HKJDH7</p>
</main>
"""


class GizConnectorTests(unittest.TestCase):
    def test_parse_public_country_page_and_documents(self) -> None:
        payloads = parse_giz_tender_page(
            GIZ_PAGE_FIXTURE,
            page_url="https://www.giz.de/en/regions/africa/south-africa/tenders",
        )

        self.assertEqual(len(payloads), 1)
        payload = payloads[0]
        self.assertEqual(payload["source_system"], "giz")
        self.assertEqual(payload["external_id"], "7000012992")
        self.assertEqual(canonical_source_key("giz", "7000012992"), "giz:7000012992")
        self.assertEqual(payload["country"], "South Africa")
        self.assertEqual(payload["region"], "Africa")
        self.assertEqual(payload["buyer"], "GIZ South Africa")
        self.assertEqual(payload["procurement_category"], "Services")
        self.assertEqual(payload["sector"], "consulting")
        self.assertEqual(payload["deadline"].isoformat(), "2026-07-15T00:00:00+00:00")
        self.assertEqual(payload["source_metadata_json"]["email"], "ZA_Quotation@giz.de")
        self.assertIn("filetransfer.giz.de", payload["source_metadata_json"]["submission_method"])
        self.assertEqual(len(payload["attachments"]), 2)
        self.assertEqual(payload["attachments"][0]["source_document_type"], "pdf")
        self.assertTrue(
            payload["attachments"][0]["source_document_url"].startswith(
                "https://www.giz.de/sites/default/files/"
            )
        )

    def test_parse_flat_download_page_with_deadline_filename(self) -> None:
        payloads = parse_giz_tender_page(
            GIZ_FLAT_DOWNLOAD_FIXTURE,
            page_url="https://www.giz.de/en/regions/asia/viet-nam/tenders",
        )

        self.assertEqual(len(payloads), 1)
        payload = payloads[0]
        self.assertEqual(payload["external_id"], "7000015155")
        self.assertEqual(payload["country"], "Viet Nam")
        self.assertEqual(payload["region"], "Asia")
        self.assertEqual(payload["deadline"].isoformat(), "2026-07-23T00:00:00+00:00")
        self.assertEqual(payload["attachments"][0]["source_document_type"], "docx")

    def test_country_page_skips_generated_page_ids_and_listing_placeholders(self) -> None:
        payloads = parse_giz_tender_page(
            """
            <main><h1>Ghana</h1>
              <div class="list-item__wrapper">
                <div class="list-item__meta">Deadline: 14.07.2026</div>
                <div class="list-item__title"><span>Procurement of Services without official id</span></div>
              </div>
              <div class="list-item__wrapper">
                <div class="list-item__meta">Deadline: 17.07.2026</div>
                <div class="list-item__title"><span>Bidding List</span></div>
                <div class="download"><div class="download__title"><span>7000014926-file.pdf</span></div><a href="/sites/default/files/7000014926-file.pdf"></a></div>
              </div>
            </main>
            """,
            page_url="https://www.giz.de/en/regions/africa/ghana/tenders",
        )

        self.assertEqual(payloads, [])

    def test_parse_eproc_listing_keeps_only_active_procurement_rows(self) -> None:
        rows = _parse_eproc_listing_page(
            GIZ_EPROC_LIST_FIXTURE,
            page_url="https://ausschreibungen.giz.de/Satellite/company/welcome.do",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Workstations und Peripheriegeräte für Usbekistan")
        self.assertEqual(rows[0]["deadline"].isoformat(), "2026-07-23T00:00:00+00:00")
        self.assertIn("projectForwarding.do?pid=51442", rows[0]["source_url"])

    def test_discovers_procedure_information_link_from_project_html(self) -> None:
        self.assertEqual(
            _discover_procedure_information_url(
                GIZ_EPROC_PROJECT_FIXTURE,
                project_url="https://ausschreibungen.giz.de/Satellite/public/company/project/CX/de/overview?0",
            ),
            "https://ausschreibungen.giz.de/Satellite/public/company/project/CX/de/processdata/eforms",
        )

    def test_extracts_eproc_contact_submission_and_geography(self) -> None:
        metadata = _extract_eproc_procedure_metadata(
            GIZ_EPROC_PROCEDURE_FIXTURE,
            procedure_url="https://ausschreibungen.giz.de/Satellite/public/company/project/CX/de/processdata/generic?2",
            project_url="https://ausschreibungen.giz.de/Satellite/public/company/project/CX/de/overview?0",
            title="Workstations und Peripheriegeräte für Usbekistan",
        )

        self.assertEqual(metadata["buyer_agency"], "Deutsche Gesellschaft für Internationale Zusammenarbeit (GIZ) GmbH")
        self.assertEqual(metadata["email"], "iana.mengel@giz.de")
        self.assertEqual(metadata["phone"], "+49 6196796441")
        self.assertEqual(metadata["submission_deadline"], "23.07.2026 12:00 Uhr")
        self.assertEqual(metadata["submission_method"], "Electronic submission through the GIZ e-procurement platform")
        self.assertEqual(metadata["procedure_type"], "Öffentliche Ausschreibung")
        self.assertEqual(metadata["country"], "Uzbekistan")
        self.assertEqual(metadata["region"], "Central Asia")

    def test_normalize_maps_safe_fields_and_attachment_metadata(self) -> None:
        raw = parse_giz_tender_page(
            GIZ_PAGE_FIXTURE,
            page_url="https://www.giz.de/en/regions/africa/south-africa/tenders",
        )[0]

        normalized = GizTenderSource(source_pages=[]).normalize(raw)

        self.assertEqual(normalized.source_system, "giz")
        self.assertEqual(normalized.external_id, "7000012992")
        self.assertEqual(normalized.category, "GIZ")
        self.assertEqual(normalized.currency, "EUR")
        self.assertEqual(normalized.source_metadata_json["buyer_agency"], "GIZ South Africa")
        self.assertIn("attachments", normalized.source_metadata_json)

    def test_duplicate_canonical_key_is_stable_for_same_reference(self) -> None:
        first = parse_giz_tender_page(
            GIZ_PAGE_FIXTURE,
            page_url="https://www.giz.de/en/regions/africa/south-africa/tenders",
        )[0]
        second = parse_giz_tender_page(
            GIZ_PAGE_FIXTURE.replace("TOR.pdf", "Terms-Reference.pdf"),
            page_url="https://www.giz.de/en/regions/africa/south-africa/tenders",
        )[0]

        self.assertEqual(first["external_id"], second["external_id"])
        self.assertEqual(
            canonical_source_key("giz", first["external_id"]),
            canonical_source_key("giz", second["external_id"]),
        )

    def test_giz_attachment_upsert_rejects_uzex_tender_scope(self) -> None:
        tender = SimpleNamespace(
            id="tender-id",
            source_system="uzex",
            canonical_source_key="uzex:10002898",
        )

        async def run_check() -> None:
            await GizTenderSource(source_pages=[]).upsert_attachments(
                SimpleNamespace(),
                tender=tender,
                attachments=[],
            )

        with self.assertRaises(ValueError):
            asyncio.run(run_check())

    def test_country_page_failure_yields_partial_rows_from_healthy_page(self) -> None:
        class PartialGizSource(GizTenderSource):
            async def _request(self, client, method, url, **kwargs):  # type: ignore[override]
                if "failed" in url:
                    raise TimeoutError("simulated country-page timeout")
                return SimpleNamespace(content=GIZ_PAGE_FIXTURE.encode(), url=url)

        source = PartialGizSource(
            source_pages=(
                "https://www.giz.de/en/regions/africa/failed/tenders",
                "https://www.giz.de/en/regions/africa/south-africa/tenders",
            ),
            include_eproc=False,
            request_delay_seconds=0,
        )
        rows = asyncio.run(source.list_opportunities())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["external_id"], "7000012992")
        self.assertEqual(source.last_failure_details[0]["stage"], "country_listing")
        self.assertTrue(source.last_failure_details[0]["retryable"])

    def test_valid_zero_result_configuration_is_not_a_failure(self) -> None:
        source = GizTenderSource(source_pages=[], include_eproc=False)

        rows = asyncio.run(source.list_opportunities())

        self.assertEqual(rows, [])
        self.assertEqual(source.last_failure_details, [])


if __name__ == "__main__":
    unittest.main()
