import type { DocContent } from '../../types/api';

interface Props {
  content: DocContent;
  highlightText?: string;
}

export default function TextViewer({ content, highlightText }: Props) {
  return (
    <div className="flex-1 overflow-auto p-4">
      <pre className="text-sm text-[var(--text-primary)] whitespace-pre-wrap leading-relaxed">
        {highlightText
          ? renderHighlighted(content.text, highlightText)
          : content.text}
      </pre>
    </div>
  );
}

function renderHighlighted(text: string, highlight: string) {
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
