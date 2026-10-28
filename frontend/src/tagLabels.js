const TAG_PREFIXES = [
  'urn:tag:genre:music:',
  'urn:tag:genre:',
  'urn:tag:audience:qloo:',
  'urn:tag:style:qloo:',
  'urn:tag:music:qloo:',
  'urn:tag:',
];

// Qloo returns tags as URNs; the display drops the scheme and subtype prefix
// so "urn:tag:genre:music:dream pop" reads as "dream pop".
export function prettyTag(tag) {
  if (!tag) return '';
  const stripped = TAG_PREFIXES.find((prefix) => tag.startsWith(prefix));
  const value = (stripped ? tag.slice(stripped.length) : tag)
    .replace(/[:_]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return value || tag;
}
