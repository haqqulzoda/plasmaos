'use client';
import { useState, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTranslations } from 'next-intl';
import {
  Archive,
  Bookmark,
  Building2,
  LayoutDashboard,
  FileText,
  Search,
  LogOut,
  Settings,
  Menu,
  UserCircle,
  ChevronDown,
  ShieldCheck,
  Bell,
} from 'lucide-react';
import { PlasmaLogo, PlasmaMark } from '@/components/brand/PlasmaLogo';
import { Button } from '@/components/ui/Button';
import { Drawer, Dropdown } from '@/components/ui/Overlay';
import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
const navigation = [
  { nameKey: 'dashboard', href: '/dashboard', Icon: LayoutDashboard },
  { nameKey: 'tenders', href: '/dashboard/tenders', Icon: Search },
  { nameKey: 'myTenders', href: '/dashboard/my-tenders', Icon: Bookmark },
  {
    nameKey: 'bidPreparation',
    href: '/dashboard/bid-preparation',
    Icon: FileText,
  },
  { nameKey: 'companyProfile', href: '/dashboard/settings', Icon: Building2 },
  {
    nameKey: 'readinessVault',
    href: '/dashboard/readiness-vault',
    Icon: Archive,
  },
  { nameKey: 'notifications', href: '/dashboard/notifications', Icon: Bell },
] as const;
export function CustomerShell({
  children,
  name,
  email,
  company,
  canAdmin,
  onLogout,
  refresh,
  search,
  notifications,
}: {
  children: ReactNode;
  name?: string | null;
  email?: string | null;
  company?: string | null;
  canAdmin: boolean;
  onLogout: () => void;
  refresh?: ReactNode;
  search?: ReactNode;
  notifications?: ReactNode;
}) {
  const t = useTranslations('navigation');
  const path = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const active = navigation.find(
    (item) =>
      path === item.href ||
      (item.href !== '/dashboard' && path.startsWith(item.href + '/')),
  );
  const nav = (
    <nav className="shell-navigation" aria-label={t('navigationLabel')}>
      {navigation.map(({ nameKey, href, Icon }) => (
        <Link
          className="shell-nav-link"
          prefetch={false}
          href={href}
          key={nameKey}
          aria-current={active?.nameKey === nameKey ? 'page' : undefined}
          onClick={() => setMobileOpen(false)}
        >
          <Icon aria-hidden />
          <span>{t(nameKey)}</span>
        </Link>
      ))}
    </nav>
  );
  const footer = (
    <div className="shell-sidebar-footer">
      {canAdmin && (
        <Link className="shell-nav-link" href="/admin" prefetch={false}>
          <ShieldCheck aria-hidden />
          {t('adminConsole')}
        </Link>
      )}
      <Link
        className="shell-nav-link"
        href="/dashboard/settings"
        prefetch={false}
        onClick={() => setMobileOpen(false)}
      >
        <Settings aria-hidden />
        {t('settings')}
      </Link>
      <Button
        variant="ghost"
        onClick={onLogout}
        leadingIcon={<LogOut aria-hidden />}
      >
        {t('logout')}
      </Button>
    </div>
  );
  return (
    <div className="ds-theme app-shell" data-customer-shell>
      <a
        className="shell-skip ds-button ds-button-primary"
        href="#customer-main"
      >
        {t('skipToContent')}
      </a>
      <aside className="shell-sidebar">
        <Link
          className="shell-brand"
          href="/dashboard"
          prefetch={false}
          aria-label={t('dashboardLabel')}
        >
          <PlasmaLogo />
        </Link>
        {nav}
        {footer}
      </aside>
      <div className="shell-body">
        <header className="shell-topbar">
          <div className="ds-row">
            <Button
              className="shell-mobile-trigger"
              variant="icon"
              aria-label={t('openNavigation')}
              aria-expanded={mobileOpen}
              onClick={() => setMobileOpen(true)}
            >
              <Menu aria-hidden />
            </Button>
            <span className="shell-mobile-brand">
              <PlasmaMark size="sm" />
            </span>
            {path !== '/dashboard' && (
              <span className="shell-context">
                {active ? t(active.nameKey) : t('commandCenter')}
              </span>
            )}
          </div>
          <div className="shell-actions">
            {search}
            {refresh}
            {notifications}
            <Dropdown
              label={t('accountMenu')}
              trigger={
                <>
                  <UserCircle className="shell-account-icon" aria-hidden />
                  <BidiText className="shell-account-name">
                    {name || email || t('accountMenu')}
                  </BidiText>
                  <ChevronDown aria-hidden />
                </>
              }
            >
              <div className="shell-account-detail" role="none">
                {name && <BidiText className="block">{name}</BidiText>}
                {email && (
                  <TechnicalText className="block ds-muted">
                    {email}
                  </TechnicalText>
                )}
                {company && (
                  <BidiText className="block ds-muted">{company}</BidiText>
                )}
              </div>
              <Link
                role="menuitem"
                className="ds-button ds-button-ghost"
                href="/dashboard/settings"
                prefetch={false}
              >
                {t('companyProfile')}
              </Link>
              <Link
                role="menuitem"
                className="ds-button ds-button-ghost"
                href="/dashboard/settings"
                prefetch={false}
              >
                {t('settings')}
              </Link>
              {canAdmin && (
                <Link
                  role="menuitem"
                  className="ds-button ds-button-ghost"
                  href="/admin"
                  prefetch={false}
                >
                  {t('adminConsole')}
                </Link>
              )}
              <Button
                role="menuitem"
                variant="ghost"
                onClick={onLogout}
                leadingIcon={<LogOut aria-hidden />}
              >
                {t('logout')}
              </Button>
            </Dropdown>
          </div>
        </header>
        <main id="customer-main" tabIndex={-1} className="shell-main">
          <div className="shell-foundation-content">
            {children}
          </div>
        </main>
      </div>
      <Drawer
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        title={<PlasmaLogo />}
        closeLabel={t('closeNavigation')}
        side="start"
      >
        <div className="shell-mobile-navigation">
          {nav}
          {footer}
        </div>
      </Drawer>
    </div>
  );
}
