import { memo } from 'react';

function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end mb-5 px-4 animate-fade-in-up">
      <div className="max-w-3xl flex items-start space-x-3">
        <div className="bg-[var(--user-bubble)] text-white px-5 py-3 rounded-2xl rounded-tr-sm text-sm leading-relaxed">
          {text}
        </div>
      </div>
    </div>
  );
}

export default memo(UserMessage);
