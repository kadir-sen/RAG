import { memo } from 'react';

function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end mb-6 px-4 animate-fade-in-up gap-3">
      <div className="max-w-[85%] md:max-w-3xl flex items-start">
        <div className="user-bubble text-white px-4 py-3 md:px-5 rounded-2xl rounded-tr-sm text-sm leading-relaxed break-words whitespace-pre-wrap ring-1 ring-white/5">
          {text}
        </div>
      </div>
      <div
        aria-hidden="true"
        className="flex-shrink-0 w-7 h-7 md:w-8 md:h-8 rounded-full bg-[var(--user-bubble)] text-white flex items-center justify-center mt-1 text-[11px] font-semibold ring-1 ring-white/10"
      >
        You
      </div>
    </div>
  );
}

export default memo(UserMessage);
