"""P1-03: done-for-you onboarding import (references, experts, assignments) from XLSX or CSV.

Template round trip, reader limits, row validation, duplicate detection, the SHA-256 guard,
one-transaction commit (new firms, references, experts, CV versions, assignments for new and
existing experts), the D2-02 CSV headers, and explore organizations refused.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from uuid import uuid4

from fastapi import HTTPException, UploadFile
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.endpoints import candidates as candidate_endpoints
from app.models.candidate_retrieval import CVVersion, Expert, Firm, ProjectReference
from app.models.company import CompanyProfile
from app.models.user import User
from app.services import library_import as li
from app.services.organization_context import ensure_profile_organization
from scripts import test_s0_5b4_baseline as support

HEAD = "20261023_0001_p2_partner_finder"


def _xlsx(sheets: dict[str, list[list]], *, shared: bool = True) -> bytes:
    """A minimal workbook the way Excel writes it (shared strings), independent of the template writer."""
    strings: list[str] = []

    def cell(ref, value):
        if value is None:
            return ""
        if isinstance(value, (int, float)):
            return f'<c r="{ref}"><v>{value}</v></c>'
        if shared:
            strings.append(str(value))
            return f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        sheet_entries, rels = [], []
        for index, (name, rows) in enumerate(sheets.items(), start=1):
            body = "".join(
                f'<row r="{r}">' + "".join(cell(f"{chr(65 + c)}{r}", v) for c, v in enumerate(row)) + "</row>"
                for r, row in enumerate(rows, start=1))
            archive.writestr(f"xl/worksheets/sheet{index}.xml",
                             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                             f"<sheetData>{body}</sheetData></worksheet>")
            sheet_entries.append(f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>')
            rels.append(f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>')
        archive.writestr("xl/workbook.xml",
                         '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                         f"<sheets>{''.join(sheet_entries)}</sheets></workbook>")
        archive.writestr("xl/_rels/workbook.xml.rels",
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         f"{''.join(rels)}</Relationships>")
        sst = "".join(f"<si><t>{s}</t></si>" for s in strings)
        archive.writestr("xl/sharedStrings.xml",
                         f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{sst}</sst>')
    return buffer.getvalue()


REF_HEADERS = ["firm", "project_name*", "client_name", "country", "service", "sector", "role*", "contract_value", "currency",
               "value_basis", "share_percent", "start_date", "completion_date", "status", "scope"]
EXPERT_HEADERS = ["full_name*", "position", "years_experience", "education", "qualifications", "specializations", "languages"]
ASSIGN_HEADERS = ["full_name*", "role*", "project*", "client", "country", "start", "end", "description"]


def _workbook() -> bytes:
    return _xlsx({
        "Instructions": [["ignored"]],
        "References": [
            REF_HEADERS,
            [None, "Water supply feasibility, Bukhara", "Ministry of Water", "Uzbekistan", "Feasibility study", "Water",
             "Lead", 480000, "USD", "Firm share", 100, "2021-03", "2022-06", "Completed", "Hydraulic modelling and design."],
            ["Partner Engineering GmbH", "Grid study, Samarkand", "REC", "Uzbekistan", "Study", "Energy", "Subconsultant",
             "1 250 000,50", "EUR", "Contract total", "", 44197, 44562, "", ""],         # Excel date serials, spaced number
            [None, "Water supply feasibility, Bukhara", None, None, None, None, "Lead", None, None, None, None, None, None, None, None],
            [None, "", None, None, None, None, "Boss", 100, None, None, 140, "soon", None, None, None],
        ],
        "Experts": [
            EXPERT_HEADERS,
            ["Dilnoza Karimova", "Team Leader / Water Engineer", 16, "MSc Water Engineering; BSc Civil", "FIDIC",
             "Distribution networks; NRW", "English; Russian; Uzbek"],
            ["Existing Expert", "Economist", 9, None, None, None, "English"],
            ["dilnoza  karimova", None, None, None, None, None, None],
        ],
        "Expert assignments": [
            ASSIGN_HEADERS,
            ["Dilnoza Karimova", "Team Leader", "Bukhara water supply", "MoWR", "Uzbekistan", "2021-03", "2022-06", "Design"],
            ["Existing Expert", "Economist", "Tariff study", None, "Uzbekistan", "2019-01", "present", None],
            ["Nobody Known", "Engineer", "Something", None, None, None, None, None],
        ],
    })


# ---- pure rules -----------------------------------------------------------------------------------

def test_template_round_trip_and_csv_templates() -> None:
    template = li.build_template_xlsx()
    with zipfile.ZipFile(io.BytesIO(template)) as archive:
        assert archive.testzip() is None and "xl/styles.xml" in archive.namelist()
        assert b"dataValidation" in archive.read("xl/worksheets/sheet2.xml")      # role / basis / status drop-downs
    fmt, tables, warnings = li.parse_upload("plasma-library-import-template.xlsx", template)
    assert fmt == "xlsx" and all(tables[kind] == [] for kind in li.KINDS) and warnings == []
    for kind in li.KINDS:
        csv_bytes = li.build_template_csv(kind)
        assert csv_bytes.startswith(b"\xef\xbb\xbf")
        header = csv_bytes.decode("utf-8-sig").strip().split(",")
        assert [h.rstrip("*") for h in header] == [name for name, _, _ in li.COLUMNS[kind]]


def test_reader_limits_and_hostile_files() -> None:
    with pytest.raises(li.ImportFileError):
        li.parse_upload("x.xlsx", b"")
    with pytest.raises(li.ImportFileError):
        li.parse_upload("x.xlsx", b"PK" + b"0" * 100)                                  # not a zip
    with pytest.raises(li.ImportFileError):
        li.parse_upload("x.csv", b"a" * (li.MAX_UPLOAD_BYTES + 1))
    hostile = io.BytesIO()
    with zipfile.ZipFile(hostile, "w") as archive:
        archive.writestr("xl/workbook.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><workbook/>')
    with pytest.raises(li.ImportFileError):
        li.parse_upload("x.xlsx", hostile.getvalue())
    with pytest.raises(li.ImportFileError):
        li.parse_upload("x.csv", b"col_a,col_b\n1,2\n")                               # no template sheet
    too_many = "project_name,role\n" + "".join(f"P{i},Lead\n" for i in range(li.MAX_ROWS_PER_SHEET + 1))
    with pytest.raises(li.ImportFileError):
        li.parse_upload("x.csv", too_many.encode())


def test_csv_parsing_with_d2_02_headers_semicolons_and_cp1251() -> None:
    d2 = ("project_name,client_name,country,sector,service,role,contract_share_percent,contract_value,contract_currency,"
          "value_basis,start_date,completion_date,completion_state,relevant_scope,evidence_state\n"
          "Substation design,REC,Uzbekistan,Energy,Design,LEAD,,250000,USD,CONTRACT_TOTAL,2021-03-01,2022-11-30,COMPLETED,Two substations,REVIEWED\n")
    fmt, tables, warnings = li.parse_upload("refs.csv", d2.encode())
    assert fmt == "csv" and warnings == [] and len(tables["references"]) == 1
    row = li._validate_reference(tables["references"][0], {"import": "t"})
    assert not row.errors and row.payload["completion_state"] == "COMPLETED" and row.payload["evidence_state"] == "UNVERIFIED"
    semi = "full_name;languages;education\nАзиз Каримов;English | Russian;MSc\n".encode("cp1251")
    _, tables, _ = li.parse_upload("experts.csv", semi)
    expert = li._validate_expert(tables["experts"][0], {"import": "t"})
    assert expert.payload["expert"]["display_name"] == "Азиз Каримов" and expert.payload["expert"]["languages"] == ["English", "Russian"]


def test_row_validation_messages() -> None:
    _, tables, _ = li.parse_upload("w.xlsx", _workbook())
    refs = [li._validate_reference(r, {"import": "t"}) for r in tables["references"]]
    assert not refs[0].errors and refs[0].payload["contract_value"] == 480000 and str(refs[0].payload["start_date"]) == "2021-03-01"
    assert not refs[1].errors and float(refs[1].payload["contract_value"]) == 1250000.5
    assert str(refs[1].payload["start_date"]) == "2021-01-01" and refs[1].payload["role"] == "SUBCONSULTANT"
    assert refs[1].payload["completion_state"] == "COMPLETED"                          # past completion date
    bad = refs[3].errors
    assert any(e.startswith("project_name") for e in bad) and any(e.startswith("role") for e in bad)
    assert any(e.startswith("share_percent") for e in bad) and any(e.startswith("start_date") for e in bad)
    assert any(e.startswith("currency") for e in bad) and any(e.startswith("value_basis") for e in bad)


# ---- Postgres scenario ----------------------------------------------------------------------------

def test_preview_and_commit_in_one_transaction() -> None:
    async def scenario() -> None:
        database = support.database_name("p1_03_import")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            engine = create_async_engine(support.target_url(database), pool_size=4)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _scenario(sessions)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


async def _org(db, email: str, approval: str):
    user = User(google_id=f"g-{uuid4()}", email=email, name=email, platform_role="pilot_user", approval_status="approved")
    db.add(user)
    await db.flush()
    profile = CompanyProfile(user_id=user.id, created_by_user_id=user.id, company_name=f"Co {email}", approval_status=approval,
                             pilot_status="scoped_pilot")
    db.add(profile)
    await db.flush()
    context = await ensure_profile_organization(db, profile=profile)
    await db.commit()
    return user, context.organization


def _upload(content: bytes, name: str = "library.xlsx") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=name)


async def _scenario(sessions) -> None:
    async with sessions() as db:
        owner, org = await _org(db, "owner@firm.example", "approved")
        explorer, _ = await _org(db, "explorer@firm.example", "pending")
        db.add(Expert(scope="ORGANIZATION_PRIVATE", owner_organization_id=org.id, display_name="Existing Expert",
                      qualifications=[], languages=[], specializations=[], consent_state="NOT_REQUIRED_PRIVATE",
                      evidence_state="UNVERIFIED", source_provenance={}, created_by_user_id=owner.id))
        await db.commit()
    content = _workbook()

    # Explore organizations cannot import (no organization context).
    async with sessions() as db:
        with pytest.raises(HTTPException) as refused:
            await candidate_endpoints.library_import_preview(file=_upload(content), x_organization_id=None, current_user=explorer, db=db)
        assert refused.value.status_code == 404

    async with sessions() as db:
        preview = await candidate_endpoints.library_import_preview(file=_upload(content), x_organization_id=None, current_user=owner, db=db)
    assert preview["counts"] == {
        "references": {"rows": 4, "new": 2, "duplicates": 1, "errors": 1},
        "experts": {"rows": 3, "new": 1, "duplicates": 2, "errors": 0},
        "assignments": {"rows": 3, "new": 2, "duplicates": 0, "errors": 1},
    }
    statuses = [(r["kind"], r["row"], r["status"], r["duplicate"]) for r in preview["rows"]]
    assert ("references", 4, "DUPLICATE", "repeated in this file") in statuses
    assert ("experts", 3, "DUPLICATE", "already in your library") in statuses
    assert ("experts", 4, "DUPLICATE", "repeated in this file") in statuses
    async with sessions() as db:
        assert await db.scalar(select(func.count(ProjectReference.id))) == 0              # preview writes nothing

    # The commit refuses a different file than the one previewed.
    async with sessions() as db:
        with pytest.raises(HTTPException) as mismatch:
            await candidate_endpoints.library_import_commit(
                file=_upload(content), expected_sha256="0" * 64, x_organization_id=None, current_user=owner, db=db)
        assert mismatch.value.status_code == 422 and "previewed" in mismatch.value.detail["message"]

    async with sessions() as db:
        result = await candidate_endpoints.library_import_commit(
            file=_upload(content), expected_sha256=preview["file_sha256"], x_organization_id=None, current_user=owner, db=db)
    assert result == {
        "file_sha256": preview["file_sha256"], "references_created": 2, "partner_firms_created": 1, "experts_created": 1,
        "cv_versions_created": 2, "assignments_attached": 2, "skipped_duplicates": 3, "skipped_errors": 2,
    }
    async with sessions() as db:
        self_firm = await db.scalar(select(Firm).where(Firm.organization_id == org.id))
        partner = await db.scalar(select(Firm).where(Firm.owner_organization_id == org.id, Firm.organization_id.is_(None)))
        assert partner.display_name == "Partner Engineering GmbH" and partner.source_type == "EXPLICIT_IMPORT"
        refs = (await db.scalars(select(ProjectReference).order_by(ProjectReference.project_name))).all()
        assert [(r.firm_id, r.project_name) for r in refs] == [
            (partner.id, "Grid study, Samarkand"), (self_firm.id, "Water supply feasibility, Bukhara")]
        assert all(r.evidence_state == "UNVERIFIED" and r.evidence_provenance["file_sha256"] == preview["file_sha256"] for r in refs)
        assert refs[1].evidence_provenance["row"] == 2 and refs[1].contract_currency == "USD"
        new_expert = await db.scalar(select(Expert).where(Expert.display_name == "Dilnoza Karimova"))
        assert new_expert.owner_organization_id == org.id and new_expert.consent_state == "NOT_REQUIRED_PRIVATE"
        assert "Team Leader / Water Engineer" in new_expert.specializations and "English" in new_expert.languages
        cv = await db.scalar(select(CVVersion).where(CVVersion.expert_id == new_expert.id))
        assert cv.version_number == 1 and cv.assignments[0]["project"] == "Bukhara water supply"
        assert cv.education == [{"degree": "MSc Water Engineering"}, {"degree": "BSc Civil"}]
        existing = await db.scalar(select(Expert).where(Expert.display_name == "Existing Expert"))
        existing_cv = await db.scalar(select(CVVersion).where(CVVersion.expert_id == existing.id))
        assert existing_cv.version_number == 1 and existing_cv.assignments == [
            {"role": "Economist", "project": "Tariff study", "country": "Uzbekistan", "start": "2019-01", "end": "present"}]

    # Importing the same file again creates nothing (everything is a duplicate now).
    async with sessions() as db:
        again = await candidate_endpoints.library_import_preview(file=_upload(content), x_organization_id=None, current_user=owner, db=db)
    assert again["counts"]["references"]["new"] == 0 and again["counts"]["experts"]["new"] == 0
    # Assignments already on an expert's CV are duplicates too, so the preview promises only what Import adds.
    assert again["counts"]["assignments"] == {"rows": 3, "new": 0, "duplicates": 2, "errors": 1}
    assert {r["duplicate"] for r in again["rows"] if r["kind"] == "assignments" and r["status"] == "DUPLICATE"} == {
        "already on this expert's CV"}

    # The template endpoint serves both formats.
    xlsx = await candidate_endpoints.library_import_template(format="xlsx")
    assert xlsx.media_type == candidate_endpoints.IMPORT_XLSX_TYPE and xlsx.body[:2] == b"PK"
    csv_template = await candidate_endpoints.library_import_template(format="csv", kind="experts")
    assert b"full_name*" in csv_template.body
    with pytest.raises(HTTPException):
        await candidate_endpoints.library_import_template(format="pdf")
