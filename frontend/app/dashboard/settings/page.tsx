"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Building2, Check, Globe2, Loader2, Phone, Save } from "lucide-react";
import { useTranslations } from "next-intl";
import { LanguageSelector } from "@/components/i18n/LanguageSelector";
import {
  CUSTOMER_ANALYSIS_LANGUAGES,
  DEFAULT_ANALYSIS_LANGUAGE,
  normalizeCustomerAnalysisLanguage,
  type CustomerAnalysisLanguage,
} from "@/i18n/analysisLanguages";
import { localizeTaxonomyValue } from "@/i18n/taxonomy";
import { api } from "@/lib/api";
import { CENTRAL_ASIA_REGION, useGeographyMeta } from "@/lib/geography";
import type { ServiceOption } from "@/lib/services";
import { labelForService, useServiceMeta } from "@/lib/services";

type CompanyProfile = {
  company_name: string;
  industry: string;
  inn: string;
  website: string;
  phone_contact: string;
  address: string;
  target_regions: string[];
  target_countries: string[];
  target_services: string[];
  pilot_status: string;
  approval_status: string;
};

const emptyProfile: CompanyProfile = {
  company_name: "",
  industry: "",
  inn: "",
  website: "",
  phone_contact: "",
  address: "",
  target_regions: [],
  target_countries: [],
  target_services: [],
  pilot_status: "",
  approval_status: "",
};

const inputClass =
  "w-full bg-gray-950 border border-gray-800 rounded-lg px-4 py-3 text-gray-100 text-sm placeholder-gray-600 outline-none focus:ring-2 focus:ring-cyan-500/40 focus:border-cyan-500 transition-all";

const labelClass = "text-sm font-medium text-gray-300";

const statusClass = (status: string) => {
  if (status === "approved")
    return "border-emerald-500/20 bg-emerald-500/10 text-emerald-200";
  if (status === "pending")
    return "border-amber-500/20 bg-amber-500/10 text-amber-200";
  if (status === "rejected")
    return "border-red-500/20 bg-red-500/10 text-red-200";
  if (status === "disabled") return "border-gray-700 bg-gray-900 text-gray-300";
  return "border-cyan-500/20 bg-cyan-500/10 text-cyan-200";
};

function toggleValue(values: string[], value: string): string[] {
  if (values.includes(value)) {
    return values.filter((item) => item !== value);
  }
  return [...values, value];
}

function normalizeProfile(data: Partial<CompanyProfile>): CompanyProfile {
  return {
    company_name: data.company_name ?? "",
    industry: data.industry ?? "",
    inn: data.inn ?? "",
    website: data.website ?? "",
    phone_contact: data.phone_contact ?? "",
    address: data.address ?? "",
    target_regions: data.target_regions ?? [],
    target_countries: data.target_countries ?? [],
    target_services: data.target_services ?? [],
    pilot_status: data.pilot_status ?? "",
    approval_status: data.approval_status ?? "",
  };
}

export default function CompanyProfilePage() {
  const t = useTranslations("settings");
  const tCommon = useTranslations("common");
  const accountStatusLabel = (status: string) => {
    if (status === "approved") return t("status.approved");
    if (status === "pending") return t("status.pending");
    if (status === "rejected") return t("status.rejected");
    if (status === "disabled") return t("status.disabled");
    return t("status.unknown");
  };
  const geography = useGeographyMeta();
  const services = useServiceMeta();
  const [profile, setProfile] = useState<CompanyProfile>(emptyProfile);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analysisLanguage, setAnalysisLanguage] = useState<CustomerAnalysisLanguage>(DEFAULT_ANALYSIS_LANGUAGE);
  const [savedAnalysisLanguage, setSavedAnalysisLanguage] = useState<CustomerAnalysisLanguage>(DEFAULT_ANALYSIS_LANGUAGE);
  const [isLoadingAnalysisLanguage, setIsLoadingAnalysisLanguage] = useState(true);
  const [isSavingAnalysisLanguage, setIsSavingAnalysisLanguage] = useState(false);
  const [analysisLanguageSaved, setAnalysisLanguageSaved] = useState(false);
  const [analysisLanguageError, setAnalysisLanguageError] = useState<string | null>(null);

  const loadProfile = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response =
        await api.get<Partial<CompanyProfile>>("/users/me/company");
      setProfile(normalizeProfile(response.data));
    } catch (err) {
      console.error("Failed to load company profile:", err);
      setError(t("loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  useEffect(() => {
    let active = true;
    api.get<{ default_analysis_language?: string | null }>("/users/me")
      .then(({ data }) => {
        if (active) {
          const loadedLanguage = normalizeCustomerAnalysisLanguage(data.default_analysis_language);
          setAnalysisLanguage(loadedLanguage);
          setSavedAnalysisLanguage(loadedLanguage);
        }
      })
      .catch(() => {
        if (active) setAnalysisLanguageError(t("analysisLanguage.loadFailed"));
      })
      .finally(() => {
        if (active) setIsLoadingAnalysisLanguage(false);
      });
    return () => { active = false; };
  }, [t]);

  const saveAnalysisLanguage = async () => {
    setIsSavingAnalysisLanguage(true);
    setAnalysisLanguageSaved(false);
    setAnalysisLanguageError(null);
    try {
      const { data } = await api.patch<{ default_analysis_language: string | null }>(
        "/users/me/preferences",
        { default_analysis_language: analysisLanguage },
      );
      const persistedLanguage = normalizeCustomerAnalysisLanguage(data.default_analysis_language);
      setAnalysisLanguage(persistedLanguage);
      setSavedAnalysisLanguage(persistedLanguage);
      setAnalysisLanguageSaved(true);
      window.setTimeout(() => setAnalysisLanguageSaved(false), 2500);
    } catch {
      setAnalysisLanguage(savedAnalysisLanguage);
      setAnalysisLanguageError(t("analysisLanguage.saveFailed"));
    } finally {
      setIsSavingAnalysisLanguage(false);
    }
  };

  const updateField = (field: keyof CompanyProfile, value: string) => {
    setProfile((current) => ({ ...current, [field]: value }));
  };

  const toggleListField = (
    field: "target_regions" | "target_countries" | "target_services",
    value: string,
  ) => {
    setProfile((current) => ({
      ...current,
      [field]: toggleValue(current[field], value),
    }));
  };

  const toggleCentralAsiaCountries = () => {
    setProfile((current) => {
      const selected = geography.central_asia_countries.every((country) =>
        current.target_countries.includes(country),
      );
      const centralAsiaCountrySet = new Set(geography.central_asia_countries);

      return {
        ...current,
        target_countries: selected
          ? current.target_countries.filter(
              (country) => !centralAsiaCountrySet.has(country),
            )
          : Array.from(
              new Set([
                ...current.target_countries,
                ...geography.central_asia_countries,
              ]),
            ),
      };
    });
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setSaved(false);
    setError(null);

    try {
      const response = await api.put<Partial<CompanyProfile>>(
        "/users/me/company",
        {
          company_name: profile.company_name || null,
          industry: profile.industry || null,
          inn: profile.inn || null,
          website: profile.website || null,
          phone_contact: profile.phone_contact || null,
          address: profile.address || null,
          target_regions: profile.target_regions,
          target_countries: profile.target_countries,
          target_services: profile.target_services,
        },
      );
      setProfile(normalizeProfile(response.data));
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      console.error("Failed to save company profile:", err);
      setError(t("saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-cyan-300" />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-cyan-500/20 bg-cyan-500/10">
            <Building2 className="h-5 w-5 text-cyan-300" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-white">{t("title")}</h1>
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              <span
                className={`rounded border px-2 py-1 ${statusClass(profile.pilot_status)}`}
              >
                {t("pilotStatus", {
                  status: accountStatusLabel(profile.pilot_status),
                })}
              </span>
              <span
                className={`rounded border px-2 py-1 ${statusClass(profile.approval_status)}`}
              >
                {t("approvalStatus", {
                  status: accountStatusLabel(profile.approval_status),
                })}
              </span>
            </div>
          </div>
        </div>
      </div>

      <LanguageSelector surface="settings" />

      <section className="space-y-4 rounded-lg border border-gray-800 bg-gray-950 p-6" aria-labelledby="analysis-language-title">
        <div className="flex items-center gap-2 text-gray-200">
          <Globe2 className="h-4 w-4 text-indigo-300" />
          <h2 id="analysis-language-title" className="text-base font-semibold">
            {t("analysisLanguage.title")}
          </h2>
        </div>
        <p className="max-w-2xl text-sm leading-relaxed text-gray-400">
          {t("analysisLanguage.help")}
        </p>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="w-full max-w-sm space-y-2">
            <span className={labelClass}>{t("analysisLanguage.label")}</span>
            <select
              className={inputClass}
              value={analysisLanguage}
              disabled={isLoadingAnalysisLanguage || isSavingAnalysisLanguage}
              onChange={(event) => setAnalysisLanguage(event.target.value as CustomerAnalysisLanguage)}
            >
              {CUSTOMER_ANALYSIS_LANGUAGES.map((language) => (
                <option key={language.code} value={language.code}>{language.nativeLabel}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={saveAnalysisLanguage}
            disabled={isLoadingAnalysisLanguage || isSavingAnalysisLanguage}
            className="inline-flex h-[46px] items-center justify-center gap-2 rounded-lg bg-indigo-600 px-5 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-wait disabled:opacity-60"
          >
            {isSavingAnalysisLanguage ? <Loader2 className="h-4 w-4 animate-spin" /> : analysisLanguageSaved ? <Check className="h-4 w-4" /> : <Save className="h-4 w-4" />}
            {analysisLanguageSaved ? t("analysisLanguage.saved") : t("analysisLanguage.save")}
          </button>
        </div>
        {analysisLanguageError && <p className="text-sm text-red-300">{analysisLanguageError}</p>}
        <p className="text-xs text-gray-500">{t("analysisLanguage.arabicGate")}</p>
      </section>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <TargetSummary
        profile={profile}
        services={services.map((service) => ({
          ...service,
          label: localizeTaxonomyValue("service", service.value, tCommon),
        }))}
      />

      <form onSubmit={handleSubmit} className="space-y-6">
        <section className="space-y-5 rounded-lg border border-gray-800 bg-gray-950 p-6">
          <div className="flex items-center gap-2 text-gray-200">
            <Building2 className="h-4 w-4 text-cyan-300" />
            <h2 className="text-base font-semibold">{t("company")}</h2>
          </div>
          <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
            <label className="space-y-2">
              <span className={labelClass}>{t("companyName")}</span>
              <input
                dir="auto"
                className={inputClass}
                value={profile.company_name}
                onChange={(event) =>
                  updateField("company_name", event.target.value)
                }
              />
            </label>
            <label className="space-y-2">
              <span className={labelClass}>{t("industry")}</span>
              <input
                dir="auto"
                className={inputClass}
                value={profile.industry}
                onChange={(event) =>
                  updateField("industry", event.target.value)
                }
              />
            </label>
            <label className="space-y-2">
              <span className={labelClass}>{t("registrationNumber")}</span>
              <input
                dir="ltr"
                className={inputClass}
                value={profile.inn}
                onChange={(event) => updateField("inn", event.target.value)}
              />
            </label>
            <label className="space-y-2">
              <span className={labelClass}>{t("website")}</span>
              <input
                dir="ltr"
                className={inputClass}
                value={profile.website}
                onChange={(event) => updateField("website", event.target.value)}
                placeholder="https://"
                type="url"
              />
            </label>
            <label className="space-y-2">
              <span className={labelClass}>{t("phone")}</span>
              <div className="relative">
                <Phone className="absolute start-4 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                <input
                  dir="ltr"
                  className={`${inputClass} ps-11`}
                  value={profile.phone_contact}
                  onChange={(event) =>
                    updateField("phone_contact", event.target.value)
                  }
                />
              </div>
            </label>
            <label className="space-y-2">
              <span className={labelClass}>{t("address")}</span>
              <input
                dir="auto"
                className={inputClass}
                value={profile.address}
                onChange={(event) => updateField("address", event.target.value)}
              />
            </label>
          </div>
        </section>

        <section className="space-y-5 rounded-lg border border-gray-800 bg-gray-950 p-6">
          <div className="flex items-center gap-2 text-gray-200">
            <Globe2 className="h-4 w-4 text-emerald-300" />
            <h2 className="text-base font-semibold">{t("marketsServices")}</h2>
          </div>
          <OptionGrid
            label={t("targetRegions")}
            options={geography.regions.map((region) => ({
              value: region,
              label: localizeTaxonomyValue("region", region, tCommon),
            }))}
            values={profile.target_regions}
            onToggle={(value) => toggleListField("target_regions", value)}
          />
          <OptionGrid
            label={t("centralAsiaCountries")}
            options={geography.central_asia_countries.map((country) => ({
              value: country,
              label: localizeTaxonomyValue("country", country, tCommon),
            }))}
            values={profile.target_countries}
            onToggle={(value) => toggleListField("target_countries", value)}
            actionLabel={
              geography.central_asia_countries.every((country) =>
                profile.target_countries.includes(country),
              )
                ? t("clearCentralAsia")
                : t("selectCentralAsia")
            }
            onAction={toggleCentralAsiaCountries}
          />
          <OptionGrid
            label={t("targetServices")}
            options={services.map((service) => ({
              ...service,
              label: localizeTaxonomyValue("service", service.value, tCommon),
            }))}
            values={profile.target_services}
            onToggle={(value) => toggleListField("target_services", value)}
          />
        </section>

        <div className="flex items-center justify-end gap-3">
          {saved && (
            <span className="inline-flex items-center gap-2 text-sm text-emerald-300">
              <Check className="h-4 w-4" />
              {t("profileSaved")}
            </span>
          )}
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-cyan-500 disabled:bg-gray-700 disabled:text-gray-400"
          >
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            {t("saveProfile")}
          </button>
        </div>
      </form>
    </div>
  );
}

function TargetSummary({
  profile,
  services,
}: {
  profile: CompanyProfile;
  services: ServiceOption[];
}) {
  const t = useTranslations("settings");
  return (
    <section className="grid grid-cols-1 gap-4 rounded-lg border border-gray-800 bg-gray-950 p-5 md:grid-cols-3">
      <SummaryGroup
        label={t("targetRegions")}
        values={profile.target_regions}
      />
      <SummaryGroup
        label={t("targetCountries")}
        values={profile.target_countries}
      />
      <SummaryGroup
        label={t("targetServices")}
        values={profile.target_services.map((service) =>
          labelForService(service, services),
        )}
      />
    </section>
  );
}

function SummaryGroup({ label, values }: { label: string; values: string[] }) {
  const t = useTranslations("settings");
  return (
    <div className="space-y-3">
      <div className={labelClass}>{label}</div>
      <div className="flex flex-wrap gap-2">
        {values.length > 0 ? (
          values.map((value) => {
            const isCentralAsia = value === CENTRAL_ASIA_REGION;
            return (
              <span
                key={value}
                className={`rounded border px-2 py-1 text-xs ${
                  isCentralAsia
                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-100"
                    : "border-gray-700 bg-gray-900 text-gray-300"
                }`}
              >
                {value}
              </span>
            );
          })
        ) : (
          <span className="text-sm text-gray-500">{t("noneSelected")}</span>
        )}
      </div>
    </div>
  );
}

function OptionGrid({
  label,
  options,
  values,
  onToggle,
  actionLabel,
  onAction,
}: {
  label: string;
  options: ServiceOption[];
  values: string[];
  onToggle: (value: string) => void;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className={labelClass}>{label}</span>
        {actionLabel && onAction && (
          <button
            type="button"
            onClick={onAction}
            className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-100 transition-colors hover:border-emerald-300"
          >
            <Check className="h-3.5 w-3.5" />
            {actionLabel}
          </button>
        )}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {options.map((option) => {
          const selected = values.includes(option.value);
          const isCentralAsia = option.value === CENTRAL_ASIA_REGION;
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => onToggle(option.value)}
              className={`flex min-h-12 items-center justify-between rounded-lg border px-4 py-3 text-start text-sm transition-colors ${
                selected
                  ? isCentralAsia
                    ? "border-emerald-400 bg-emerald-500/15 text-emerald-100"
                    : "border-cyan-400 bg-cyan-500/10 text-cyan-100"
                  : isCentralAsia
                    ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-200 hover:border-emerald-400"
                    : "border-gray-800 bg-gray-900 text-gray-300 hover:border-gray-700"
              }`}
            >
              <span className="break-words">{option.label}</span>
              {selected && <Check className="ms-3 h-4 w-4 shrink-0" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}
