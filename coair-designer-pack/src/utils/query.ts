// Some surfaces wrap a short user intent into a fuller backend prompt before
// sending (e.g. the Document Analysis topic box turns "Vingcard" into
// `Show me all documents related to "Vingcard", chronologically.`). The wrapper
// is an implementation detail of how we steer the model — the user only ever
// typed the topic, so we strip it back to that for display. Works for both
// live sends and conversations restored from the backend, since the transform
// lives at the render layer rather than in what we persist.
const WRAPPER_PATTERNS: RegExp[] = [
  /^Show me all documents related to "(.+)",\s*chronologically\.?$/i,
];

export function prettifyUserQuery(text: string): string {
  const trimmed = text.trim();
  for (const re of WRAPPER_PATTERNS) {
    const m = trimmed.match(re);
    if (m?.[1]) return m[1];
  }
  return text;
}
