import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import "./globals.css";
import { Providers } from "./providers";
import { ErrorReporting } from "@/components/ErrorReporting";
import { errorTrackingConfig } from "@/lib/errorTracking";
import { directionForLocale } from "@/i18n/locales";

export const metadata: Metadata = {
  title: "Plasma AI",
  description: "Procurement Intelligence Platform",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const [locale, messages] = await Promise.all([getLocale(), getMessages()]);
  return (
    <html lang={locale} dir={directionForLocale(locale)}>
      <body className="antialiased">
        <ErrorReporting config={errorTrackingConfig()} />
        <NextIntlClientProvider locale={locale} messages={messages}>
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
