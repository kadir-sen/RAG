import { memo } from 'react';
import Avatar from './Avatar';

interface Props {
  text: string;
  timestamp?: number;
}

function formatTime(ts?: number): string {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function UserMessage({ text, timestamp }: Props) {
  const time = formatTime(timestamp);
  return (
    <div className="mb-6 px-4 animate-fade-in-up group">
      <div className="max-w-3xl ml-auto flex items-start gap-3 justify-end">
        <div className="min-w-0 flex flex-col items-end">
          <div
            className="inline-block px-4 py-3 md:px-5 user-bubble text-sm leading-relaxed text-[var(--text-primary)] break-words whitespace-pre-wrap text-left"
          >
            {text}
          </div>
          {time && (
            <span className="mt-1 text-[10px] font-mono text-[var(--text-muted)] opacity-0 group-hover:opacity-100 transition-opacity">
              {time}
            </span>
          )}
        </div>
        <Avatar variant="user" />
      </div>
    </div>
  );
}

export default memo(UserMessage);
