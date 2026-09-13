"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Building2,
  Check,
  Globe2,
  Phone,
  UserRound,
} from "lucide-react";
import { useSession } from "next-auth/react";
import { useTranslations } from "next-intl";
import { LanguageSelector } from "@/components/i18n/LanguageSelector";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Feedback";
import { localizeTaxonomyValue } from "@/i18n/taxonomy";
import { api, setApiAccessToken } from "@/lib/api";
import {
  CENTRAL_ASIA_COUNTRIES,
  CENTRAL_ASIA_REGION,
  useGeographyMeta,
} from "@/lib/geography";
import { useServiceMeta } from "@/lib/services";

type FormState = {
  company_name: string;
  industry: string;
  target_regions: string[];
  target_countries: string[];
  target_services: string[];
  director_name: string;
  phone_contact: string;
  inn: string;
  website: string;
  address: string;
  notes: string;
};

const initialForm: FormState = {
  company_name: "",
  industry: "",
  target_regions: [CENTRAL_ASIA_REGION],
  target_countries: [CENTRAL_ASIA_COUNTRIES[0]],
  target_services: [],
  director_name: "",
  phone_contact: "",
  inn: "",
  website: "",
  address: "",
  notes: "",
};

const inputClass = "ds-control";

const labelClass = "ds-field-label";

function toggleValue(values: string[], value: string): string[] {
  if (values.includes(value)) {
    return values.filter((item) => item !== value);
  }
  return [...values, value];
}

export default function OnboardingPage() {
  const router = useRouter();
  const t = useTranslations("onboarding");
  const tCommon = useTranslations("common");
  const { update } = useSession();
  const geography = useGeographyMeta();
  const services = useServiceMeta();
  const [form, setForm] = useState<FormState>(initialForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const countryCount = useMemo(
    () => form.target_countries.length,
    [form.target_countries.length],
  );
  const centralAsiaCountries = geography.central_asia_countries;
  const allCentralAsiaCountriesSelected = centralAsiaCountries.every(
    (country) => form.target_countries.includes(country),
  );

  const updateField = (field: keyof FormState, value: string) => {
    setForm((current) => ({ ...current, [field]: value }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (
      !form.company_name.trim() ||
      !form.industry.trim() ||
      !form.director_name.trim() ||
      !form.phone_contact.trim() ||
      !form.inn.trim() ||
      form.target_regions.length === 0 ||
      form.target_services.length === 0 ||
      form.target_countries.length === 0
    ) {
      setError(t("validationError"));
      return;
    }

    setSaving(true);
    try {
      await api.post("/users/me/company/onboarding", {
        company_name: form.company_name,
        industry: form.industry,
        target_regions: form.target_regions,
        target_countries: form.target_countries,
        target_services: form.target_services,
        director_name: form.director_name,
        phone_contact: form.phone_contact,
        inn: form.inn,
        website: form.website || null,
        address: form.address || null,
        notes: form.notes || null,
      });
      setSubmitted(true);
      const refreshedSession = await update();
      setApiAccessToken(refreshedSession?.accessToken ?? null);
      router.replace("/dashboard/pending-approval");
    } catch {
      console.error("Failed to submit onboarding:");
      setError(t("submitError"));
    } finally {
      setSaving(false);
    }
  };

  const toggleCentralAsiaCountries = () => {
    setForm((current) => {
      const selected = centralAsiaCountries.every((country) =>
        current.target_countries.includes(country),
      );
      const centralAsiaCountrySet = new Set(centralAsiaCountries);

      return {
        ...current,
        target_countries: selected
          ? current.target_countries.filter(
              (country) => !centralAsiaCountrySet.has(country),
            )
          : Array.from(
              new Set([...current.target_countries, ...centralAsiaCountries]),
            ),
      };
    });
  };

  return (
    <div className="customer-page onboarding-page ds-container-content ds-stack">
      <header className="ds-page-header">
        <div className="onboarding-heading">
          <span className="onboarding-heading-icon"><Building2 aria-hidden /></span>
          <div>
            <span className="ds-eyebrow">Plasma</span>
            <h1>{t("title")}</h1>
            <p className="ds-muted">{t("subtitle")}</p>
          </div>
        </div>
      </header>

      <LanguageSelector surface="onboarding" />

      {error && <Alert tone="danger" title={error} />}

      {submitted && (
        <Alert tone="success" title={t("submittedTitle")}>{t("submittedHelp")}</Alert>
      )}

      <form onSubmit={handleSubmit} className="ds-stack">
        <section className="ds-surface onboarding-section">
          <div className="onboarding-section-heading">
            <Building2 aria-hidden />
            <h2>{t("company")}</h2>
          </div>
          <div className="onboarding-field-grid">
            <label className="ds-field">
              <span className={labelClass}>{t("companyName")}</span>
              <input
                dir="auto"
                className={inputClass}
                value={form.company_name}
                onChange={(event) =>
                  updateField("company_name", event.target.value)
                }
                required
              />
            </label>
            <label className="ds-field">
              <span className={labelClass}>{t("industry")}</span>
              <input
                dir="auto"
                className={inputClass}
                value={form.industry}
                onChange={(event) =>
                  updateField("industry", event.target.value)
                }
                required
              />
            </label>
            <label className="ds-field">
              <span className={labelClass}>{t("website")}</span>
              <input
                dir="ltr"
                className={inputClass}
                value={form.website}
                onChange={(event) => updateField("website", event.target.value)}
                placeholder="https://"
                type="url"
              />
            </label>
            <label className="ds-field">
              <span className={labelClass}>{t("registrationNumber")}</span>
              <input
                dir="ltr"
                className={inputClass}
                value={form.inn}
                onChange={(event) => updateField("inn", event.target.value)}
                required
              />
            </label>
          </div>
          <label className="ds-field">
            <span className={labelClass}>{t("address")}</span>
            <input
              dir="auto"
              className={inputClass}
              value={form.address}
              onChange={(event) => updateField("address", event.target.value)}
            />
          </label>
        </section>

        <section className="ds-surface onboarding-section">
          <div className="onboarding-section-heading">
            <Globe2 aria-hidden />
            <h2>{t("targets")}</h2>
          </div>
          <fieldset className="onboarding-choice-group">
            <legend className={labelClass}>{t("targetRegions")}</legend>
            <div className="onboarding-choice-grid">
              {geography.regions.map((region) => {
                const selected = form.target_regions.includes(region);
                const isCentralAsia = region === CENTRAL_ASIA_REGION;
                return (
                  <button
                    type="button"
                    key={region}
                    onClick={() =>
                      setForm((current) => ({
                        ...current,
                        target_regions: toggleValue(
                          current.target_regions,
                          region,
                        ),
                      }))
                    }
                    aria-pressed={selected}
                    data-emphasis={isCentralAsia || undefined}
                    className="onboarding-choice"
                  >
                    <span>
                      {localizeTaxonomyValue("region", region, tCommon)}
                    </span>
                    {selected && <Check aria-hidden />}
                  </button>
                );
              })}
            </div>
          </fieldset>

          <fieldset className="onboarding-choice-group">
            <legend className={labelClass}>{t("targetCountries")}</legend>
            <Button
              variant="secondary"
              size="sm"
              onClick={toggleCentralAsiaCountries}
              leadingIcon={<Check aria-hidden />}
            >
              {allCentralAsiaCountriesSelected
                ? t("clearCentralAsia")
                : t("selectCentralAsia")}
            </Button>
            <div className="onboarding-choice-grid">
              {centralAsiaCountries.map((country) => {
                const selected = form.target_countries.includes(country);
                return (
                  <button
                    type="button"
                    key={country}
                    onClick={() =>
                      setForm((current) => ({
                        ...current,
                        target_countries: toggleValue(
                          current.target_countries,
                          country,
                        ),
                      }))
                    }
                    aria-pressed={selected}
                    className="onboarding-choice"
                  >
                    <span>
                      {localizeTaxonomyValue("country", country, tCommon)}
                    </span>
                    {selected && <Check aria-hidden />}
                  </button>
                );
              })}
            </div>
            <span className="ds-field-help">
              {t("countriesSelected", { count: countryCount })}
            </span>
          </fieldset>

          <fieldset className="onboarding-choice-group">
            <legend className={labelClass}>{t("targetServices")}</legend>
            <div className="onboarding-choice-grid">
              {services.map((service) => {
                const selected = form.target_services.includes(service.value);
                return (
                  <label
                    key={service.value}
                    data-selected={selected}
                    className="onboarding-check"
                  >
                    <input
                      type="checkbox"
                      className="ds-checkbox"
                      checked={selected}
                      onChange={() =>
                        setForm((current) => ({
                          ...current,
                          target_services: toggleValue(
                            current.target_services,
                            service.value,
                          ),
                        }))
                      }
                    />
                    <span>
                      {localizeTaxonomyValue("service", service.value, tCommon)}
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        </section>

        <section className="ds-surface onboarding-section">
          <div className="onboarding-section-heading">
            <UserRound aria-hidden />
            <h2>{t("contact")}</h2>
          </div>
          <div className="onboarding-field-grid">
            <label className="ds-field">
              <span className={labelClass}>{t("directorName")}</span>
              <input
                dir="auto"
                className={inputClass}
                value={form.director_name}
                onChange={(event) =>
                  updateField("director_name", event.target.value)
                }
                required
              />
            </label>
            <label className="ds-field">
              <span className={labelClass}>{t("phone")}</span>
              <div className="onboarding-phone">
                <Phone aria-hidden />
                <input
                  dir="ltr"
                  className={`${inputClass} onboarding-phone-control`}
                  value={form.phone_contact}
                  onChange={(event) =>
                    updateField("phone_contact", event.target.value)
                  }
                  required
                />
              </div>
            </label>
          </div>
          <label className="ds-field">
            <span className={labelClass}>{t("notes")}</span>
            <textarea
              dir="auto"
              className={inputClass}
              value={form.notes}
              onChange={(event) => updateField("notes", event.target.value)}
            />
          </label>
        </section>

        <div className="onboarding-submit">
          <Button
            type="submit"
            loading={saving}
            leadingIcon={<Check aria-hidden />}
          >
            {saving ? t("submitting") : t("submit")}
          </Button>
        </div>
      </form>
    </div>
  );
}
