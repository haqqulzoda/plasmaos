export type MessageTree = {
    readonly [key: string]: string | MessageTree;
};

export type MessageCatalogIssue = Readonly<{
    locale: string;
    key: string;
    kind: 'missing_key' | 'extra_key' | 'placeholder_mismatch' | 'rich_placeholder_mismatch';
    expected?: readonly string[];
    actual?: readonly string[];
}>;

export function flattenMessageTree(
    tree: MessageTree,
    prefix = '',
): ReadonlyMap<string, string> {
    const messages = new Map<string, string>();

    for (const [segment, value] of Object.entries(tree)) {
        const key = prefix ? `${prefix}.${segment}` : segment;
        if (typeof value === 'string') {
            messages.set(key, value);
        } else {
            for (const [nestedKey, nestedValue] of flattenMessageTree(value, key)) {
                messages.set(nestedKey, nestedValue);
            }
        }
    }

    return messages;
}

export function extractIcuPlaceholders(message: string): readonly string[] {
    const placeholders = new Set<string>();
    const placeholderPattern = /\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:,|\})/g;

    for (const match of message.matchAll(placeholderPattern)) {
        placeholders.add(match[1]);
    }

    return [...placeholders].sort();
}

export function extractRichPlaceholders(message: string): readonly string[] {
    const tags = new Set<string>();
    for (const match of message.matchAll(/<\/?([A-Za-z][A-Za-z0-9_]*)>/g)) tags.add(match[1]);
    return [...tags].sort();
}

/**
 * CI catalog validator. English is the reference catalog; each supplied
 * target must have identical leaf keys and ICU placeholder names.
 */
export function validateMessageCatalogs(
    reference: MessageTree,
    targets: Readonly<Record<string, MessageTree>>,
): readonly MessageCatalogIssue[] {
    const expected = flattenMessageTree(reference);
    const issues: MessageCatalogIssue[] = [];

    for (const [locale, tree] of Object.entries(targets)) {
        const actual = flattenMessageTree(tree);

        for (const [key, expectedMessage] of expected) {
            const actualMessage = actual.get(key);
            if (actualMessage === undefined) {
                issues.push({locale, key, kind: 'missing_key'});
                continue;
            }

            const expectedPlaceholders = extractIcuPlaceholders(expectedMessage);
            const actualPlaceholders = extractIcuPlaceholders(actualMessage);
            if (expectedPlaceholders.join('\0') !== actualPlaceholders.join('\0')) {
                issues.push({
                    locale,
                    key,
                    kind: 'placeholder_mismatch',
                    expected: expectedPlaceholders,
                    actual: actualPlaceholders,
                });
            }
            const expectedRich = extractRichPlaceholders(expectedMessage);
            const actualRich = extractRichPlaceholders(actualMessage);
            if (expectedRich.join('\0') !== actualRich.join('\0')) {
                issues.push({
                    locale,
                    key,
                    kind: 'rich_placeholder_mismatch',
                    expected: expectedRich,
                    actual: actualRich,
                });
            }
        }

        for (const key of actual.keys()) {
            if (!expected.has(key)) {
                issues.push({locale, key, kind: 'extra_key'});
            }
        }
    }

    return issues;
}
