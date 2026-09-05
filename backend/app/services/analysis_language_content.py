"""Deterministic localization of immutable Compliance explanation fields."""

from __future__ import annotations

import re
from typing import Any, Iterable

from app.core.analysis_languages import AnalysisLanguage
from app.core.agents.requirement_extractor import (
    EvidenceValidationStatus,
    ScopeReviewStatus,
    TenderRequirement,
)
from app.services.compliance_engine import (
    ComplianceResult,
    ComplianceVerdictStatus,
    MatchMethod,
    MatchVerdict,
    RequirementMatchDetail,
)


_TEXT: dict[AnalysisLanguage, dict[str, str]] = {
    AnalysisLanguage.ENGLISH: {
        "evidence_verified": "Evidence was verified against the cited source.",
        "evidence_review": "Source evidence requires manual verification.",
        "evidence_rejected": "Source evidence could not be verified.",
        "eligibility_affecting": "This requirement affects bid-stage eligibility.",
        "eligibility_review": "Bid-stage eligibility impact requires manual review.",
        "eligibility_non_affecting": "This item does not create a verified bid-stage eligibility blocker.",
        "satisfied": "Company Vault evidence ‘{credential}’ satisfies this requirement.",
        "failed": "No matching active Company Vault evidence satisfies this requirement.",
        "manual": "Manual verification is required before relying on this requirement assessment.",
        "recorded": "Verified non-bid obligation recorded for the audit trail.",
        "vault_gap": "Matching evidence is not available in Company Vault.",
        "not_eligible": "NOT ELIGIBLE — {failed} mandatory requirement(s) failed | {satisfied} satisfied | {review} require manual review",
        "needs_review": "No verified requirements yet — manual review required.",
        "eligible_review": "ELIGIBLE WITH REVIEW — no failed bid-stage dealbreakers | {satisfied} satisfied | {review} require manual review",
        "compliant": "ELIGIBLE — {satisfied} satisfied",
        "extraction_failed": "ANALYSIS FAILED — requirement extraction failed; do not rely on this result until extraction succeeds.",
        "coverage_warning": "Some document sections require manual review because extraction or source coverage was incomplete.",
        "language_failed": "The model did not produce a valid result in the requested analysis language.",
    },
    AnalysisLanguage.UZBEK: {
        "evidence_verified": "Dalil ko‘rsatilgan manba bilan tekshirildi.",
        "evidence_review": "Manba dalilini qo‘lda tekshirish talab etiladi.",
        "evidence_rejected": "Manba dalilini tasdiqlab bo‘lmadi.",
        "eligibility_affecting": "Ushbu talab taklif bosqichidagi muvofiqlikka ta’sir qiladi.",
        "eligibility_review": "Taklif bosqichidagi ta’sirni qo‘lda tekshirish talab etiladi.",
        "eligibility_non_affecting": "Ushbu band taklif bosqichida tasdiqlangan to‘siq yaratmaydi.",
        "satisfied": "Kompaniya omboridagi «{credential}» dalili ushbu talabni qanoatlantiradi.",
        "failed": "Kompaniya omborida ushbu talabni qanoatlantiradigan faol dalil topilmadi.",
        "manual": "Ushbu talab bahosiga tayanishdan oldin qo‘lda tekshirish zarur.",
        "recorded": "Taklifga aloqador bo‘lmagan tasdiqlangan majburiyat audit uchun qayd etildi.",
        "vault_gap": "Kompaniya omborida mos dalil mavjud emas.",
        "not_eligible": "MUVOFIQ EMAS — {failed} ta majburiy talab bajarilmadi | {satisfied} ta bajarildi | {review} ta qo‘lda tekshiriladi",
        "needs_review": "Tasdiqlangan talablar hozircha yo‘q — qo‘lda tekshirish zarur.",
        "eligible_review": "TEKSHIRUV BILAN MUVOFIQ — bajarilmagan hal qiluvchi talab yo‘q | {satisfied} ta bajarildi | {review} ta qo‘lda tekshiriladi",
        "compliant": "MUVOFIQ — {satisfied} ta talab bajarildi",
        "extraction_failed": "TAHLIL BAJARILMADI — talablarni ajratib olishda xato yuz berdi; muvaffaqiyatli tahlilgacha bu natijaga tayanmang.",
        "coverage_warning": "Ajratib olish yoki manba qamrovi to‘liq bo‘lmagani sababli ayrim bo‘limlar qo‘lda tekshirilishi kerak.",
        "language_failed": "Model so‘ralgan tahlil tilida yaroqli natija yaratmadi.",
    },
    AnalysisLanguage.RUSSIAN: {
        "evidence_verified": "Доказательство сверено с указанным источником.",
        "evidence_review": "Требуется ручная проверка доказательства по источнику.",
        "evidence_rejected": "Не удалось подтвердить доказательство по источнику.",
        "eligibility_affecting": "Это требование влияет на допуск на этапе подачи заявки.",
        "eligibility_review": "Влияние на допуск требует ручной проверки.",
        "eligibility_non_affecting": "Этот пункт не создает подтвержденного препятствия для допуска.",
        "satisfied": "Доказательство «{credential}» из хранилища компании удовлетворяет требованию.",
        "failed": "В хранилище компании нет действующего доказательства, удовлетворяющего требованию.",
        "manual": "Перед использованием этой оценки требуется ручная проверка.",
        "recorded": "Подтвержденное обязательство вне этапа заявки сохранено для аудита.",
        "vault_gap": "Подходящее доказательство отсутствует в хранилище компании.",
        "not_eligible": "НЕ ДОПУЩЕН — не выполнено обязательных требований: {failed} | выполнено: {satisfied} | требуют проверки: {review}",
        "needs_review": "Подтвержденных требований пока нет — необходима ручная проверка.",
        "eligible_review": "ДОПУЩЕН С ПРОВЕРКОЙ — нет невыполненных критических требований | выполнено: {satisfied} | требуют проверки: {review}",
        "compliant": "ДОПУЩЕН — выполнено требований: {satisfied}",
        "extraction_failed": "АНАЛИЗ НЕ ВЫПОЛНЕН — извлечение требований завершилось ошибкой; не полагайтесь на результат до успешного анализа.",
        "coverage_warning": "Некоторые разделы требуют ручной проверки из-за неполного извлечения или покрытия источников.",
        "language_failed": "Модель не сформировала корректный результат на запрошенном языке анализа.",
    },
    AnalysisLanguage.ARABIC: {
        "evidence_verified": "تم التحقق من الدليل مقابل المصدر المشار إليه.",
        "evidence_review": "يتطلب دليل المصدر تحققاً يدوياً.",
        "evidence_rejected": "تعذر التحقق من دليل المصدر.",
        "eligibility_affecting": "يؤثر هذا المتطلب في الأهلية بمرحلة تقديم العطاء.",
        "eligibility_review": "يتطلب أثر الأهلية في مرحلة العطاء مراجعة يدوية.",
        "eligibility_non_affecting": "لا ينشئ هذا البند مانع أهلية مؤكداً في مرحلة العطاء.",
        "satisfied": "يلبي دليل «{credential}» في خزينة الشركة هذا المتطلب.",
        "failed": "لا يوجد في خزينة الشركة دليل ساري يفي بهذا المتطلب.",
        "manual": "يلزم التحقق اليدوي قبل الاعتماد على تقييم هذا المتطلب.",
        "recorded": "سُجل التزام مؤكد خارج مرحلة العطاء لأغراض التدقيق.",
        "vault_gap": "لا يتوفر دليل مطابق في خزينة الشركة.",
        "not_eligible": "غير مؤهل — المتطلبات الإلزامية غير المستوفاة: {failed} | المستوفاة: {satisfied} | للمراجعة: {review}",
        "needs_review": "لا توجد متطلبات مؤكدة بعد — المراجعة اليدوية مطلوبة.",
        "eligible_review": "مؤهل مع المراجعة — لا توجد متطلبات حاسمة فاشلة | المستوفاة: {satisfied} | للمراجعة: {review}",
        "compliant": "مؤهل — المتطلبات المستوفاة: {satisfied}",
        "extraction_failed": "فشل التحليل — تعذر استخراج المتطلبات؛ لا تعتمد على النتيجة حتى ينجح التحليل.",
        "coverage_warning": "تتطلب بعض أقسام المستند مراجعة يدوية بسبب عدم اكتمال الاستخراج أو تغطية المصدر.",
        "language_failed": "لم ينتج النموذج نتيجة صالحة بلغة التحليل المطلوبة.",
    },
}


def analysis_text(
    language: AnalysisLanguage | str,
    key: str,
    **values: Any,
) -> str:
    return _TEXT[AnalysisLanguage(language)][key].format(**values)


def localize_validated_requirements(
    requirements: Iterable[TenderRequirement],
    language: AnalysisLanguage | str,
) -> list[TenderRequirement]:
    localized: list[TenderRequirement] = []
    for requirement in requirements:
        if requirement.validation_status == EvidenceValidationStatus.ACCEPTED:
            validation_key = "evidence_verified"
        elif requirement.validation_status == EvidenceValidationStatus.REJECTED:
            validation_key = "evidence_rejected"
        else:
            validation_key = "evidence_review"
        if requirement.scope_review_status == ScopeReviewStatus.NEEDS_REVIEW:
            eligibility_key = "eligibility_review"
        elif requirement.affects_bid_eligibility:
            eligibility_key = "eligibility_affecting"
        else:
            eligibility_key = "eligibility_non_affecting"
        localized.append(
            requirement.model_copy(
                update={
                    "validation_reason": analysis_text(language, validation_key),
                    "eligibility_reason": analysis_text(language, eligibility_key),
                }
            )
        )
    return localized


def _localized_detail(
    detail: RequirementMatchDetail,
    language: AnalysisLanguage | str,
) -> RequirementMatchDetail:
    if detail.match_method == MatchMethod.SKIPPED and detail.verdict == MatchVerdict.SATISFIED:
        reason_key = "recorded"
    elif detail.verdict == MatchVerdict.SATISFIED:
        reason_key = "satisfied"
    elif detail.verdict == MatchVerdict.FAILED:
        reason_key = "failed"
    else:
        reason_key = "manual"
    credential = detail.matched_credential or "—"
    update: dict[str, Any] = {
        "reason": analysis_text(language, reason_key, credential=credential),
    }
    if detail.vault_missing_reason:
        update["vault_missing_reason"] = analysis_text(language, "vault_gap")
    return detail.model_copy(update=update)


def localize_compliance_result(
    result: ComplianceResult,
    language: AnalysisLanguage | str,
) -> ComplianceResult:
    if result.verdict_status == ComplianceVerdictStatus.NOT_ELIGIBLE:
        status_key = "not_eligible"
    elif result.verdict_status == ComplianceVerdictStatus.COMPLIANT:
        status_key = "compliant"
    elif result.verdict_status == ComplianceVerdictStatus.ELIGIBLE_WITH_REVIEW:
        status_key = "eligible_review"
    else:
        status_key = "needs_review"
    return result.model_copy(
        update={
            "failed_dealbreakers": [
                _localized_detail(item, language) for item in result.failed_dealbreakers
            ],
            "manual_reviews_required": [
                _localized_detail(item, language)
                for item in result.manual_reviews_required
            ],
            "satisfied_requirements": [
                _localized_detail(item, language)
                for item in result.satisfied_requirements
            ],
            "recorded_obligations": [
                _localized_detail(item, language)
                for item in result.recorded_obligations
            ],
            "status_message": analysis_text(
                language,
                status_key,
                failed=result.failed_count,
                satisfied=result.satisfied_count,
                review=result.manual_review_count,
            ),
        }
    )


def localize_analysis_warnings(
    warnings: Iterable[str],
    language: AnalysisLanguage | str,
) -> list[str]:
    return [analysis_text(language, "coverage_warning") for _ in warnings]


_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")


def generated_texts_follow_language(
    texts: Iterable[str],
    language: AnalysisLanguage | str,
) -> bool:
    """Bounded script guard; QA remains authoritative for linguistic quality."""
    generated = [text for text in texts if text.strip()]
    if not generated:
        return True
    combined = " ".join(generated)
    selected = AnalysisLanguage(language)
    if selected == AnalysisLanguage.RUSSIAN:
        return bool(_CYRILLIC_RE.search(combined)) and not _ARABIC_RE.search(combined)
    if selected == AnalysisLanguage.ARABIC:
        return bool(_ARABIC_RE.search(combined))
    return not _CYRILLIC_RE.search(combined) and not _ARABIC_RE.search(combined)


def generated_headlines_follow_language(
    requirements: Iterable[TenderRequirement],
    language: AnalysisLanguage | str,
) -> bool:
    return generated_texts_follow_language(
        (item.headline for item in requirements),
        language,
    )
