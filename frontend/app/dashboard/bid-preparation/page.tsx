"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  FileText,
  Loader2,
  Clock,
  Banknote,
  MapPin,
  ArrowRight,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { formatCurrency, formatDate } from "@/i18n/formatters";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import Link from "next/link";
import { tenderStatusClasses } from "@/types/tender";
import { PrepareBidButton } from "@/components/bid-preparation/PrepareBidButton";
import {
  preparationStatusClasses,
  type BidPreparationArtifact,
} from "@/types/bid-preparation";

export default function BidPreparationPage() {
  const t = useTranslations("bidPreparation");
  const tExplorer = useTranslations("explorer");
  const tMy = useTranslations("myTenders");
  const locale = useLocale() as CustomerSelectableLocale;
  const [proposals, setProposals] = useState<BidPreparationArtifact[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchProposals = async () => {
      try {
        const response = await api.get("/proposals");
        setProposals(response.data);
      } catch (err) {
        console.error("Failed to fetch proposals:", err);
        setError(t("loadFailed"));
      } finally {
        setIsLoading(false);
      }
    };

    fetchProposals();
  }, [t]);

  const proposalStatus = (status: string) =>
    status === "DRAFT"
      ? t("status.draft")
      : status === "GENERATING"
        ? t("status.generating")
        : status === "COMPLETED"
          ? t("status.completed")
          : status === "SUBMITTED"
            ? t("status.submitted")
            : t("status.unknown");
  const tenderStatus = (status: string) =>
    status === "OPEN"
      ? tExplorer("status.open")
      : status === "CLOSED"
        ? tExplorer("status.closed")
        : status === "CANCELLED"
          ? tExplorer("status.cancelled")
          : tExplorer("status.unknown");
  const engagementStatus = (status: string) =>
    status === "SAVED"
      ? tMy("statuses.saved")
      : status === "EVALUATING"
        ? tMy("statuses.evaluating")
        : status === "PREPARING"
          ? tMy("statuses.preparing")
          : status === "SUBMITTED"
            ? tMy("statuses.submitted")
            : status === "WON"
              ? tMy("statuses.won")
              : status === "LOST"
                ? tMy("statuses.lost")
                : tMy("statuses.dismissed");

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 text-indigo-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between"
      >
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-purple-500/10 flex items-center justify-center">
            <FileText className="w-6 h-6 text-purple-500" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-white">{t("title")}</h1>
            <p className="text-zinc-400 mt-1">{t("subtitle")}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 px-4 py-2 bg-purple-500/10 border border-purple-500/20 rounded-full">
          <span className="text-purple-400 text-sm font-medium">
            {t("activeCount", { count: proposals.length })}
          </span>
        </div>
      </motion.div>

      {/* Error Alert */}
      {error && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-400"
        >
          {error}
        </motion.div>
      )}

      {/* Proposals List */}
      {proposals.length === 0 ? (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center"
        >
          <FileText className="w-16 h-16 text-zinc-600 mx-auto mb-4" />
          <h3 className="text-xl font-semibold text-white mb-2">
            {t("emptyTitle")}
          </h3>
          <p className="text-zinc-400 mb-6">{t("emptyHelp")}</p>
          <Link
            href="/dashboard/tenders"
            className="inline-flex items-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl transition-colors"
          >
            {t("browse")}
            <ArrowRight className="w-4 h-4" />
          </Link>
        </motion.div>
      ) : (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-4"
        >
          {proposals.map((proposal, index) => (
            <motion.div
              key={proposal.id}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.05 }}
            >
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 hover:border-indigo-500/50 transition-colors group">
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="text-lg font-semibold text-white truncate group-hover:text-indigo-400 transition-colors">
                        {proposal.tender_title}
                      </h3>
                      <span
                        className={`rounded-full border px-3 py-1 text-xs font-medium ${preparationStatusClasses(proposal.status)}`}
                      >
                        {t("preparationStatus", {
                          status: proposalStatus(proposal.status),
                        })}
                      </span>
                      <span
                        className={`rounded-full border px-3 py-1 text-xs font-medium ${tenderStatusClasses(proposal.tender_status)}`}
                      >
                        {t("tenderStatus", {
                          status: tenderStatus(proposal.tender_status),
                        })}
                      </span>
                      {proposal.engagement_status && (
                        <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1 text-xs font-medium text-sky-200">
                          {t("engagement", {
                            status: engagementStatus(
                              proposal.engagement_status,
                            ),
                          })}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-6 text-sm text-zinc-400">
                      <span className="flex items-center gap-1">
                        <Banknote className="w-4 h-4 text-green-400" />
                        <span className="text-green-400 font-medium">
                          {formatCurrency(
                            proposal.tender_budget,
                            proposal.tender_currency,
                            locale,
                            { maximumFractionDigits: 1 },
                          )}
                        </span>
                      </span>

                      {proposal.tender_region && (
                        <span className="flex items-center gap-1">
                          <MapPin className="w-4 h-4" />
                          {proposal.tender_region}
                        </span>
                      )}

                      <span className="flex items-center gap-1">
                        <Clock className="w-4 h-4" />
                        {t("created", {
                          date: formatDate(proposal.created_at, locale),
                        })}
                      </span>
                    </div>

                    {proposal.structured_data?.our_price && (
                      <div className="mt-3 pt-3 border-t border-zinc-800">
                        <span className="text-zinc-500 text-sm">
                          {t("yourPrice", {
                            value: formatCurrency(
                              proposal.structured_data.our_price,
                              proposal.tender_currency,
                              locale,
                              { maximumFractionDigits: 1 },
                            ),
                          })}
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-2 ml-4">
                    {!proposal.engagement_status && (
                      <PrepareBidButton proposalId={proposal.id} />
                    )}
                    <div className="text-right">
                      <div className="text-zinc-500 text-xs mb-1">
                        {t("aiConfidence")}
                      </div>
                      <div className="text-white font-bold">
                        {proposal.ai_confidence_score}%
                      </div>
                    </div>
                    <Link
                      href={`/dashboard/bid-preparation/${proposal.id}`}
                      className="inline-flex items-center gap-1 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:border-indigo-500 hover:text-indigo-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
                    >
                      {t("open")}
                      <ArrowRight className="w-4 h-4" />
                    </Link>
                  </div>
                </div>
              </div>
            </motion.div>
          ))}
        </motion.div>
      )}
    </div>
  );
}
