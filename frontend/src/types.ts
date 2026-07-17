// 与后端 API 对应的 TypeScript 类型定义

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user_id: number;
  username: string;
}

export interface UserInfo {
  user_id: number;
  username: string;
  created_at: string;
}

export interface Conversation {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  role: "user" | "assistant";
  content: string;
  created_at?: string;
}

export interface DocumentInfo {
  filename: string;
  chunks?: number;
  [key: string]: unknown;
}

// SSE 流事件类型
export type StreamEvent =
  | { type: "status"; node: string }
  | { type: "token"; content: string }
  | { type: "done" }
  | { type: "error"; error: string };
