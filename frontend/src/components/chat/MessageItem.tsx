import { memo } from 'react';
import type { Message } from '../../types/chat';
import type { ViewerDoc } from '../../stores/uiStore';
import UserMessage from './UserMessage';
import AssistantMessage from './AssistantMessage';

interface Props {
  message: Message;
  onDocClick: (doc: ViewerDoc) => void;
}

function MessageItem({ message, onDocClick }: Props) {
  if (message.role === 'user') {
    return <UserMessage text={message.content} />;
  }
  return (
    <AssistantMessage
      text={message.content}
      response={message.response}
      onDocClick={onDocClick}
    />
  );
}

export default memo(MessageItem);
