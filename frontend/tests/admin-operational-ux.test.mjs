import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import {
    actionConsequence,
    adminActionError,
    auditReasonLabel,
    safeStateSummary,
    statusLabel,
} from '../lib/adminOperations.ts';

const accounts = fs.readFileSync(new URL('../app/admin/approvals/page.tsx', import.meta.url), 'utf8');
const audit = fs.readFileSync(new URL('../app/admin/audit/page.tsx', import.meta.url), 'utf8');
const layout = fs.readFileSync(new URL('../app/admin/layout.tsx', import.meta.url), 'utf8');

test('canonical lifecycle language and restore consequence are truthful', () => {
    assert.equal(statusLabel('pending'), 'Pending');
    assert.equal(statusLabel('approved'), 'Approved');
    assert.equal(statusLabel('rejected'), 'Rejected');
    assert.equal(statusLabel('disabled'), 'Disabled');
    assert.match(actionConsequence('restore', 'rejected'), /return to Rejected/);
    assert.match(actionConsequence('restore', null), /return to Pending/);
    assert.match(actionConsequence('disable'), /sessions and credentials will become invalid/);
    assert.match(actionConsequence('approve'), /must sign in again/);
});

test('security errors are safe and stale state always refreshes', () => {
    const stale = adminActionError({ response: { status: 409, data: { detail: 'Cannot disable account' } } });
    assert.equal(stale.refresh, true);
    assert.match(stale.message, /latest state has been refreshed/);
    const lastAdmin = adminActionError({ response: { status: 409, data: { detail: 'At least one effective administrator must remain' } } });
    assert.match(lastAdmin.message, /last active administrator/);
    assert.doesNotMatch(lastAdmin.message, /effective administrator must remain/i);
    assert.equal(adminActionError({ response: { status: 403 } }).authorityLost, true);
    assert.equal(adminActionError({ response: { status: 401 } }).authorityLost, true);
});

test('audit summaries expose only semantic allowlisted state', () => {
    assert.deepEqual(
        safeStateSummary({ approval_status: 'disabled', credentials_invalidated: true, auth_version: 42, access_token: 'nope' }),
        ['Account status: Disabled', 'Credentials invalidated: Yes'],
    );
    assert.equal(auditReasonLabel('SELF_ACTION_PROHIBITED'), 'Self-action blocked');
    assert.equal(auditReasonLabel('TRANSACTION_FAILED'), 'Transaction failed; no state changed');
});

test('accounts use backend capabilities, stable identity, confirmations, and bounded pages', () => {
    assert.match(accounts, /\/admin\/accounts/);
    assert.match(accounts, /account\.allowed_actions\.map/);
    assert.match(accounts, /account\.is_current_actor/);
    assert.doesNotMatch(accounts, /session\?\.user\?\.email/);
    assert.doesNotMatch(accounts, /window\.prompt/);
    assert.match(accounts, /role="dialog"/);
    assert.match(accounts, /aria-modal="true"/);
    assert.match(accounts, /PAGE_SIZE = 25/);
    assert.match(accounts, /await loadAccounts\(\)/);
    assert.doesNotMatch(accounts, /auth_version|pre_disabled_approval_status|google_id/);
});

test('audit surface is canonical, sanitized, filtered, and paginated', () => {
    assert.match(audit, /\/admin\/audit-events/);
    assert.match(audit, /SUCCESS/);
    assert.match(audit, /DENIED/);
    assert.match(audit, /FAILED/);
    assert.match(audit, /Legacy event/);
    assert.match(audit, /safeStateSummary/);
    assert.match(audit, /PAGE_SIZE = 25/);
    assert.doesNotMatch(audit, /metadata|auth_version|access_token|google_id/);
    assert.match(layout, /adminOnly: true/);
});
