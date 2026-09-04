import type {MessageTree} from './messageValidation';

export const PSEUDO_LOCALE_CODE = 'en-XA' as const;
export const PSEUDO_LOCALE_HEADER = 'x-plasma-pseudo-locale';

const ACCENTS: Record<string, string> = {
  A: 'Å', B: 'Ɓ', C: 'Ç', D: 'Ð', E: 'Ë', F: 'Ƒ', G: 'Ĝ', H: 'Ħ', I: 'Ï', J: 'Ĵ',
  K: 'Ķ', L: 'Ŀ', M: 'Ḿ', N: 'Ñ', O: 'Ø', P: 'Þ', Q: 'Q', R: 'Ŕ', S: 'Š', T: 'Ţ',
  U: 'Û', V: 'Ṽ', W: 'Ŵ', X: 'Ẋ', Y: 'Ÿ', Z: 'Ž',
  a: 'à', b: 'ƀ', c: 'ç', d: 'ð', e: 'ë', f: 'ƒ', g: 'ĝ', h: 'ħ', i: 'ï', j: 'ĵ',
  k: 'ķ', l: 'ŀ', m: 'ḿ', n: 'ñ', o: 'ø', p: 'þ', q: 'q', r: 'ŕ', s: 'š', t: 'ţ',
  u: 'û', v: 'ṽ', w: 'ŵ', x: 'ẋ', y: 'ÿ', z: 'ž',
};

function transformStatic(value: string): string {
  let letters = 0;
  let result = '';
  for (const character of value) {
    result += ACCENTS[character] ?? character;
    if (/[A-Za-z]/.test(character) && ++letters % 2 === 0) result += '˜';
  }
  return result;
}

function transformIcuBlock(block: string): string {
  if (!/,\s*(?:plural|select|selectordinal)\s*,/.test(block)) return block;
  return block.replace(
    /([=A-Za-z0-9_-]+)(\s*)\{([^{}]*)\}/g,
    (_match, selector: string, spacing: string, branch: string) =>
      `${selector}${spacing}{${transformStatic(branch)}}`,
  );
}

/** Deterministic LTR stress transform. ICU placeholders and rich-message tags stay exact. */
export function pseudoLocalizeMessage(message: string): string {
  let result = '';
  let staticBuffer = '';
  const flush = () => {
    result += transformStatic(staticBuffer);
    staticBuffer = '';
  };

  for (let index = 0; index < message.length;) {
    if (message[index] === '{') {
      flush();
      let depth = 0;
      let end = index;
      do {
        if (message[end] === '{') depth += 1;
        if (message[end] === '}') depth -= 1;
        end += 1;
      } while (end < message.length && depth > 0);
      result += transformIcuBlock(message.slice(index, end));
      index = end;
      continue;
    }
    if (message[index] === '<') {
      flush();
      const end = message.indexOf('>', index);
      if (end >= 0) {
        result += message.slice(index, end + 1);
        index = end + 1;
        continue;
      }
    }
    staticBuffer += message[index];
    index += 1;
  }
  flush();
  return `⟦${result}⟧`;
}

export function pseudoLocalizeMessages(messages: MessageTree): MessageTree {
  return Object.fromEntries(Object.entries(messages).map(([key, value]) => [
    key,
    typeof value === 'string' ? pseudoLocalizeMessage(value) : pseudoLocalizeMessages(value),
  ]));
}

export function isPseudoLocaleEnabled(environment: NodeJS.ProcessEnv = process.env): boolean {
  return environment.NODE_ENV !== 'production' && environment.PLASMA_ENABLE_PSEUDO_LOCALE === '1';
}
