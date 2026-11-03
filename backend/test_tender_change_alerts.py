"""Tender-change alerts: a pursued tender's new deadline, amendment or new document marks
its analysis out of date and reaches the firm in the inbox and by e-mail.

Pure rules first, then the migration, then a Postgres scenario through the real source
refresh persistence and the existing outbox publisher.
"""

from __future__ import annotations

import asyncio
from dataclasses import fields
from datetime import timedelta
import hashlib

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.agents.pursuit_analyzer import VerifiedFact
from app.core.config import settings
from app.models.all_models import Tender, TenderDocument
from app.models.base import TenderEngagementOrigin, TenderEngagementStatus
from app.models.communications import NotificationDelivery, NotificationEvent, NotificationOutbox
from app.models.email import EmailDelivery
from app.models.tenancy import Membership, OrganizationPursuit
from app.models.tender_changes import TenderChange
from app.services import pursuit_analysis as analysis_service
from app.services.email_templates import LOCALES, render_email
from app.services.notifications import CommunicationsError, publish_outbox_batch, validate_system_event
from app.services.pursuit_analysis import get_analysis_run
from app.services.pursuits import get_or_create_source_pursuit
from app.services.tender_changes import change_kinds_for_fields
from app.services.tender_sources.base import (
    SOURCE_OWNED_TENDER_FIELDS,
    CanonicalDocument,
    NormalizedTender,
    persist_document_descriptors,
    persist_tender_batch,
)
from scripts import test_s0_5b4_baseline as support
from test_d2_01_own_experience import SUBSTATION, _fact
from test_r3_02_experience_changed import _run
from test_w2_organization_pursuit_foundation import W1_HEAD, _seed_w1


REVISION = "20261103_0001_tender_change_alerts"
PREVIOUS = "20261025_0001_b1_billing"
HEAD = REVISION


# ---- pure rules -----------------------------------------------------------------------------------

def test_only_deadline_and_notice_fields_are_material() -> None:
    assert change_kinds_for_fields(["deadline"]) == {"DEADLINE"}
    assert change_kinds_for_fields(["description", "budget"]) == {"AMENDMENT"}
    assert change_kinds_for_fields(["deadline", "title"]) == {"DEADLINE", "AMENDMENT"}
    assert change_kinds_for_fields(["source_metadata_json", "scrape_status", "last_synced_at", "source_url"]) == set()


def test_event_contract_and_email_in_every_locale() -> None:
    payload = {
        "organization_id": "11111111-1111-4111-8111-111111111111", "pursuit_id": "22222222-2222-4222-8222-222222222222",
        "tender_id": "33333333-3333-4333-8333-333333333333", "tender_change_id": "44444444-4444-4444-8444-444444444444",
        "change_kinds": ["DEADLINE", "DOCUMENT"],
    }
    contract = dict(event_type="TENDER_CHANGED", category="TENDER_ALERT", template_key="notifications.tender_changed")
    validate_system_event(**contract, payload=payload, dedupe_key="tender-change:x")
    for bad in ([], ["SOMETHING"], "DEADLINE"):
        with pytest.raises(CommunicationsError):
            validate_system_event(**contract, payload={**payload, "change_kinds": bad}, dedupe_key="tender-change:x")
    subjects = set()
    for locale in LOCALES:
        rendered = render_email("TENDER_CHANGED", locale, payload, app_url="https://app.example")
        link = f"https://app.example/dashboard/pursuits/{payload['pursuit_id']}?tab=requirements"
        assert link in rendered.text and f'href="{link}"' in rendered.html
        assert ('dir="rtl"' in rendered.html) == (locale == "ar")
        assert "{changes}" not in rendered.text and "DEADLINE" not in rendered.text
        subjects.add(rendered.subject)
    assert len(subjects) == 4
    english = render_email("TENDER_CHANGED", "en", payload, app_url="https://app.example").text
    assert "(new deadline, new document)" in english


# ---- migration ------------------------------------------------------------------------------------

def test_migration_is_additive_reversible_and_drift_free() -> None:
    async def scenario() -> None:
        database = support.database_name("tender_change_migration")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", PREVIOUS)
            await asyncio.to_thread(support.alembic, database, "upgrade", REVISION)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('tender_changes')")
                definition = await connection.fetchval(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_email_delivery_kind'"
                )
                assert "TENDER_CHANGED" in definition and "BILLING_SUSPENDED" in definition
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "downgrade", PREVIOUS)
            connection = await support.database_connection(database)
            try:
                assert await connection.fetchval("SELECT to_regclass('tender_changes')") is None
                definition = await connection.fetchval(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_email_delivery_kind'"
                )
                assert "TENDER_CHANGED" not in definition and "BILLING_SUSPENDED" in definition
            finally:
                await connection.close()
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            check = await asyncio.to_thread(support.alembic, database, "check", success=False)
            assert check.returncode == 0, check.stderr or check.stdout
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


# ---- Postgres scenario ----------------------------------------------------------------------------

def test_source_changes_flag_the_analysis_and_alert_the_firm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        database = support.database_name("tender_change_alerts")
        await support.create_database(database)
        try:
            await support.raw_baseline(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", W1_HEAD)
            ids = await _seed_w1(database)
            await asyncio.to_thread(support.alembic, database, "upgrade", HEAD)
            connection = await support.database_connection(database)
            try:
                org_a = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_a"])
                org_b = await connection.fetchval("SELECT id FROM organizations WHERE legacy_company_profile_id=$1", ids["profile_b"])
                owner_a = await connection.fetchval("SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", org_a, ids["user_a"])
                owner_b = await connection.fetchval("SELECT id FROM memberships WHERE organization_id=$1 AND user_id=$2", org_b, ids["user_b"])
            finally:
                await connection.close()
            engine = create_async_engine(support.target_url(database), pool_size=8)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                await _flow(sessions, ids, org_a, org_b, owner_a, owner_b, monkeypatch)
            finally:
                await engine.dispose()
        finally:
            await support.drop_database(database)

    asyncio.run(scenario())


def _snapshot(tender: Tender, **changes) -> NormalizedTender:
    """The tender exactly as stored, as a source would deliver it, with ``changes``."""
    accepted = {item.name for item in fields(NormalizedTender)}
    values = {name: getattr(tender, name) for name in SOURCE_OWNED_TENDER_FIELDS if name in accepted}
    values["budget"] = float(values["budget"] or 0)
    return NormalizedTender(**{**values, **changes})


async def _outbox(db) -> list[NotificationOutbox]:
    return list((await db.scalars(
        select(NotificationOutbox).where(NotificationOutbox.event_type == "TENDER_CHANGED")
        .order_by(NotificationOutbox.created_at, NotificationOutbox.id)
    )).all())


async def _flow(sessions, ids, org_a, org_b, owner_a, owner_b, monkeypatch) -> None:
    tender_id = ids["tender"]
    async with sessions() as db:
        pursuit_a = (await get_or_create_source_pursuit(
            db, organization_id=org_a, actor_user_id=ids["user_a"], actor_membership_id=owner_a, tender_id=tender_id,
            stage=TenderEngagementStatus.EVALUATING, legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
        )).pursuit.id
        # Organization B pursues the same tender but never analyzed it.
        await get_or_create_source_pursuit(
            db, organization_id=org_b, actor_user_id=ids["user_b"], actor_membership_id=owner_b, tender_id=tender_id,
            stage=TenderEngagementStatus.SAVED, legacy_origin=TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
        )
        document = TenderDocument(
            tender_id=tender_id, file_url="tca.pdf", file_type="pdf", source_document_url="https://example.invalid/tca.pdf",
            source_document_type="RFP", sha256=hashlib.sha256(SUBSTATION.encode()).hexdigest(), parsed_text=SUBSTATION,
        )
        db.add(document)
        await db.commit()
        document_id = document.id
        tender = await db.get(Tender, tender_id)
        # Before any analysis a change alerts nobody and records nothing.
        await persist_tender_batch(db, [_snapshot(tender, description="Before analysis")])
        await db.commit()
        assert await db.scalar(select(func.count(TenderChange.id))) == 0 and await _outbox(db) == []

    async def extracted(sealed, language):
        fact = _fact(original_quote=SUBSTATION, normalized_text=SUBSTATION)
        return [VerifiedFact(sealed[0].pack_item_id, fact, 0, len(SUBSTATION), None, 1)]

    monkeypatch.setattr(analysis_service.pursuit_analyzer, "analyze_pack_items", extracted)
    first = await _run(sessions, ids, org_a, owner_a, pursuit_a, document_id)

    async with sessions() as db:
        analysis = await get_analysis_run(db, organization_id=org_a, pursuit_id=pursuit_a, include_company_evidence=True)
        assert analysis.status == "COMPLETED" and analysis.tender_changed is False and analysis.tender_change_kinds == []
        tender = await db.get(Tender, tender_id)
        # Bookkeeping alone (metadata, scrape status) is not a change for the firm.
        await persist_tender_batch(db, [_snapshot(tender, source_metadata_json={"seen": 1})])
        await db.commit()
        assert await db.scalar(select(func.count(TenderChange.id))) == 0

        # New deadline and an amended notice: one change, one event per active member of A.
        tender = await db.get(Tender, tender_id)
        await persist_tender_batch(db, [_snapshot(
            tender, deadline=tender.deadline + timedelta(days=14), description="Amended: 330 kV substations",
        )])
        await db.commit()
        [change] = (await db.scalars(select(TenderChange))).all()
        assert change.tender_id == tender_id and change.change_kinds == ["AMENDMENT", "DEADLINE"]
        members_a = set((await db.scalars(
            select(Membership.user_id).where(Membership.organization_id == org_a, Membership.state == "ACTIVE")
        )).all())
        staged = await _outbox(db)
        assert {row.user_id for row in staged} == members_a and len(staged) == len(members_a)
        assert ids["user_b"] not in {row.user_id for row in staged}
        assert staged[0].category == "TENDER_ALERT" and staged[0].template_key == "notifications.tender_changed"
        assert staged[0].payload == {
            "organization_id": str(org_a), "pursuit_id": str(pursuit_a), "tender_id": str(tender_id),
            "tender_change_id": str(change.id), "change_kinds": ["AMENDMENT", "DEADLINE"],
        }

        # The analysis read now says it is out of date, in a stable order; the old run stays readable.
        analysis = await get_analysis_run(db, organization_id=org_a, pursuit_id=pursuit_a, include_company_evidence=True)
        assert analysis.tender_changed is True and analysis.tender_change_kinds == ["DEADLINE", "AMENDMENT"]
        assert analysis.analysis_run_id == first and analysis.requirements

        # The same snapshot again is unchanged: nothing new.
        tender = await db.get(Tender, tender_id)
        await persist_tender_batch(db, [_snapshot(tender)])
        await db.commit()
        assert await db.scalar(select(func.count(TenderChange.id))) == 1 and len(await _outbox(db)) == len(members_a)

        # A new source document is a DOCUMENT change.
        await persist_document_descriptors(db, source_system=tender.source_system, tender=tender, documents=[
            CanonicalDocument(source_system=tender.source_system, source_document_url="https://example.invalid/addendum-1.pdf",
                              file_type="pdf", source_document_type="ADDENDUM"),
        ])
        await db.commit()
        analysis = await get_analysis_run(db, organization_id=org_a, pursuit_id=pursuit_a)
        assert analysis.tender_change_kinds == ["DEADLINE", "AMENDMENT", "DOCUMENT"]
        assert len(await _outbox(db)) == 2 * len(members_a)

    # Publishing: the inbox (deduplicated on replay) and, with SMTP configured, the e-mail.
    monkeypatch.setattr(settings, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "SMTP_FROM", "Plasma <noreply@plasma.test>")
    async with sessions() as db:
        assert await publish_outbox_batch(db) >= 2 * len(members_a)
        await db.commit()
        assert await publish_outbox_batch(db) == 0
        inbox = (await db.execute(
            select(NotificationDelivery.user_id, NotificationEvent.payload)
            .join(NotificationEvent, NotificationEvent.id == NotificationDelivery.event_id)
            .where(NotificationEvent.event_type == "TENDER_CHANGED")
        )).all()
        assert len(inbox) == 2 * len(members_a) and {row.user_id for row in inbox} == members_a
        mails = list((await db.scalars(select(EmailDelivery).where(EmailDelivery.kind == "TENDER_CHANGED"))).all())
        assert mails and {mail.user_id for mail in mails} <= members_a and ids["user_a"] in {mail.user_id for mail in mails}
        assert all(mail.category == "ANALYSIS" and mail.state == "PENDING" for mail in mails)

    # A re-run seals the current tender: the new run is current again.
    async with sessions() as db:
        document = TenderDocument(
            tender_id=tender_id, file_url="tca2.pdf", file_type="pdf", source_document_url="https://example.invalid/tca2.pdf",
            source_document_type="RFP", sha256=hashlib.sha256(b"tca2" + SUBSTATION.encode()).hexdigest(), parsed_text=SUBSTATION,
        )
        db.add(document)
        await db.commit()
        rerun_document = document.id
    second = await _run(sessions, ids, org_a, owner_a, pursuit_a, rerun_document)
    async with sessions() as db:
        latest = await get_analysis_run(db, organization_id=org_a, pursuit_id=pursuit_a)
        assert latest.analysis_run_id == second and latest.tender_changed is False
        old = await get_analysis_run(db, organization_id=org_a, pursuit_id=pursuit_a, run_id=first)
        assert old.tender_changed is True

        # A dismissed pursuit is no longer pursued: later changes alert nobody.
        pursuit = await db.get(OrganizationPursuit, pursuit_a)
        pursuit.stage = TenderEngagementStatus.DISMISSED
        await db.commit()
        before = len(await _outbox(db))
        tender = await db.get(Tender, tender_id)
        await persist_tender_batch(db, [_snapshot(tender, deadline=tender.deadline + timedelta(days=7))])
        await db.commit()
        assert len(await _outbox(db)) == before
