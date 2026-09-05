"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Building2,
  Check,
  Globe2,
  Loader2,
  Phone,
  UserRound,
} from "lucide-react";
import { useSession } from "next-auth/react";
import { useTranslations } from "next-intl";
import { LanguageSelector } from "@/components/i18n/LanguageSelector";
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

const inputClass =
  "w-full bg-gray-950 border border-gray-800 rounded-lg px-4 py-3 text-gray-100 text-sm placeholder-gray-600 outline-none focus:ring-2 focus:ring-cyan-500/40 focus:border-cyan-500 transition-all";

const labelClass = "text-sm font-medium text-gray-300";

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
    } catch (err) {
      console.error("Failed to submit onboarding:", err);
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
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center">
          <Building2 className="w-5 h-5 text-cyan-300" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">
            {t("title")}
          </h1>
          <p className="text-sm text-gray-400">{t("subtitle")}</p>
        </div>
      </div>

      <LanguageSelector surface="onboarding" />

      {error && (
        <div className="border border-red-500/30 bg-red-500/10 text-red-300 rounded-lg px-4 py-3 text-sm">
          {error}
        </div>
      )}

      {submitted && (
        <div className="border border-emerald-500/30 bg-emerald-500/10 text-emerald-200 rounded-lg px-4 py-3">
          <p className="font-semibold">{t("submittedTitle")}</p>
          <p className="mt-1 text-sm text-emerald-100/80">
            {t("submittedHelp")}
          </p>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <section className="border border-gray-800 bg-gray-950 rounded-lg p-6 space-y-5">
          <div className="flex items-center gap-2 text-gray-200">
            <Building2 className="w-4 h-4 text-cyan-300" />
            <h2 className="text-base font-semibold">{t("company")}</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <label className="space-y-2">
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
            <label className="space-y-2">
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
            <label className="space-y-2">
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
            <label className="space-y-2">
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
          <label className="space-y-2 block">
            <span className={labelClass}>{t("address")}</span>
            <input
              dir="auto"
              className={inputClass}
              value={form.address}
              onChange={(event) => updateField("address", event.target.value)}
            />
          </label>
        </section>

        <section className="border border-gray-800 bg-gray-950 rounded-lg p-6 space-y-5">
          <div className="flex items-center gap-2 text-gray-200">
            <Globe2 className="w-4 h-4 text-emerald-300" />
            <h2 className="text-base font-semibold">{t("targets")}</h2>
          </div>
          <div className="space-y-3">
            <span className={labelClass}>{t("targetRegions")}</span>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
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
                    className={`flex items-center justify-between rounded-lg border px-4 py-3 text-sm transition-colors ${
                      selected
                        ? isCentralAsia
                          ? "border-emerald-400 bg-emerald-500/15 text-emerald-100"
                          : "border-cyan-500 bg-cyan-500/10 text-cyan-100"
                        : isCentralAsia
                          ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-200"
                          : "border-gray-800 bg-gray-900 text-gray-300 hover:border-gray-700"
                    }`}
                  >
                    <span>
                      {localizeTaxonomyValue("region", region, tCommon)}
                    </span>
                    {selected && <Check className="w-4 h-4" />}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="space-y-3">
            <span className={labelClass}>{t("targetCountries")}</span>
            <button
              type="button"
              onClick={toggleCentralAsiaCountries}
              className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-100 transition-colors hover:border-emerald-300"
            >
              <Check className="h-3.5 w-3.5" />
              {allCentralAsiaCountriesSelected
                ? t("clearCentralAsia")
                : t("selectCentralAsia")}
            </button>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
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
                    className={`flex items-center justify-between rounded-lg border px-4 py-3 text-sm transition-colors ${
                      selected
                        ? "border-emerald-400 bg-emerald-500/15 text-emerald-100"
                        : "border-gray-800 bg-gray-900 text-gray-300 hover:border-gray-700"
                    }`}
                  >
                    <span>
                      {localizeTaxonomyValue("country", country, tCommon)}
                    </span>
                    {selected && <Check className="w-4 h-4" />}
                  </button>
                );
              })}
            </div>
            <span className="text-xs text-gray-500">
              {t("countriesSelected", { count: countryCount })}
            </span>
          </div>

          <div className="space-y-3">
            <span className={labelClass}>{t("targetServices")}</span>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {services.map((service) => {
                const selected = form.target_services.includes(service.value);
                return (
                  <label
                    key={service.value}
                    className={`flex items-center gap-3 rounded-lg border px-4 py-3 text-sm transition-colors ${
                      selected
                        ? "border-amber-400 bg-amber-500/10 text-amber-100"
                        : "border-gray-800 bg-gray-900 text-gray-300"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-amber-400"
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
          </div>
        </section>

        <section className="border border-gray-800 bg-gray-950 rounded-lg p-6 space-y-5">
          <div className="flex items-center gap-2 text-gray-200">
            <UserRound className="w-4 h-4 text-sky-300" />
            <h2 className="text-base font-semibold">{t("contact")}</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <label className="space-y-2">
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
            <label className="space-y-2">
              <span className={labelClass}>{t("phone")}</span>
              <div className="relative">
                <Phone className="w-4 h-4 text-gray-500 absolute start-4 top-1/2 -translate-y-1/2" />
                <input
                  dir="ltr"
                  className={`${inputClass} ps-11`}
                  value={form.phone_contact}
                  onChange={(event) =>
                    updateField("phone_contact", event.target.value)
                  }
                  required
                />
              </div>
            </label>
          </div>
          <label className="space-y-2 block">
            <span className={labelClass}>{t("notes")}</span>
            <textarea
              dir="auto"
              className={`${inputClass} min-h-28 resize-y`}
              value={form.notes}
              onChange={(event) => updateField("notes", event.target.value)}
            />
          </label>
        </section>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-5 py-3 text-sm font-semibold text-white hover:bg-cyan-500 disabled:bg-gray-700 disabled:text-gray-400 transition-colors"
          >
            {saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Check className="w-4 h-4" />
            )}
            {saving ? t("submitting") : t("submit")}
          </button>
        </div>
      </form>
    </div>
  );
}
