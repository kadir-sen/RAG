import { memo } from 'react';
import type { Citation } from '../../types/api';
import type { ViewerDoc } from '../../stores/uiStore';
import CitationChip from './CitationChip';

interface Props {
  citations?: Citation[];
  onChipClick: (doc: ViewerDoc) => void;
}

/**
 * Renders citation chips inline, appended to the end of the assistant text.
 * Hides itself when there are no valid citations.
 */
function InlineCitations({ citations, onChipClick }: Props) {
  if (!citations?.length) return null;
  // De-duplicate by doc_id so a citation that appears N times only renders once.
  const seen = new Set<string>();
  const unique: Citation[] = [];
  for (const c of citations) {
    if (!c.doc_id || !c.doc_id.trim()) continue;
    if (seen.has(c.doc_id)) continue;
    seen.add(c.doc_id);
    unique.push(c);
  }
  if (!unique.length) return null;

  return (
    <span className="inline-flex flex-wrap gap-1.5 align-baseline">
      {unique.map((c, i) => (
        <CitationChip
          key={`${c.doc_id}_${i}`}
          citation={c}
          onClick={() =>
            onChipClick({
              docId: c.doc_id,
              fileName: c.doc_name,
              anchor: c.anchor,
              highlightText: c.snippet,
            })
          }
        />
      ))}
    </span>
  );
}

export default memo(InlineCitations);
