"""R3 Task 4: e-mail templates in en/ru/uz/ar, plain text and HTML.

Templates carry links and public facts only: never private document content, analysis
findings or customer-uploaded titles. Values are HTML-escaped; the HTML part mirrors the
plain part line for line.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

LOCALES = ("en", "ru", "uz", "ar")

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "brand": "Plasma",
        "footer": "You receive this e-mail because of your Plasma account. Change e-mail notifications in Settings: {settings_url}",
        "footer_invite": "You receive this e-mail because someone invited this address to Plasma. If you did not expect it, ignore it.",
        "invite_subject": "{inviter} invited you to join {organization} on Plasma",
        "invite_body": "{inviter} invited you to join {organization} on Plasma as {role}.",
        "invite_action": "Accept the invitation: {url}",
        "invite_note": "Sign in with Google using this e-mail address. The invitation expires on {expires}.",
        "role_OWNER": "an owner", "role_MEMBER": "a member",
        "analysis_completed_subject": "Your analysis is ready",
        "analysis_completed_body": "The analysis you started has finished. Open the pursuit to review requirements and gaps.",
        "analysis_failed_subject": "Your analysis could not be completed",
        "analysis_failed_body": "The analysis you started could not be completed. Open the pursuit to try again.",
        "open_pursuit": "Open the pursuit: {url}",
        "eoi_subject": "Expression of Interest draft {version} is ready",
        "eoi_body": "Expression of Interest draft {version} (DOCX and PDF) is ready to download.",
        "digest_subject": "{count} new open opportunities match your profile",
        "digest_body": "New open opportunities from the last 24 hours that match your company profile:",
        "digest_more": "And {count} more in Opportunities.",
        "digest_item": "{title} — {country}, deadline {deadline}",
        "digest_no_deadline": "no deadline published",
        "open_opportunities": "See all opportunities: {url}",
    },
    "ru": {
        "brand": "Plasma",
        "footer": "Вы получили это письмо, потому что у вас есть аккаунт Plasma. Настроить уведомления по e-mail можно в Настройках: {settings_url}",
        "footer_invite": "Вы получили это письмо, потому что этот адрес пригласили в Plasma. Если вы его не ждали, просто проигнорируйте.",
        "invite_subject": "{inviter} приглашает вас в {organization} на Plasma",
        "invite_body": "{inviter} приглашает вас присоединиться к {organization} на Plasma в роли «{role}».",
        "invite_action": "Принять приглашение: {url}",
        "invite_note": "Войдите через Google с этим адресом e-mail. Приглашение действует до {expires}.",
        "role_OWNER": "владелец", "role_MEMBER": "участник",
        "analysis_completed_subject": "Ваш анализ готов",
        "analysis_completed_body": "Запущенный вами анализ завершён. Откройте тендер, чтобы проверить требования и пробелы.",
        "analysis_failed_subject": "Не удалось завершить анализ",
        "analysis_failed_body": "Запущенный вами анализ не удалось завершить. Откройте тендер, чтобы повторить попытку.",
        "open_pursuit": "Открыть тендер: {url}",
        "eoi_subject": "Черновик заявления о заинтересованности {version} готов",
        "eoi_body": "Черновик заявления о заинтересованности {version} (DOCX и PDF) готов к скачиванию.",
        "digest_subject": "Новые открытые возможности по вашему профилю: {count}",
        "digest_body": "Новые открытые возможности за последние 24 часа, подходящие профилю вашей компании:",
        "digest_more": "И ещё {count} в разделе «Возможности».",
        "digest_item": "{title} — {country}, срок {deadline}",
        "digest_no_deadline": "срок не опубликован",
        "open_opportunities": "Все возможности: {url}",
    },
    "uz": {
        "brand": "Plasma",
        "footer": "Bu xat Plasma hisobingiz sababli yuborildi. E-mail bildirishnomalarini Sozlamalarda o‘zgartiring: {settings_url}",
        "footer_invite": "Bu xat ushbu manzil Plasma’ga taklif qilingani uchun yuborildi. Agar kutmagan bo‘lsangiz, e’tibor bermang.",
        "invite_subject": "{inviter} sizni Plasma’dagi {organization}ga taklif qildi",
        "invite_body": "{inviter} sizni Plasma’dagi {organization}ga «{role}» sifatida qo‘shilishga taklif qildi.",
        "invite_action": "Taklifni qabul qilish: {url}",
        "invite_note": "Google orqali aynan shu e-mail manzili bilan kiring. Taklif {expires} gacha amal qiladi.",
        "role_OWNER": "ega", "role_MEMBER": "a’zo",
        "analysis_completed_subject": "Tahlilingiz tayyor",
        "analysis_completed_body": "Siz boshlagan tahlil yakunlandi. Talablar va kamchiliklarni ko‘rish uchun tenderni oching.",
        "analysis_failed_subject": "Tahlilni yakunlab bo‘lmadi",
        "analysis_failed_body": "Siz boshlagan tahlilni yakunlab bo‘lmadi. Qayta urinish uchun tenderni oching.",
        "open_pursuit": "Tenderni ochish: {url}",
        "eoi_subject": "Qiziqish bildirish xati loyihasi {version} tayyor",
        "eoi_body": "Qiziqish bildirish xati loyihasi {version} (DOCX va PDF) yuklab olishga tayyor.",
        "digest_subject": "Profilingizga mos {count} ta yangi ochiq imkoniyat",
        "digest_body": "Oxirgi 24 soatdagi kompaniya profilingizga mos yangi ochiq imkoniyatlar:",
        "digest_more": "«Imkoniyatlar» bo‘limida yana {count} ta.",
        "digest_item": "{title} — {country}, muddat {deadline}",
        "digest_no_deadline": "muddat e’lon qilinmagan",
        "open_opportunities": "Barcha imkoniyatlar: {url}",
    },
    "ar": {
        "brand": "Plasma",
        "footer": "تصلك هذه الرسالة بسبب حسابك في Plasma. غيّر إشعارات البريد الإلكتروني من الإعدادات: {settings_url}",
        "footer_invite": "تصلك هذه الرسالة لأن أحدهم دعا هذا العنوان إلى Plasma. إن لم تكن تتوقعها فتجاهلها.",
        "invite_subject": "دعاك {inviter} للانضمام إلى {organization} على Plasma",
        "invite_body": "دعاك {inviter} للانضمام إلى {organization} على Plasma بدور {role}.",
        "invite_action": "اقبل الدعوة: {url}",
        "invite_note": "سجّل الدخول عبر Google بعنوان البريد هذا. تنتهي الدعوة في {expires}.",
        "role_OWNER": "مالك", "role_MEMBER": "عضو",
        "analysis_completed_subject": "تحليلك جاهز",
        "analysis_completed_body": "اكتمل التحليل الذي بدأته. افتح الفرصة لمراجعة المتطلبات والفجوات.",
        "analysis_failed_subject": "تعذّر إكمال تحليلك",
        "analysis_failed_body": "تعذّر إكمال التحليل الذي بدأته. افتح الفرصة للمحاولة مجددًا.",
        "open_pursuit": "افتح الفرصة: {url}",
        "eoi_subject": "مسودة إبداء الاهتمام {version} جاهزة",
        "eoi_body": "مسودة إبداء الاهتمام {version} (DOCX وPDF) جاهزة للتنزيل.",
        "digest_subject": "{count} فرص جديدة مفتوحة تطابق ملفك",
        "digest_body": "فرص جديدة مفتوحة خلال آخر 24 ساعة تطابق ملف شركتك:",
        "digest_more": "و{count} أخرى في قسم الفرص.",
        "digest_item": "{title} — {country}، الموعد النهائي {deadline}",
        "digest_no_deadline": "لا يوجد موعد نهائي منشور",
        "open_opportunities": "جميع الفرص: {url}",
    },
}


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


def _t(locale: str, key: str, **values: Any) -> str:
    table = STRINGS.get(locale, STRINGS["en"])
    return (table.get(key) or STRINGS["en"][key]).format(**{name: str(value) for name, value in values.items()})


def _url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}{path}"


def _html(locale: str, title: str, lines: list[tuple[str, str | None]], footer: str) -> str:
    """Lines are (text, link): a link line renders as an anchor; all text is escaped."""
    direction = "rtl" if locale == "ar" else "ltr"
    body = []
    for text_value, link in lines:
        if link:
            label = escape(text_value)
            body.append(f'<p><a href="{escape(link, quote=True)}" style="color:#1d4ed8">{label}</a></p>')
        else:
            body.append(f"<p>{escape(text_value)}</p>")
    return (
        f'<!doctype html><html lang="{locale}" dir="{direction}"><head><meta charset="utf-8">'
        f"<title>{escape(title)}</title></head>"
        '<body style="font-family:Arial,Helvetica,sans-serif;color:#0f172a;line-height:1.5">'
        f"<h1 style=\"font-size:18px\">{escape(title)}</h1>{''.join(body)}"
        f'<hr style="border:0;border-top:1px solid #e2e8f0"><p style="color:#64748b;font-size:12px">{escape(footer)}</p>'
        "</body></html>"
    )


def _compose(locale: str, subject: str, lines: list[tuple[str, str | None]], footer: str) -> RenderedEmail:
    # Plain text carries every link: a line that does not already show its URL gets it below.
    text_lines = [line if not link or link in line else f"{line}\n{link}" for line, link in lines]
    text = "\n\n".join([*text_lines, "--", footer]) + "\n"
    return RenderedEmail(subject=subject, text=text, html=_html(locale, subject, lines, footer))


def render_email(kind: str, locale: str, context: dict[str, Any], *, app_url: str) -> RenderedEmail:
    """Render one e-mail. ``context`` holds public facts and ids only."""
    locale = locale if locale in LOCALES else "en"
    settings_url = _url(app_url, "/dashboard/settings#email-notifications")
    footer = _t(locale, "footer", settings_url=settings_url)
    if kind == "TEAM_INVITATION":
        role = _t(locale, f"role_{context.get('role', 'MEMBER')}")
        values = {"inviter": context.get("inviter_name") or "Plasma", "organization": context.get("organization_name") or "Plasma"}
        link = context["invite_url"]
        lines = [
            (_t(locale, "invite_body", role=role, **values), None),
            (_t(locale, "invite_action", url=link), link),
            (_t(locale, "invite_note", expires=context.get("expires_on", "")), None),
        ]
        return _compose(locale, _t(locale, "invite_subject", **values), lines, _t(locale, "footer_invite"))
    if kind in {"ANALYSIS_COMPLETED", "ANALYSIS_FAILED"}:
        link = _url(app_url, f"/dashboard/pursuits/{context['pursuit_id']}?tab=requirements")
        prefix = "analysis_completed" if kind == "ANALYSIS_COMPLETED" else "analysis_failed"
        lines = [(_t(locale, f"{prefix}_body"), None), (_t(locale, "open_pursuit", url=link), link)]
        return _compose(locale, _t(locale, f"{prefix}_subject"), lines, footer)
    if kind == "EOI_DRAFT_READY":
        link = _url(app_url, f"/dashboard/pursuits/{context['pursuit_id']}?tab=eoi")
        version = context.get("version_number", 1)
        lines = [(_t(locale, "eoi_body", version=version), None), (_t(locale, "open_pursuit", url=link), link)]
        return _compose(locale, _t(locale, "eoi_subject", version=version), lines, footer)
    if kind == "DAILY_DIGEST":
        items = list(context.get("items") or [])[:10]
        total = int(context.get("total") or len(items))
        lines: list[tuple[str, str | None]] = [(_t(locale, "digest_body"), None)]
        for item in items:
            link = _url(app_url, f"/dashboard/tenders/{item['tender_id']}")
            label = _t(
                locale, "digest_item", title=item.get("title") or "—", country=item.get("country") or "—",
                deadline=item.get("deadline") or _t(locale, "digest_no_deadline"),
            )
            lines.append((label, link))
        if total > len(items):
            lines.append((_t(locale, "digest_more", count=total - len(items)), None))
        explorer = _url(app_url, "/dashboard/tenders")
        lines.append((_t(locale, "open_opportunities", url=explorer), explorer))
        return _compose(locale, _t(locale, "digest_subject", count=total), lines, footer)
    raise ValueError(f"unknown e-mail kind {kind}")
