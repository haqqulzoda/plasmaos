'use client';
import { useState, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  ClipboardList,
  LayoutDashboard,
  Users,
  LogOut,
  Menu,
  UserCircle,
  ChevronDown,
  ExternalLink,
  Megaphone,
} from 'lucide-react';
import { PlasmaLogo, PlasmaMark } from '@/components/brand/PlasmaLogo';
import { Button } from '@/components/ui/Button';
import { Drawer, Dropdown } from '@/components/ui/Overlay';
import { BidiText, TechnicalText } from '@/components/i18n/BidiText';
const navigation = [
  { name: 'Overview', href: '/admin', Icon: LayoutDashboard },
  { name: 'Accounts', href: '/admin/approvals', Icon: Users },
  { name: 'Broadcasts', href: '/admin/broadcasts', Icon: Megaphone, adminOnly: true },
  {
    name: 'Audit activity',
    href: '/admin/audit',
    Icon: ClipboardList,
    adminOnly: true,
  },
];
/** Dedicated English/LTR business boundary; authorization remains in route layout. */
export function AdminShell({
  children,
  isEffectiveAdmin,
  name,
  email,
  onLogout,
  search,
}: {
  children: ReactNode;
  isEffectiveAdmin: boolean;
  name?: string | null;
  email?: string | null;
  onLogout: () => void;
  search?: ReactNode;
}) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const nav = (
    <nav aria-label="Admin navigation" className="shell-navigation">
      {navigation
        .filter((item) => !item.adminOnly || isEffectiveAdmin)
        .map(({ name, href, Icon }) => (
          <Link
            key={href}
            prefetch={false}
            href={href}
            className="shell-nav-link"
            aria-current={
              pathname === href ||
              (href !== '/admin' && pathname.startsWith(href + '/'))
                ? 'page'
                : undefined
            }
            onClick={() => setMobileOpen(false)}
          >
            <Icon aria-hidden />
            {name}
          </Link>
        ))}
    </nav>
  );
  const footer = (
    <div className="shell-sidebar-footer">
      <Link href="/dashboard" prefetch={false} className="shell-nav-link">
        <ExternalLink aria-hidden />
        User dashboard
      </Link>
      <Button
        variant="ghost"
        onClick={onLogout}
        leadingIcon={<LogOut aria-hidden />}
      >
        Logout
      </Button>
    </div>
  );
  return (
    <div
      lang="en"
      dir="ltr"
      className="ds-theme ds-admin app-shell"
    >
      <a className="shell-skip ds-button ds-button-primary" href="#admin-main">
        Skip to content
      </a>
      <aside className="shell-sidebar">
        <Link href="/admin" prefetch={false} className="shell-brand">
          <PlasmaLogo admin />
        </Link>
        {nav}
        {footer}
      </aside>
      <div className="shell-body">
        <header className="shell-topbar">
          <div className="ds-row">
            <Button
              variant="icon"
              className="shell-mobile-trigger"
              aria-label="Open navigation"
              aria-expanded={mobileOpen}
              onClick={() => setMobileOpen(true)}
            >
              <Menu aria-hidden />
            </Button>
            <span className="shell-mobile-brand">
              <PlasmaMark size="sm" />
            </span>
            <span className="shell-context">Administrative operations</span>
          </div>
          <div className="shell-actions">
            {search}
            <Link
              href="/dashboard"
              prefetch={false}
              className="ds-button ds-button-secondary shell-dashboard-link"
            >
              <ExternalLink aria-hidden />
              User dashboard
            </Link>
            <Dropdown
              label="Account menu"
              trigger={
                <>
                  <UserCircle className="shell-account-icon" aria-hidden />
                  <BidiText className="shell-account-name">
                    {name || email || 'Account'}
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
              </div>
              <Link
                href="/dashboard"
                role="menuitem"
                prefetch={false}
                className="ds-button ds-button-ghost"
              >
                User dashboard
              </Link>
              <Button role="menuitem" variant="ghost" onClick={onLogout}>
                Logout
              </Button>
            </Dropdown>
          </div>
        </header>
        <main id="admin-main" tabIndex={-1} className="shell-main">
          <div className="shell-foundation-content">
            {children}
          </div>
        </main>
      </div>
      <Drawer
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        title={<PlasmaLogo admin />}
        closeLabel="Close navigation"
        side="start"
      >
        {nav}
        {footer}
      </Drawer>
    </div>
  );
}
