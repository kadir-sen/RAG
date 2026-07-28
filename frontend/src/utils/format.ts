/**
 * Number formatting for an English-only product.
 *
 * `n.toLocaleString()` with no locale follows the *browser's* locale, not the
 * product's. On a Turkish-configured machine that renders 27676 as "27.676",
 * which an English reader parses as a decimal — the chronology header read
 * "27.676 events on file" over a record of nearly twenty-eight thousand.
 *
 * COAir is English throughout: files, inputs, outputs. So the locale is stated
 * rather than inherited.
 */
const NUMBER = new Intl.NumberFormat('en-GB');

/** 27676 → "27,676". Same on every machine. */
export function count(n: number): string {
  return NUMBER.format(n);
}
