import { memo } from 'react';

function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end mb-5 px-4 animate-fade-in-up">
      <div className="max-w-[85%] md:max-w-3xl flex items-start">
        <div className="bg-[var(--user-bubble)] text-white px-4 py-3 md:px-5 rounded-2xl rounded-tr-sm text-sm leading-relaxed break-words whitespace-pre-wrap">
          {text}
        </div>
      </div>
    </div>
  );
}

export default memo(UserMessage);
