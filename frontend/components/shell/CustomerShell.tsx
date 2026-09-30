'use client';
import { useState, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTranslations } from 'next-intl';
import {
  Bookmark,
  Building2,
  LayoutDashboard,
  Search,
  LogOut,
  Menu,
  UserCircle,
  ChevronDown,
  ShieldCheck,
  Bell,
  Upload,
  Users,
} from 'lucide-react';
import { PlasmaLogo, PlasmaMark } from '@/components/brand/PlasmaLogo';
import { Button } from '@/components/ui/Button';
import { Drawer, Dropdown } from '@/components/ui/Overlay';
import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
import {
  CUSTOMER_NAVIGATION,
  activeNavigationKey,
  type CustomerNavigationKey,
} from '@/lib/customerNavigation';
// D1-07: one product. Destinations and active-state rules live in lib/customerNavigation.
const NAVIGATION_ICONS: Record<CustomerNavigationKey, typeof LayoutDashboard> = {
  dashboard: LayoutDashboard,
  opportunities: Search,
  pursuits: Bookmark,
  partnersExperts: Users,
  companyExperience: Building2,
  notifications: Bell,
};
const navigation = CUSTOMER_NAVIGATION.map((item) => ({ ...item, Icon: NAVIGATION_ICONS[item.nameKey] }));
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
  const activeKey = activeNavigationKey(path);
  const active = navigation.find((item) => item.nameKey === activeKey);
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
            <Link className="shell-upload-action ds-button ds-button-primary ds-button-sm" href="/dashboard/uploaded-tenders/upload" prefetch={false}>
              <Upload aria-hidden />
              <span>{t('uploadTender')}</span>
            </Link>
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
                {t('companyExperience')}
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
