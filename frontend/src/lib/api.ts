// API 客户端：axios + JWT 双 Token 自动刷新 + 统一端点封装
import axios, { AxiosError, type AxiosRequestConfig } from "axios";
import type {
  AuthResponse,
  Conversation,
  DocumentInfo,
  HealthReport,
  Message,
  SystemStats,
  AdminUser,
  TokenStats,
  UserInfo,
} from "../types";

const ACCESS_KEY = "agent_access_token";
const REFRESH_KEY = "agent_refresh_token";

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}
export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}
export function setTokens(access: string, refresh: string): void {
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}
export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

const http = axios.create({ baseURL: "" });

// 请求拦截器：附加 Authorization
http.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// 是否正在刷新（避免并发重复刷新）
let refreshing: Promise<string> | null = null;

async function doRefresh(): Promise<string> {
  const refresh = getRefreshToken();
  if (!refresh) throw new Error("无刷新令牌");
  const { data } = await axios.post<AuthResponse>("/api/auth/refresh", {
    refresh_token: refresh,
  });
  setTokens(data.access_token, data.refresh_token);
  return data.access_token;
}

// 响应拦截器：401 时尝试刷新并重试一次
http.interceptors.response.use(
  (resp) => resp,
  async (error: AxiosError) => {
    const original = error.config as AxiosRequestConfig & { _retried?: boolean };
    if (error.response?.status === 401 && original && !original._retried) {
      original._retried = true;
      try {
        refreshing = refreshing ?? doRefresh();
        const newToken = await refreshing;
        refreshing = null;
        original.headers = { ...original.headers, Authorization: `Bearer ${newToken}` };
        return http(original);
      } catch {
        refreshing = null;
        clearTokens();
        if (window.location.pathname !== "/login") {
          window.location.href = "/login";
        }
      }
    }
    return Promise.reject(error);
  }
);

// 提取后端错误详情
export function errDetail(e: unknown, fallback = "请求失败"): string {
  if (axios.isAxiosError(e)) {
    const d = e.response?.data as { detail?: string } | undefined;
    return d?.detail || e.message || fallback;
  }
  return e instanceof Error ? e.message : fallback;
}

// ============================================================
// 认证
// ============================================================

export const register = (username: string, password: string) =>
  http.post<AuthResponse>("/api/auth/register", { username, password }).then((r) => r.data);

export const login = (username: string, password: string) =>
  http.post<AuthResponse>("/api/auth/login", { username, password }).then((r) => r.data);

export const logout = (refresh_token?: string) =>
  http.post("/api/auth/logout", refresh_token ? { refresh_token } : {});

export const fetchMe = () => http.get<UserInfo>("/api/auth/me").then((r) => r.data);

// ============================================================
// 会话
// ============================================================

export const listConversations = (convType: "general" | "mfg" = "general") =>
  http.get<{ conversations: Conversation[] }>("/api/conversations", { params: { conv_type: convType } }).then((r) => r.data.conversations);

export const getMessages = (id: string) =>
  http.get<{ messages: Message[] }>(`/api/conversations/${id}/messages`).then((r) => r.data.messages);

export const renameConversation = (id: string, title: string) =>
  http.patch(`/api/conversations/${id}`, { title });

export const deleteConversation = (id: string) => http.delete(`/api/conversations/${id}`);

export const exportConversation = (id: string, format: "markdown" | "json") =>
  http
    .get(`/api/conversations/${id}/export`, { params: { format }, responseType: "blob" })
    .then((r) => r.data as Blob);

export const getTokenStats = (days = 30) =>
  http.get<TokenStats>("/api/stats/tokens", { params: { days } }).then((r) => r.data);

// ============================================================
// 聊天（非流式 + 上传）
// ============================================================

export const chatOnce = (question: string, session_id?: string, image_filename?: string) =>
  http
    .post<{ answer: string; session_id: string; token_count: number; error?: string }>("/api/chat", {
      question,
      session_id,
      image_filename,
    })
    .then((r) => r.data);

export const uploadImage = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return http.post<{ filename: string }>("/api/chat/upload-image", form).then((r) => r.data.filename);
};

// ============================================================
// 文档（RAG）
// ============================================================

export const uploadDocument = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return http
    .post<{ filename: string; chunks: number }>("/api/documents/upload", form)
    .then((r) => r.data);
};

export const listDocuments = () =>
  http.get<{ documents: DocumentInfo[] }>("/api/documents").then((r) => r.data.documents);

export const deleteDocument = (filename: string) =>
  http.delete(`/api/documents/${encodeURIComponent(filename)}`);

// ============================================================
// 管理后台
// ============================================================

export const listUsers = () =>
  http.get<{ users: AdminUser[] }>("/api/admin/users").then((r) => r.data.users);

export const setUserActive = (userId: number, is_active: boolean) =>
  http.patch(`/api/admin/users/${userId}`, { is_active });

export const getSystemStats = () => http.get<SystemStats>("/api/admin/stats").then((r) => r.data);

export const getHealth = () => http.get<HealthReport>("/api/health").then((r) => r.data);
