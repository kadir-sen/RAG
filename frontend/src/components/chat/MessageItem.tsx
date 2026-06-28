import { memo } from 'react';
import type { Message } from '../../types/chat';
import type { ViewerDoc } from '../../stores/uiStore';
import UserMessage from './UserMessage';
import AssistantMessage from './AssistantMessage';

interface Props {
  message: Message;
  onDocClick: (doc: ViewerDoc) => void;
  onRetry?: (text: string) => void;
}

function MessageItem({ message, onDocClick, onRetry }: Props) {
  if (message.role === 'user') {
    return <UserMessage text={message.content} timestamp={message.timestamp} />;
  }
  return (
    <AssistantMessage
      text={message.content}
      response={message.response}
      timestamp={message.timestamp}
      onDocClick={onDocClick}
      failedText={message.failedText}
      onRetry={onRetry}
      activities={message.activities}
    />
  );
}

export default memo(MessageItem);
