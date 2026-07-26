// Centralized design tokens for COAir.
// Every component reads file-type and provider colors from here so a single
// change in globals.css cascades through the whole UI.

export type FileTypeKey =
  | 'pdf'
  | 'xls'
  | 'eml'
  | 'doc'
  | 'csv'
  | 'fallback';

export interface FileTypeBadge {
  key: FileTypeKey;
  label: string;        // 3-letter monogram, e.g. "PDF"
  dot: string;          // CSS color (var(--type-*))
}

const FILE_TYPE_BADGES: Record<FileTypeKey, FileTypeBadge> = {
  pdf:      { key: 'pdf', label: 'PDF', dot: 'var(--type-pdf)' },
  xls:      { key: 'xls', label: 'XLS', dot: 'var(--type-xls)' },
  eml:      { key: 'eml', label: 'EML', dot: 'var(--type-eml)' },
  csv:      { key: 'csv', label: 'CSV', dot: 'var(--type-xls)' },
  doc:      { key: 'doc', label: 'DOC', dot: 'var(--text-muted)' },
  fallback: { key: 'fallback', label: 'DOC', dot: 'var(--text-muted)' },
};

// Maps backend file_type values to badges.
const FILE_TYPE_ALIASES: Record<string, FileTypeKey> = {
  document: 'pdf',
  pdf: 'pdf',
  data: 'xls',
  excel: 'xls',
  xls: 'xls',
  xlsx: 'xls',
  csv: 'csv',
  email: 'eml',
  eml: 'eml',
  msg: 'eml',
  text: 'doc',
  txt: 'doc',
  doc: 'doc',
  docx: 'doc',
  unknown: 'fallback',
};

// Resolve any backend `file_type` string (or a filename extension) to a badge.
// Accepts: 'document', 'data', 'email', 'pdf', 'xlsx', '.eml', etc.
export function getFileTypeBadge(input?: string | null): FileTypeBadge {
  if (!input) return FILE_TYPE_BADGES.fallback;
  const cleaned = input.toLowerCase().replace(/^\./, '').trim();
  const key = FILE_TYPE_ALIASES[cleaned] ?? 'fallback';
  return FILE_TYPE_BADGES[key];
}

// Resolve a badge from a filename + optional content type (used by viewer).
export function resolveFileTypeFromName(
  fileName: string,
  contentType?: string,
): FileTypeBadge {
  if (contentType === 'table') return FILE_TYPE_BADGES.xls;
  if (contentType === 'pdf') return FILE_TYPE_BADGES.pdf;
  const ext = fileName.toLowerCase().match(/\.([a-z0-9]+)$/)?.[1];
  return getFileTypeBadge(ext);
}

// LLM provider colors — read from CSS variables so theme changes cascade.
export type ProviderKey = 'gemini' | 'openai' | 'claude' | 'fallback';

export interface ProviderMeta {
  key: ProviderKey;
  label: string;
  color: string;
}

const PROVIDER_META: Record<ProviderKey, ProviderMeta> = {
  gemini:   { key: 'gemini', label: 'Gemini', color: 'var(--provider-gemini)' },
  openai:   { key: 'openai', label: 'OpenAI', color: 'var(--provider-openai)' },
  claude:   { key: 'claude', label: 'Claude', color: 'var(--provider-claude)' },
  fallback: { key: 'fallback', label: 'Provider', color: 'var(--provider-fallback)' },
};

export function getProviderMeta(provider?: string | null): ProviderMeta {
  if (!provider) return PROVIDER_META.fallback;
  const key = provider.toLowerCase() as ProviderKey;
  return PROVIDER_META[key] ?? { ...PROVIDER_META.fallback, label: provider };
}
