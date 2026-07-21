// 与后端 API 对应的 TypeScript 类型定义（v2.0 新架构）

// ============================================================
// 认证
// ============================================================

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user_id: number;
  username: string;
  is_admin: boolean;
}

export interface UserInfo {
  user_id: number;
  username: string;
  is_admin: boolean;
  created_at: string;
}

// ============================================================
// 会话与消息
// ============================================================

export interface Conversation {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  role: "user" | "assistant";
  content: string;
  token_count?: number;
  image_filename?: string;
  created_at?: string;
}

export interface TokenStatItem {
  date: string;
  total_tokens: number;
  message_count: number;
}

export interface TokenStats {
  total_tokens: number;
  daily: TokenStatItem[];
}

// ============================================================
// 文档（RAG 知识库）
// ============================================================

export interface DocumentInfo {
  filename: string;
  chunks: number;
  timestamp?: string;
}

// ============================================================
// 管理后台
// ============================================================

export interface AdminUser {
  id: number;
  username: string;
  created_at: string;
  is_active: boolean;
  is_admin: boolean;
}

export interface SystemStats {
  user_count: number;
  conversation_count: number;
  message_count: number;
  total_tokens: number;
}

export interface HealthComponent {
  status: "ok" | "degraded" | "error";
  detail?: string;
  models?: string[];
}

export interface HealthReport {
  status: "healthy" | "degraded" | "unhealthy";
  components: Record<string, HealthComponent>;
}

// ============================================================
// WebSocket 协议
// ============================================================

/** 客户端 → 服务端 */
export type WSClientMessage =
  | { type: "chat"; question: string; image_filename?: string }
  | { type: "abort" }
  | { type: "ping" };

/** 服务端 → 客户端 */
export type WSServerMessage =
  | { type: "status"; node: string; message: string; session_id: string }
  | { type: "thinking"; content: string }
  | { type: "token"; content: string }
  | {
      type: "done";
      answer: string;
      session_id: string;
      route?: string;
      token_count?: number;
      aborted?: boolean;
    }
  | { type: "error"; message: string }
  | { type: "pong" };

/** 节点流水线阶段（用于状态动画） */
export type PipelineNode =
  | "preprocess"
  | "supervisor"
  | "search"
  | "rag"
  | "answer"
  | "store_memory";
