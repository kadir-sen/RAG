import { memo } from 'react';
import type { Message } from '../../types/chat';
import type { ViewerDoc } from '../../stores/uiStore';
import UserMessage from './UserMessage';
import AssistantMessage from './AssistantMessage';

interface Props {
  message: Message;
  /** The user message this answer replies to — carried into the Word export. */
  question?: string;
  onDocClick: (doc: ViewerDoc) => void;
  onRetry?: (text: string) => void;
}

function MessageItem({ message, question, onDocClick, onRetry }: Props) {
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
      question={question ?? ''}
    />
  );
}

export default memo(MessageItem);
