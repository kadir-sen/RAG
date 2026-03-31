import type { DocContent } from '../../types/api';

interface Props {
  content: DocContent;
  highlightText?: string;
}

export default function PdfViewer({ content, highlightText }: Props) {
  return (
    <div className="flex-1 overflow-auto p-2">
      {content.image_base64 && (
        <img
          src={`data:image/png;base64,${content.image_base64}`}
          alt={`Page ${content.page}`}
          className="w-full rounded"
        />
      )}
      {content.text && (
        <div className="mt-3 p-3 rounded bg-[var(--bg-secondary)] text-xs text-[var(--text-primary)] whitespace-pre-wrap leading-relaxed">
          {highlightText
            ? highlightSnippet(content.text, highlightText)
            : content.text}
        </div>
      )}
    </div>
  );
}

function highlightSnippet(text: string, highlight: string) {
  if (!highlight) return text;
  const idx = text.toLowerCase().indexOf(highlight.toLowerCase());
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-yellow-500/30 text-yellow-200 rounded px-0.5">
        {text.slice(idx, idx + highlight.length)}
      </mark>
      {text.slice(idx + highlight.length)}
    </>
  );
}
