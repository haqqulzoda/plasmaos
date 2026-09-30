"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Archive, Building2, Save } from "lucide-react";
import {
  PageHeader,
  SectionHeader,
  Surface,
  StatusBadge,
  PageSkeleton,
} from "@/components/ui/Display";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Input, Select, Checkbox } from "@/components/ui/Forms";
import { Alert } from "@/components/ui/Feedback";
import { BidiText, TechnicalText } from "@/components/i18n/BidiText";
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
import { useGeographyMeta } from "@/lib/geography";
import { useServiceMeta } from "@/lib/services";

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
  const pilotStatusLabel = (status: string) => {
    const labels = {
      lead: "pilotStates.lead",
      scoped_pilot: "pilotStates.scoped_pilot",
      active_pilot: "pilotStates.active_pilot",
      at_risk: "pilotStates.at_risk",
      converted: "pilotStates.converted",
      paused: "pilotStates.paused",
    } as const;
    return status in labels
      ? t(labels[status as keyof typeof labels])
      : accountStatusLabel(status);
  };
  const geography = useGeographyMeta();
  const services = useServiceMeta();
  const [profile, setProfile] = useState<CompanyProfile>(emptyProfile);
  const [persistedProfile, setPersistedProfile] =
    useState<CompanyProfile>(emptyProfile);
  const dirty = JSON.stringify(profile) !== JSON.stringify(persistedProfile);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<"loadFailed" | "saveFailed" | null>(null);
  const [analysisLanguage, setAnalysisLanguage] =
    useState<CustomerAnalysisLanguage>(DEFAULT_ANALYSIS_LANGUAGE);
  const [savedAnalysisLanguage, setSavedAnalysisLanguage] =
    useState<CustomerAnalysisLanguage>(DEFAULT_ANALYSIS_LANGUAGE);
  const [isLoadingAnalysisLanguage, setIsLoadingAnalysisLanguage] =
    useState(true);
  const [isSavingAnalysisLanguage, setIsSavingAnalysisLanguage] =
    useState(false);
  const [analysisLanguageSaved, setAnalysisLanguageSaved] = useState(false);
  const [analysisLanguageError, setAnalysisLanguageError] = useState<
    "analysisLanguage.loadFailed" | "analysisLanguage.saveFailed" | null
  >(null);

  const loadProfile = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response =
        await api.get<Partial<CompanyProfile>>("/users/me/company");
      setProfile(normalizeProfile(response.data));
      setPersistedProfile(normalizeProfile(response.data));
    } catch {
      console.error("Failed to load company profile:");
      setError("loadFailed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  useEffect(() => {
    let active = true;
    api
      .get<{ default_analysis_language?: string | null }>("/users/me")
      .then(({ data }) => {
        if (active) {
          const loadedLanguage = normalizeCustomerAnalysisLanguage(
            data.default_analysis_language,
          );
          setAnalysisLanguage(loadedLanguage);
          setSavedAnalysisLanguage(loadedLanguage);
        }
      })
      .catch(() => {
        if (active) setAnalysisLanguageError("analysisLanguage.loadFailed");
      })
      .finally(() => {
        if (active) setIsLoadingAnalysisLanguage(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const saveAnalysisLanguage = async () => {
    setIsSavingAnalysisLanguage(true);
    setAnalysisLanguageSaved(false);
    setAnalysisLanguageError(null);
    try {
      const { data } = await api.patch<{
        default_analysis_language: string | null;
      }>("/users/me/preferences", {
        default_analysis_language: analysisLanguage,
      });
      const persistedLanguage = normalizeCustomerAnalysisLanguage(
        data.default_analysis_language,
      );
      setAnalysisLanguage(persistedLanguage);
      setSavedAnalysisLanguage(persistedLanguage);
      setAnalysisLanguageSaved(true);
      window.setTimeout(() => setAnalysisLanguageSaved(false), 2500);
    } catch {
      setAnalysisLanguage(savedAnalysisLanguage);
      setAnalysisLanguageError("analysisLanguage.saveFailed");
    } finally {
      setIsSavingAnalysisLanguage(false);
    }
  };

  const updateField = (field: keyof CompanyProfile, value: string) => {
    setSaved(false);
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
      setPersistedProfile(normalizeProfile(response.data));
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2500);
    } catch {
      console.error("Failed to save company profile:");
      setError("saveFailed");
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (loading)
    return (
      <div className="customer-page">
        <PageSkeleton label={t("title")} />
      </div>
    );
  const tone = (status: string) =>
    status === "approved"
      ? ("success" as const)
      : status === "rejected"
        ? ("danger" as const)
        : status === "pending"
          ? ("warning" as const)
          : ("neutral" as const);
  return (
    <div className="customer-page profile-page">
      <PageHeader
        eyebrow={t("redesign.context")}
        title={t("title")}
        description={t("redesign.description")}
        primaryAction={
          <ButtonLink
            variant="secondary"
            href="/dashboard/readiness-vault"
            title={t("readinessHelp")}
            data-readiness-link
          >
            <Archive aria-hidden />
            {t("readinessLink")}
          </ButtonLink>
        }
      />
      {error && (
        <Alert
          tone="danger"
          title={t(error)}
          action={
            error === "loadFailed" ? (
              <Button onClick={loadProfile}>{t("redesign.retry")}</Button>
            ) : undefined
          }
        />
      )}
      <LanguageSelector surface="settings" foundation />
      <div className="profile-layout">
        <form
          id="company-profile-form"
          onSubmit={handleSubmit}
          className="profile-form"
        >
          <Surface className="profile-section">
            <SectionHeader
              title={t("company")}
              description={t("redesign.identityHelp")}
            />
            <div className="profile-fields">
              {(
                [
                  ["company_name", "companyName"],
                  ["industry", "industry"],
                  ["inn", "registrationNumber"],
                  ["website", "website"],
                  ["phone_contact", "phone"],
                  ["address", "address"],
                ] as const
              ).map(([field, label]) => (
                <Input
                  key={field}
                  label={t(label)}
                  dir={
                    ["inn", "website", "phone_contact"].includes(field)
                      ? "ltr"
                      : "auto"
                  }
                  type={
                    field === "website"
                      ? "url"
                      : field === "phone_contact"
                        ? "tel"
                        : "text"
                  }
                  value={profile[field]}
                  disabled={saving}
                  onChange={(event) => updateField(field, event.target.value)}
                />
              ))}
            </div>
          </Surface>
          <Surface className="profile-section">
            <SectionHeader
              title={t("marketsServices")}
              description={t("redesign.marketsHelp")}
            />
            <OptionGrid
              label={t("targetRegions")}
              options={geography.regions.map((value) => ({
                value,
                label: localizeTaxonomyValue("region", value, tCommon),
              }))}
              values={profile.target_regions}
              onToggle={(value) => toggleListField("target_regions", value)}
              disabled={saving}
            />
            <OptionGrid
              label={t("centralAsiaCountries")}
              options={geography.central_asia_countries.map((value) => ({
                value,
                label: localizeTaxonomyValue("country", value, tCommon),
              }))}
              values={profile.target_countries}
              onToggle={(value) => toggleListField("target_countries", value)}
              disabled={saving}
              actionLabel={
                geography.central_asia_countries.every((value) =>
                  profile.target_countries.includes(value),
                )
                  ? t("clearCentralAsia")
                  : t("selectCentralAsia")
              }
              onAction={toggleCentralAsiaCountries}
            />
            <OptionGrid
              label={t("targetServices")}
              options={services.map(({ value }) => ({
                value,
                label: localizeTaxonomyValue("service", value, tCommon),
              }))}
              values={profile.target_services}
              onToggle={(value) => toggleListField("target_services", value)}
              disabled={saving}
            />
          </Surface>
          <Surface className="profile-save ds-row">
            <span role="status" className="ds-muted">
              {dirty
                ? t("redesign.unsaved")
                : saved
                  ? t("profileSaved")
                  : t("redesign.upToDate")}
            </span>
            <Button
              variant="secondary"
              disabled={!dirty || saving}
              onClick={() => {
                setProfile(persistedProfile);
                setError(null);
                setSaved(false);
              }}
            >
              {t("redesign.cancel")}
            </Button>
            <Button
              type="submit"
              loading={saving}
              disabled={saving || error === "loadFailed"}
            >
              <Save aria-hidden />
              {t("saveProfile")}
            </Button>
          </Surface>
        </form>
        <aside className="profile-summary" aria-label={t("redesign.overview")}>
          <Surface className="profile-section">
            <SectionHeader title={t("redesign.overview")} />
            <Building2 aria-hidden />
            <h2>
              <BidiText>
                {persistedProfile.company_name || t("noneSelected")}
              </BidiText>
            </h2>
            <p className="ds-muted">
              <BidiText>{persistedProfile.industry}</BidiText>
            </p>
            <p>
              <BidiText>{persistedProfile.address}</BidiText>
            </p>
            <div className="ds-row">
              <StatusBadge tone={tone(profile.pilot_status)}>
                {t("pilotStatus", {
                  status: pilotStatusLabel(profile.pilot_status),
                })}
              </StatusBadge>
              <StatusBadge tone={tone(profile.approval_status)}>
                {t("approvalStatus", {
                  status: accountStatusLabel(profile.approval_status),
                })}
              </StatusBadge>
            </div>
            {persistedProfile.inn && (
              <p>
                <TechnicalText>{persistedProfile.inn}</TechnicalText>
              </p>
            )}
            {persistedProfile.website && (
              <p>
                <TechnicalText>{persistedProfile.website}</TechnicalText>
              </p>
            )}
          </Surface>
          {(
            ["target_regions", "target_countries", "target_services"] as const
          ).map((field, index) => (
            <Surface className="profile-section" key={field}>
              <SectionHeader
                title={t(
                  (
                    [
                      "targetRegions",
                      "targetCountries",
                      "targetServices",
                    ] as const
                  )[index],
                )}
              />
              <div className="ds-row">
                {persistedProfile[field].length ? (
                  persistedProfile[field].map((value) => (
                    <StatusBadge key={value}>
                      {localizeTaxonomyValue(
                        (["region", "country", "service"] as const)[index],
                        value,
                        tCommon,
                      )}
                    </StatusBadge>
                  ))
                ) : (
                  <span className="ds-muted">{t("noneSelected")}</span>
                )}
              </div>
            </Surface>
          ))}
        </aside>
      </div>
      <Surface
        className="profile-section"
        aria-labelledby="analysis-language-title"
      >
        <h2 id="analysis-language-title">{t("analysisLanguage.title")}</h2>
        <p className="ds-muted">{t("analysisLanguage.help")}</p>
        <div className="profile-preference ds-row">
          <Select
            label={t("analysisLanguage.label")}
            value={analysisLanguage}
            disabled={isLoadingAnalysisLanguage || isSavingAnalysisLanguage}
            onChange={(event) => {
              setAnalysisLanguage(
                event.target.value as CustomerAnalysisLanguage,
              );
              setAnalysisLanguageSaved(false);
            }}
          >
            {CUSTOMER_ANALYSIS_LANGUAGES.map((language) => (
              <option key={language.code} value={language.code}>
                {language.nativeLabel}
              </option>
            ))}
          </Select>
          <Button
            onClick={saveAnalysisLanguage}
            loading={isSavingAnalysisLanguage}
            disabled={isLoadingAnalysisLanguage || isSavingAnalysisLanguage}
          >
            {t("analysisLanguage.save")}
          </Button>
        </div>
        {analysisLanguageSaved && (
          <Alert tone="success" title={t("analysisLanguage.saved")} />
        )}
        {analysisLanguageError && (
          <Alert tone="danger" title={t(analysisLanguageError)} />
        )}
        <p className="ds-muted">{t("analysisLanguage.arabicGate")}</p>
      </Surface>
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
  disabled,
}: {
  label: string;
  options: { value: string; label: string }[];
  values: string[];
  onToggle: (value: string) => void;
  actionLabel?: string;
  onAction?: () => void;
  disabled?: boolean;
}) {
  return (
    <fieldset className="profile-options" disabled={disabled}>
      <legend>{label}</legend>
      {actionLabel && (
        <Button variant="secondary" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
      <div className="profile-choices">
        {options.map((option) => (
          <Checkbox
            key={option.value}
            label={option.label}
            checked={values.includes(option.value)}
            onChange={() => onToggle(option.value)}
          />
        ))}
      </div>
    </fieldset>
  );
}
