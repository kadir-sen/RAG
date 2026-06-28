import type { ChatResponse, ActivityStep } from './api';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  response?: ChatResponse;
  failedText?: string;
  // Live activity steps captured while this answer was produced (agent/hybrid).
  activities?: ActivityStep[];
}

export interface Conversation {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
}
