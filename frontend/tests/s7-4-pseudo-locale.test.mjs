import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

import {flattenMessageTree} from '../i18n/messageValidation.ts';
import {
  PSEUDO_LOCALE_CODE,
  isPseudoLocaleEnabled,
  pseudoLocalizeMessage,
  pseudoLocalizeMessages,
} from '../i18n/pseudoLocale.ts';
import {MESSAGE_NAMESPACES} from '../i18n/locales.ts';

const en = Object.fromEntries(MESSAGE_NAMESPACES.map((namespace) => [
  namespace,
  JSON.parse(readFileSync(new URL(`../messages/en/${namespace}.json`, import.meta.url), 'utf8')),
]));

test('pseudo locale expands deterministic static copy and preserves placeholders', () => {
  const input = 'Refreshing {source} safely';
  const output = pseudoLocalizeMessage(input);
  assert.equal(output, pseudoLocalizeMessage(input));
  assert.ok(output.length >= input.length * 1.3);
  assert.match(output, /^⟦/);
  assert.match(output, /\{source\}/);
  assert.doesNotMatch(output, /World Bank/);
});

test('pseudo catalog preserves shape, ICU blocks, and rich tags', () => {
  const pseudo = pseudoLocalizeMessages(en);
  assert.equal(flattenMessageTree(pseudo).size, flattenMessageTree(en).size);
  assert.match(pseudo.common.tenderCount, /\{count, plural,/);
  assert.match(pseudo.common.tenderCount, /Ñø˜ ţë˜ñð˜ëŕ˜š/);
  assert.match(pseudo.common.richReview, /<strong>\{source\}<\/strong>/);
});

test('pseudo locale is gated away from production and is not a customer locale', async () => {
  assert.equal(PSEUDO_LOCALE_CODE, 'en-XA');
  assert.equal(isPseudoLocaleEnabled({NODE_ENV: 'development', PLASMA_ENABLE_PSEUDO_LOCALE: '1'}), true);
  assert.equal(isPseudoLocaleEnabled({NODE_ENV: 'test', PLASMA_ENABLE_PSEUDO_LOCALE: '1'}), true);
  assert.equal(isPseudoLocaleEnabled({NODE_ENV: 'production', PLASMA_ENABLE_PSEUDO_LOCALE: '1'}), false);
  const {CUSTOMER_SELECTABLE_LOCALES} = await import('../i18n/locales.ts');
  assert.deepEqual(CUSTOMER_SELECTABLE_LOCALES, ['en', 'uz', 'ru']);
  assert.ok(!CUSTOMER_SELECTABLE_LOCALES.includes(PSEUDO_LOCALE_CODE));
});
