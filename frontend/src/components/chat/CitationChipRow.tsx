import type { Citation } from '../../types/api';
import CitationChip from './CitationChip';
import type { ViewerDoc } from '../../stores/uiStore';

interface Props {
  citations: Citation[];
  onChipClick: (doc: ViewerDoc) => void;
}

export default function CitationChipRow({ citations, onChipClick }: Props) {
  if (!citations.length) return null;
  // Filter out citations with empty doc_id
  const validCitations = citations.filter(c => c.doc_id && c.doc_id.trim());
  if (!validCitations.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {validCitations.map((c, i) => (
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
    </div>
  );
}
