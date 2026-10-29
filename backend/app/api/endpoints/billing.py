"""B1: billing. The customer's checkout and billing page, the Polar webhook, the admin billing console."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_approved_user, require_operator
from app.core.security import authenticated_dependency
from app.db.session import get_db
from app.models.billing import BillingInvoice, BillingOrder, OnboardingTask
from app.models.tenancy import Organization
from app.models.user import User
from app.schemas.billing import (
    AdminBillingCustomer,
    AdminBillingDetail,
    BillingCustomerIn,
    BillingCustomerOut,
    BillingOverrideRequest,
    BillingOverview,
    CatalogResponse,
    CheckoutRequest,
    CheckoutResponse,
    MarkPaidRequest,
    OnboardingDoneRequest,
    OnboardingTaskOut,
    AdminInvoiceRequest,
    OfferCreateRequest,
    OfferCreateResponse,
    OrderStatusResponse,
    PortalResponse,
    QuoteResponse,
    RefundNoteRequest,
    TermsResponse,
    WebhookHealth,
)
from app.services import billing as service
from app.services.admin_alerts import kick_admin_alerts
from app.services.billing_invoice_pdf import render_invoice_pdf
from app.services.billing_polar import WebhookSignatureError
from app.services.email_notifications import app_url
from app.services.organization_context import (
    OrganizationAccessDeniedError,
    OrganizationContextRequiredError,
    resolve_organization_context,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[authenticated_dependency(), Depends(require_approved_user)])
webhook_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_operator)])


async def _context(db: AsyncSession, user: User, organization_id: UUID | None, *, owner: bool = False):
    # Explore organizations buy here too (that is how a pilot starts).
    try:
        context = await resolve_organization_context(db, user_id=user.id, organization_id=organization_id,
                                                     allow_explore=True)
    except OrganizationContextRequiredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organization not found") from exc
    if owner and context.membership.role.value != "OWNER":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
            "code": "owner_required", "message": "Only an owner of the organization can buy or change billing details"})
    return context


async def _fail(db: AsyncSession, exc: service.BillingError) -> None:
    await db.rollback()
    raise HTTPException(exc.status_code, detail=exc.detail()) from exc


@router.get("/catalog", response_model=CatalogResponse)
async def billing_catalog() -> CatalogResponse:
    """Plans with prices, limits and features, and the products sold in the app."""
    return CatalogResponse(**service.catalog())


@router.get("/terms", response_model=TermsResponse)
async def billing_terms() -> TermsResponse:
    return TermsResponse(**service.terms())


@router.get("", response_model=BillingOverview)
async def billing_overview(
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> BillingOverview:
    context = await _context(db, current_user, x_organization_id)
    return BillingOverview(**await service.overview(db, context.organization))


@router.put("/customer", response_model=BillingCustomerOut)
async def save_billing_customer(
    payload: BillingCustomerIn,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> BillingCustomerOut:
    context = await _context(db, current_user, x_organization_id, owner=True)
    try:
        customer = await service.save_customer(db, organization=context.organization, user=current_user,
                                               data=payload.model_dump())
    except service.BillingError as exc:
        await _fail(db, exc)
    view = service.customer_view(customer)
    await db.commit()
    return BillingCustomerOut(**view)


@router.get("/quote", response_model=QuoteResponse)
async def billing_quote(
    product: str = Query(..., max_length=40), offer: str | None = Query(default=None, max_length=200),
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> QuoteResponse:
    """The price for this organization (with the pilot credit when it applies), and what blocks it."""
    context = await _context(db, current_user, x_organization_id)
    try:
        return QuoteResponse(**await service.quote(db, context.organization, product, offer_token=offer))
    except service.BillingError as exc:
        await _fail(db, exc)


@router.post("/checkout", response_model=CheckoutResponse)
async def billing_checkout(
    payload: CheckoutRequest, request: Request,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    """Card: a Polar checkout URL (the webhook activates). Bank transfer: the invoice; active now."""
    context = await _context(db, current_user, x_organization_id, owner=True)
    base = app_url()
    if payload.method == "card" and not base:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail={
            "code": "method_unavailable", "message": "Card payment is not available yet"})
    success_url = f"{base}/dashboard/billing/success?checkout_id={{CHECKOUT_ID}}" if base else ""
    try:
        result = await service.start_checkout(
            db, organization=context.organization, user=current_user, product_code=payload.product,
            method=payload.method, terms_version=payload.terms_version, terms_sha256=payload.terms_sha256,
            accepted=payload.accept_terms, ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"), success_url=success_url,
            offer_token=payload.offer, attribution=payload.attribution,
        )
    except service.BillingError as exc:
        await _fail(db, exc)
    await db.commit()
    kick_admin_alerts()
    return CheckoutResponse(**result)


@router.post("/portal", response_model=PortalResponse)
async def billing_portal(
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> PortalResponse:
    """Card customers: a link to Polar's customer portal (cancel or change the subscription, card, receipts)."""
    context = await _context(db, current_user, x_organization_id, owner=True)
    try:
        return PortalResponse(url=await service.customer_portal_url(db, organization=context.organization))
    except service.BillingError as exc:
        await _fail(db, exc)


@router.post("/cancel-renewal", response_model=BillingOverview)
async def billing_cancel_renewal(
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> BillingOverview:
    """Bank-transfer Pursuit Desk: ask not to renew. Recorded and audited; the team confirms."""
    context = await _context(db, current_user, x_organization_id, owner=True)
    try:
        await service.request_cancel_renewal(db, organization=context.organization, user=current_user)
    except service.BillingError as exc:
        await _fail(db, exc)
    await db.commit()
    kick_admin_alerts()
    return BillingOverview(**await service.overview(db, context.organization))


@router.get("/orders/{order_id}", response_model=OrderStatusResponse)
async def billing_order(
    order_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> OrderStatusResponse:
    context = await _context(db, current_user, x_organization_id)
    order = await db.get(BillingOrder, order_id)
    if order is None or order.organization_id != context.organization.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found")
    return OrderStatusResponse(order=service.order_view(order), plan=context.organization.plan,
                               billing_status=context.organization.billing_status)


@router.get("/orders", response_model=OrderStatusResponse)
async def billing_order_by_checkout(
    checkout_id: str = Query(..., max_length=100),
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> OrderStatusResponse:
    """The success page: the order of a Polar checkout (Polar appends checkout_id to the success URL)."""
    context = await _context(db, current_user, x_organization_id)
    order = await db.scalar(select(BillingOrder).where(
        BillingOrder.provider_checkout_id == checkout_id, BillingOrder.organization_id == context.organization.id))
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found")
    return OrderStatusResponse(order=service.order_view(order), plan=context.organization.plan,
                               billing_status=context.organization.billing_status)


@router.get("/invoices/{invoice_id}/pdf")
async def billing_invoice_pdf(
    invoice_id: UUID,
    x_organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> Response:
    context = await _context(db, current_user, x_organization_id)
    invoice = await db.get(BillingInvoice, invoice_id)
    if invoice is None or invoice.organization_id != context.organization.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return _pdf(invoice, await db.get(BillingOrder, invoice.order_id))


def _pdf(invoice: BillingInvoice, order: BillingOrder) -> Response:
    return Response(render_invoice_pdf(invoice, order), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{invoice.number}.pdf"', "Cache-Control": "private, no-store"})


# ---- Polar webhook (no session: the signature is the authentication) --------------------------

@webhook_router.post("/polar", status_code=status.HTTP_202_ACCEPTED)
async def polar_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    body = await request.body()
    headers = dict(request.headers)
    try:
        result = await service.receive_polar_webhook(db, body=body, headers=headers)
        await db.commit()
    except WebhookSignatureError as exc:
        await db.rollback()
        logger.warning("polar_webhook refused code=%s", exc)
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})
    except Exception as exc:  # processing failed: keep the delivery, let Polar retry
        await db.rollback()
        event_id = headers.get("webhook-id", "")
        logger.exception("polar_webhook failed event=%s", event_id)
        try:
            await service.record_webhook_failure(db, body=body, event_id=event_id, error=type(exc).__name__)
            await db.commit()
        except Exception:  # never mask the original failure
            await db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": "processing_failed"})
    if result["status"] == "processed":
        kick_admin_alerts()
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=result)


# ---- admin billing console ---------------------------------------------------------------------

async def _organization(db: AsyncSession, organization_id: UUID) -> Organization:
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return organization


@admin_router.get("/customers", response_model=list[AdminBillingCustomer])
async def admin_billing_customers(db: AsyncSession = Depends(get_db)) -> list[AdminBillingCustomer]:
    return [AdminBillingCustomer(**row) for row in await service.admin_customers(db)]


@admin_router.get("/onboarding", response_model=list[OnboardingTaskOut])
async def admin_onboarding(db: AsyncSession = Depends(get_db)) -> list[OnboardingTaskOut]:
    return [OnboardingTaskOut(**row) for row in await service.admin_onboarding_queue(db)]


@admin_router.get("/webhook-health", response_model=WebhookHealth)
async def admin_webhook_health(db: AsyncSession = Depends(get_db)) -> WebhookHealth:
    """Deploy 5.1: Polar deliveries by event type; a warning when no order.paid arrived 24 h after the first card
    checkout (the endpoint is then not subscribed to order.paid)."""
    return WebhookHealth(**await service.webhook_health(db))


@admin_router.get("/organizations/{organization_id}", response_model=AdminBillingDetail)
async def admin_billing_detail(organization_id: UUID, db: AsyncSession = Depends(get_db)) -> AdminBillingDetail:
    return AdminBillingDetail(**await service.admin_detail(db, await _organization(db, organization_id)))


@admin_router.get("/invoices/{invoice_id}/pdf")
async def admin_invoice_pdf(invoice_id: UUID, db: AsyncSession = Depends(get_db)) -> Response:
    invoice = await db.get(BillingInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return _pdf(invoice, await db.get(BillingOrder, invoice.order_id))


@admin_router.post("/invoices/{invoice_id}/mark-paid", response_model=AdminBillingDetail)
async def admin_mark_paid(
    invoice_id: UUID, payload: MarkPaidRequest,
    current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> AdminBillingDetail:
    invoice = await db.get(BillingInvoice, invoice_id, with_for_update=True)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    try:
        await service.mark_invoice_paid(db, invoice=invoice, reference=payload.reference, note=payload.note,
                                        actor_user=current_user)
    except service.BillingError as exc:
        await _fail(db, exc)
    await db.commit()
    kick_admin_alerts()
    return AdminBillingDetail(**await service.admin_detail(db, await _organization(db, invoice.organization_id)))


@admin_router.post("/orders/{order_id}/refund", response_model=AdminBillingDetail)
async def admin_refund(
    order_id: UUID, payload: RefundNoteRequest,
    current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> AdminBillingDetail:
    """Record a refund made outside the app (Polar dashboard or bank) with a note."""
    order = await db.get(BillingOrder, order_id, with_for_update=True)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found")
    try:
        await service.record_refund(db, order=order, note=payload.note, actor_user=current_user,
                                    downgrade=payload.downgrade)
    except service.BillingError as exc:
        await _fail(db, exc)
    await db.commit()
    kick_admin_alerts()
    return AdminBillingDetail(**await service.admin_detail(db, await _organization(db, order.organization_id)))


@admin_router.post("/organizations/{organization_id}/override", response_model=AdminBillingDetail)
async def admin_override(
    organization_id: UUID, payload: BillingOverrideRequest,
    current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> AdminBillingDetail:
    organization = await _organization(db, organization_id)
    try:
        await service.override_billing(
            db, organization=organization, plan=payload.plan, billing_status=payload.billing_status,
            reason=payload.reason, actor_user=current_user, plan_started_on=payload.plan_started_on,
            plan_ends_on=payload.plan_ends_on,
        )
    except service.BillingError as exc:
        await _fail(db, exc)
    except ValueError as exc:  # the access writer's validation
        await db.rollback()
        raise HTTPException(422, detail={"code": "override_invalid", "message": str(exc)}) from exc
    await db.commit()
    return AdminBillingDetail(**await service.admin_detail(db, await _organization(db, organization_id)))


@admin_router.post("/organizations/{organization_id}/offers", response_model=OfferCreateResponse)
async def admin_create_offer(
    organization_id: UUID, payload: OfferCreateRequest,
    current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> OfferCreateResponse:
    """A one-use checkout link for a per-tender review: the customer completes the usual checkout (terms, card
    or bank transfer). The link is shown once."""
    organization = await _organization(db, organization_id)
    base = app_url()
    if not base:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail={
            "code": "app_url_missing", "message": "PUBLIC_APP_URL is not set"})
    try:
        offer, token = await service.create_offer(db, organization=organization, product=payload.product,
                                                  actor_user=current_user, note=payload.note, days=payload.days)
    except service.BillingError as exc:
        await _fail(db, exc)
    await db.commit()
    return OfferCreateResponse(offer_id=offer.id, expires_at=offer.expires_at,
                               url=f"{base}/billing/start?plan={payload.product}&offer={token}")


@admin_router.post("/organizations/{organization_id}/invoices", response_model=AdminBillingDetail)
async def admin_issue_invoice(
    organization_id: UUID, payload: AdminInvoiceRequest,
    current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> AdminBillingDetail:
    """A per-tender review by bank transfer, with the signed order form as the terms acceptance."""
    organization = await _organization(db, organization_id)
    try:
        await service.admin_invoice(db, organization=organization, product_code=payload.product,
                                    actor_user=current_user, signed_note=payload.signed_note)
    except service.BillingError as exc:
        await _fail(db, exc)
    await db.commit()
    kick_admin_alerts()
    return AdminBillingDetail(**await service.admin_detail(db, await _organization(db, organization_id)))


@admin_router.post("/orders/{order_id}/confirm-cancel", response_model=AdminBillingDetail)
async def admin_confirm_cancel(
    order_id: UUID, current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> AdminBillingDetail:
    order = await db.get(BillingOrder, order_id, with_for_update=True)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found")
    try:
        await service.confirm_cancel_renewal(db, order=order, actor_user=current_user)
    except service.BillingError as exc:
        await _fail(db, exc)
    await db.commit()
    return AdminBillingDetail(**await service.admin_detail(db, await _organization(db, order.organization_id)))


@admin_router.post("/onboarding/{task_id}/done", response_model=list[OnboardingTaskOut])
async def admin_onboarding_done(
    task_id: UUID, payload: OnboardingDoneRequest,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> list[OnboardingTaskOut]:
    task = await db.get(OnboardingTask, task_id, with_for_update=True)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    try:
        await service.complete_onboarding(db, task=task, note=payload.note, actor_user=current_user)
    except service.BillingError as exc:
        await _fail(db, exc)
    await db.commit()
    return [OnboardingTaskOut(**row) for row in await service.admin_onboarding_queue(db)]
