// API 客户端：封装 axios 请求 + JWT token 注入 + SSE 流式聊天
import axios from "axios";
import type {
  AuthResponse,
  Conversation,
  Message,
  DocumentInfo,
  StreamEvent,
  UserInfo,
} from "../types";

const TOKEN_KEY = "agent_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

// axios 实例：baseURL 使用相对路径，交由 Vite 代理 / Nginx 转发
const http = axios.create({ baseURL: "" });

// 请求拦截器：自动附加 Authorization header
http.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 响应拦截器：401 时清除 token 并跳转登录
http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    if (error.response?.status === 401) {
      clearToken();
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

// ============================================================
// 认证
// ============================================================

export async function register(username: string, password: string): Promise<AuthResponse> {
  const { data } = await http.post<AuthResponse>("/api/auth/register", { username, password });
  return data;
}

export async function login(username: string, password: string): Promise<AuthResponse> {
  const { data } = await http.post<AuthResponse>("/api/auth/login", { username, password });
  return data;
}

export async function fetchMe(): Promise<UserInfo> {
  const { data } = await http.get<UserInfo>("/api/auth/me");
  return data;
}

// ============================================================
// 会话
// ============================================================

export async function newSession(): Promise<string> {
  const { data } = await http.post<{ session_id: string }>("/api/session/new");
  return data.session_id;
}

export async function listConversations(): Promise<Conversation[]> {
  const { data } = await http.get<{ conversations: Conversation[] }>("/api/conversations");
  return data.conversations;
}

export async function getMessages(convId: string): Promise<Message[]> {
  const { data } = await http.get<{ messages: Message[] }>(
    `/api/conversations/${convId}/messages`
  );
  return data.messages;
}

export async function deleteConversation(convId: string): Promise<void> {
  await http.delete(`/api/conversations/${convId}`);
}

// ============================================================
// 上传
// ============================================================

export async function uploadImage(file: File): Promise<string> {
  const form = new FormData();
  form.append("image", file);
  const { data } = await http.post<{ filename: string }>("/api/upload/image", form);
  return data.filename;
}

export async function uploadDocument(file: File): Promise<{ filename: string; chunks: number }> {
  const form = new FormData();
  form.append("document", file);
  const { data } = await http.post<{ filename: string; chunks: number }>(
    "/api/upload/document",
    form
  );
  return data;
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const { data } = await http.get<{ documents: DocumentInfo[] }>("/api/documents");
  return data.documents;
}

export async function deleteDocument(filename: string): Promise<void> {
  await http.delete(`/api/documents/${encodeURIComponent(filename)}`);
}

// ============================================================
// 流式聊天（SSE，通过 fetch + ReadableStream 以便携带 JWT header）
// ============================================================

export interface ChatStreamParams {
  question: string;
  sessionId: string;
  imageFilename?: string;
  isFirstTurn: boolean;
}

/**
 * 发起流式聊天，通过回调逐事件推送。
 * EventSource 无法携带自定义 header，故使用 fetch 手动解析 SSE。
 */
export async function chatStream(
  params: ChatStreamParams,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const token = getToken();
  const resp = await fetch("/api/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      question: params.question,
      session_id: params.sessionId,
      image_filename: params.imageFilename || "",
      is_first_turn: params.isFirstTurn,
    }),
    signal,
  });

  if (!resp.ok || !resp.body) {
    const detail = await resp.text().catch(() => "");
    throw new Error(`流式请求失败 (${resp.status}): ${detail}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE 事件以 \n\n 分隔
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const line = raw.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const payload = line.replace(/^data:\s?/, "").trim();
      if (!payload) continue;
      try {
        onEvent(JSON.parse(payload) as StreamEvent);
      } catch {
        // 忽略无法解析的分片
      }
    }
  }
}
