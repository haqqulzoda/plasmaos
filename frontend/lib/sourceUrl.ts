/** Only expose backend-supplied web destinations; never construct source URLs. */
export function safeSourceUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return (url.protocol === "https:" || url.protocol === "http:") &&
      !url.username && !url.password && url.hostname
      ? url.href
      : null;
  } catch {
    return null;
  }
}
