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
        "code_subject": "Your Plasma sign-in code",
        "code_body": "Your sign-in code is {code}",
        "code_note": "Enter it on the Plasma sign-in page. It expires in {minutes} minutes and works once.",
        "footer_code": "You receive this e-mail because someone asked to sign in to Plasma with this address. If it was not you, ignore it: no one can sign in without this code.",
        "footer": "You receive this e-mail because of your Plasma account. Change e-mail notifications in Settings: {settings_url}",
        "footer_invite": "You receive this e-mail because someone invited this address to Plasma. If you did not expect it, ignore it.",
        "invite_subject": "{inviter} invited you to join {organization} on Plasma",
        "invite_body": "{inviter} invited you to join {organization} on Plasma as {role}.",
        "invite_action": "Accept the invitation: {url}",
        "invite_note": "Sign in with this e-mail address, with Google or a one-time e-mail code. The invitation expires on {expires}.",
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
        # B1: billing.
        "billing_footer": "You receive this e-mail because your organization bought a Plasma plan. Questions: hq@plasmaos.uz",
        "product_pilot": "Pilot",
        "product_pursuit_desk": "Pursuit Desk",
        "product_extra_pursuit": "extra pursuit",
        "invoice_subject": "Invoice {number} from Plasma",
        "invoice_body": "Your {product} is active now. Invoice {number} is attached: {amount}, payable by bank transfer by {due}.",
        "invoice_reference": "Use {number} as the payment reference. If it is unpaid on {due}, your organization returns to the free Explore plan until the payment arrives.",
        "invoice_pilot_note": "The pilot payment is credited to your first annual invoice.",
        "open_billing": "Billing in Plasma: {url}",
        "reminder_subject": "Reminder: invoice {number} is due on {due}",
        "reminder_body": "Invoice {number} ({amount}) is not paid yet. {days} days left: pay by {due} to keep your plan.",
        "suspended_subject": "Your Plasma plan is paused: invoice {number} is unpaid",
        "suspended_body": "Invoice {number} was not paid within 10 days, so your organization is back on the free Explore plan. Your data is kept: pay the invoice and your plan comes back.",
        "welcome_subject": "Welcome to Plasma {plan}",
        "welcome_body": "Your {plan} is active from {start} to {end}.",
        "welcome_kickoff": "Book your kickoff call: {url}",
        "welcome_next": "Next: open a tender in Plasma and start its analysis. Our team will contact you to plan the first pursuits.",
        "welcome_awaiting": "The invoice comes in a separate e-mail; your plan is already active.",
        "open_dashboard": "Open Plasma: {url}",
    },
    "ru": {
        "brand": "Plasma",
        "code_subject": "Ваш код для входа в Plasma",
        "code_body": "Ваш код для входа: {code}",
        "code_note": "Введите его на странице входа в Plasma. Код действует {minutes} минут и только один раз.",
        "footer_code": "Вы получили это письмо, потому что кто-то запросил вход в Plasma с этим адресом. Если это были не вы, просто проигнорируйте его: без этого кода войти нельзя.",
        "footer": "Вы получили это письмо, потому что у вас есть аккаунт Plasma. Настроить уведомления по e-mail можно в Настройках: {settings_url}",
        "footer_invite": "Вы получили это письмо, потому что этот адрес пригласили в Plasma. Если вы его не ждали, просто проигнорируйте.",
        "invite_subject": "{inviter} приглашает вас в {organization} на Plasma",
        "invite_body": "{inviter} приглашает вас присоединиться к {organization} на Plasma в роли «{role}».",
        "invite_action": "Принять приглашение: {url}",
        "invite_note": "Войдите с этим адресом e-mail — через Google или по одноразовому коду из письма. Приглашение действует до {expires}.",
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
        # B1: billing.
        "billing_footer": "Вы получили это письмо, потому что ваша организация оплатила тариф Plasma. Вопросы: hq@plasmaos.uz",
        "product_pilot": "Пилот",
        "product_pursuit_desk": "Pursuit Desk",
        "product_extra_pursuit": "дополнительный тендер",
        "invoice_subject": "Счёт {number} от Plasma",
        "invoice_body": "Ваш тариф «{product}» уже активен. Счёт {number} во вложении: {amount}, оплата банковским переводом до {due}.",
        "invoice_reference": "Укажите {number} в назначении платежа. Если счёт не оплачен к {due}, организация вернётся на бесплатный тариф Explore до поступления оплаты.",
        "invoice_pilot_note": "Оплата пилота засчитывается в первый годовой счёт.",
        "open_billing": "Оплата в Plasma: {url}",
        "reminder_subject": "Напоминание: счёт {number} нужно оплатить до {due}",
        "reminder_body": "Счёт {number} ({amount}) ещё не оплачен. Осталось дней: {days}. Оплатите до {due}, чтобы сохранить тариф.",
        "suspended_subject": "Тариф Plasma приостановлен: счёт {number} не оплачен",
        "suspended_body": "Счёт {number} не был оплачен в течение 10 дней, поэтому организация вернулась на бесплатный тариф Explore. Данные сохранены: оплатите счёт, и тариф вернётся.",
        "welcome_subject": "Добро пожаловать в Plasma: {plan}",
        "welcome_body": "Ваш тариф «{plan}» действует с {start} по {end}.",
        "welcome_kickoff": "Запишитесь на стартовый звонок: {url}",
        "welcome_next": "Дальше: откройте тендер в Plasma и запустите анализ. Наша команда свяжется с вами, чтобы спланировать первые тендеры.",
        "welcome_awaiting": "Счёт придёт отдельным письмом; тариф уже активен.",
        "open_dashboard": "Открыть Plasma: {url}",
    },
    "uz": {
        "brand": "Plasma",
        "code_subject": "Plasma’ga kirish kodingiz",
        "code_body": "Kirish kodingiz: {code}",
        "code_note": "Uni Plasma’ning kirish sahifasida kiriting. Kod {minutes} daqiqa amal qiladi va bir marta ishlaydi.",
        "footer_code": "Bu xat kimdir ushbu manzil bilan Plasma’ga kirishni so‘ragani uchun yuborildi. Agar bu siz bo‘lmasangiz, e’tibor bermang: bu kodsiz hech kim kira olmaydi.",
        "footer": "Bu xat Plasma hisobingiz sababli yuborildi. E-mail bildirishnomalarini Sozlamalarda o‘zgartiring: {settings_url}",
        "footer_invite": "Bu xat ushbu manzil Plasma’ga taklif qilingani uchun yuborildi. Agar kutmagan bo‘lsangiz, e’tibor bermang.",
        "invite_subject": "{inviter} sizni Plasma’dagi {organization}ga taklif qildi",
        "invite_body": "{inviter} sizni Plasma’dagi {organization}ga «{role}» sifatida qo‘shilishga taklif qildi.",
        "invite_action": "Taklifni qabul qilish: {url}",
        "invite_note": "Aynan shu e-mail manzili bilan kiring: Google orqali yoki bir martalik e-mail kodi bilan. Taklif {expires} gacha amal qiladi.",
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
        # B1: billing.
        "billing_footer": "Bu xat tashkilotingiz Plasma tarifini sotib olgani uchun yuborildi. Savollar: hq@plasmaos.uz",
        "product_pilot": "Pilot",
        "product_pursuit_desk": "Pursuit Desk",
        "product_extra_pursuit": "qo‘shimcha tender",
        "invoice_subject": "Plasma’dan {number} hisob-fakturasi",
        "invoice_body": "«{product}» tarifingiz faol. {number} hisob-fakturasi ilova qilingan: {amount}, {due} gacha bank o‘tkazmasi orqali to‘lanadi.",
        "invoice_reference": "To‘lov maqsadida {number} ni ko‘rsating. {due} gacha to‘lanmasa, tashkilotingiz to‘lov kelguncha bepul Explore tarifiga qaytadi.",
        "invoice_pilot_note": "Pilot uchun to‘lov birinchi yillik hisob-fakturaga hisoblanadi.",
        "open_billing": "Plasma’da to‘lovlar: {url}",
        "reminder_subject": "Eslatma: {number} hisob-fakturasi {due} gacha to‘lanishi kerak",
        "reminder_body": "{number} hisob-fakturasi ({amount}) hali to‘lanmagan. {days} kun qoldi: tarifni saqlash uchun {due} gacha to‘lang.",
        "suspended_subject": "Plasma tarifingiz to‘xtatildi: {number} hisob-fakturasi to‘lanmagan",
        "suspended_body": "{number} hisob-fakturasi 10 kun ichida to‘lanmadi, shuning uchun tashkilotingiz bepul Explore tarifiga qaytdi. Ma’lumotlaringiz saqlangan: hisob-fakturani to‘lang va tarif qaytadi.",
        "welcome_subject": "Plasma {plan} tarifiga xush kelibsiz",
        "welcome_body": "«{plan}» tarifingiz {start} dan {end} gacha faol.",
        "welcome_kickoff": "Boshlang‘ich qo‘ng‘iroqqa yoziling: {url}",
        "welcome_next": "Keyingi qadam: Plasma’da tenderni oching va tahlilni boshlang. Jamoamiz birinchi tenderlarni rejalashtirish uchun siz bilan bog‘lanadi.",
        "welcome_awaiting": "Hisob-faktura alohida xatda keladi; tarifingiz allaqachon faol.",
        "open_dashboard": "Plasma’ni ochish: {url}",
    },
    "ar": {
        "brand": "Plasma",
        "code_subject": "رمز الدخول إلى Plasma",
        "code_body": "رمز الدخول الخاص بك: {code}",
        "code_note": "أدخله في صفحة تسجيل الدخول إلى Plasma. تنتهي صلاحيته بعد {minutes} دقائق ويُستخدم مرة واحدة.",
        "footer_code": "تصلك هذه الرسالة لأن أحدهم طلب تسجيل الدخول إلى Plasma بهذا العنوان. إن لم تكن أنت فتجاهلها: لا يمكن لأحد الدخول دون هذا الرمز.",
        "footer": "تصلك هذه الرسالة بسبب حسابك في Plasma. غيّر إشعارات البريد الإلكتروني من الإعدادات: {settings_url}",
        "footer_invite": "تصلك هذه الرسالة لأن أحدهم دعا هذا العنوان إلى Plasma. إن لم تكن تتوقعها فتجاهلها.",
        "invite_subject": "دعاك {inviter} للانضمام إلى {organization} على Plasma",
        "invite_body": "دعاك {inviter} للانضمام إلى {organization} على Plasma بدور {role}.",
        "invite_action": "اقبل الدعوة: {url}",
        "invite_note": "سجّل الدخول بعنوان البريد هذا، عبر Google أو برمز بريد لمرة واحدة. تنتهي الدعوة في {expires}.",
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
        # B1: billing.
        "billing_footer": "تصلك هذه الرسالة لأن مؤسستك اشترت خطة في Plasma. للاستفسارات: hq@plasmaos.uz",
        "product_pilot": "التجربة",
        "product_pursuit_desk": "مكتب المناقصات",
        "product_extra_pursuit": "مناقصة إضافية",
        "invoice_subject": "الفاتورة {number} من Plasma",
        "invoice_body": "خطتك ({product}) مفعّلة الآن. الفاتورة {number} مرفقة: {amount}، تُدفع بتحويل بنكي قبل {due}.",
        "invoice_reference": "اذكر {number} مرجعًا للدفع. إن لم تُدفع حتى {due} تعود مؤسستك إلى خطة الاستكشاف المجانية حتى وصول الدفعة.",
        "invoice_pilot_note": "يُحتسب مبلغ التجربة من أول فاتورة سنوية.",
        "open_billing": "الفوترة في Plasma: {url}",
        "reminder_subject": "تذكير: الفاتورة {number} مستحقة في {due}",
        "reminder_body": "الفاتورة {number} ({amount}) لم تُدفع بعد. متبقٍ {days} أيام: ادفع قبل {due} للحفاظ على خطتك.",
        "suspended_subject": "تم إيقاف خطتك في Plasma مؤقتًا: الفاتورة {number} غير مدفوعة",
        "suspended_body": "لم تُدفع الفاتورة {number} خلال 10 أيام، لذا عادت مؤسستك إلى خطة الاستكشاف المجانية. بياناتك محفوظة: ادفع الفاتورة وتعود خطتك.",
        "welcome_subject": "مرحبًا بك في Plasma: {plan}",
        "welcome_body": "خطتك ({plan}) مفعّلة من {start} إلى {end}.",
        "welcome_kickoff": "احجز مكالمة البدء: {url}",
        "welcome_next": "التالي: افتح مناقصة في Plasma وابدأ تحليلها. سيتواصل فريقنا معك لتخطيط أولى المناقصات.",
        "welcome_awaiting": "تصلك الفاتورة في رسالة منفصلة؛ خطتك مفعّلة بالفعل.",
        "open_dashboard": "افتح Plasma: {url}",
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
    if kind == "SIGN_IN_CODE":
        # P1: the code is the only value; no link (a link would invite phishing look-alikes).
        minutes = context.get("expires_minutes", 10)
        lines = [
            (_t(locale, "code_body", code=context["code"]), None),
            (_t(locale, "code_note", minutes=minutes), None),
        ]
        return _compose(locale, _t(locale, "code_subject"), lines, _t(locale, "footer_code"))
    if kind == "ADMIN_ALERT":
        # P1: to the Plasma team only (PLASMA_ADMIN_EMAILS), English, plain facts.
        lines = [(str(line), None) for line in (context.get("lines") or [])]
        footer_admin = "You receive this e-mail because your address is in PLASMA_ADMIN_EMAILS."
        return _compose("en", str(context.get("subject") or "Plasma alert"), lines, footer_admin)
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
    if kind in BILLING_KINDS:
        return _render_billing(kind, locale, context, app_url=app_url)
    raise ValueError(f"unknown e-mail kind {kind}")


BILLING_KINDS = {"BILLING_INVOICE", "BILLING_REMINDER", "BILLING_WELCOME", "BILLING_SUSPENDED"}


def _amount(context: dict[str, Any]) -> str:
    if context.get("currency") == "UZS" and context.get("total_uzs"):
        return f"UZS {context['total_uzs']}"
    return f"USD {context.get('total_usd')}"


def _render_billing(kind: str, locale: str, context: dict[str, Any], *, app_url: str) -> RenderedEmail:
    """B1: transactional billing e-mails (no preference switch: they are about the customer's payment)."""
    footer = _t(locale, "billing_footer")
    billing = _url(app_url, "/dashboard/billing")
    product = _t(locale, f"product_{context.get('product') or 'pilot'}")
    values = {"number": context.get("number", ""), "due": context.get("due_on", ""), "amount": _amount(context)}
    if kind == "BILLING_WELCOME":
        plan = _t(locale, f"product_{context.get('plan') or 'pilot'}")
        lines: list[tuple[str, str | None]] = [
            (_t(locale, "welcome_body", plan=plan, start=context.get("starts_on", ""), end=context.get("ends_on", "")), None),
        ]
        if context.get("kickoff_url"):
            lines.append((_t(locale, "welcome_kickoff", url=context["kickoff_url"]), str(context["kickoff_url"])))
        lines.append((_t(locale, "welcome_next"), None))
        if context.get("awaiting_payment"):
            lines.append((_t(locale, "welcome_awaiting"), None))
        dashboard = _url(app_url, "/dashboard")
        lines.append((_t(locale, "open_dashboard", url=dashboard), dashboard))
        return _compose(locale, _t(locale, "welcome_subject", plan=plan), lines, footer)
    if kind == "BILLING_INVOICE":
        lines = [(_t(locale, "invoice_body", product=product, **values), None),
                 (_t(locale, "invoice_reference", **values), None)]
        if context.get("pilot"):
            lines.append((_t(locale, "invoice_pilot_note"), None))
        lines.append((_t(locale, "open_billing", url=billing), billing))
        return _compose(locale, _t(locale, "invoice_subject", **values), lines, footer)
    if kind == "BILLING_REMINDER":
        lines = [(_t(locale, "reminder_body", days=context.get("days_left", ""), **values), None),
                 (_t(locale, "invoice_reference", **values), None),
                 (_t(locale, "open_billing", url=billing), billing)]
        return _compose(locale, _t(locale, "reminder_subject", **values), lines, footer)
    lines = [(_t(locale, "suspended_body", **values), None), (_t(locale, "open_billing", url=billing), billing)]
    return _compose(locale, _t(locale, "suspended_subject", **values), lines, footer)
