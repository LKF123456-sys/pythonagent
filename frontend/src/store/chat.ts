// 聊天状态管理（Zustand）+ WebSocket 编排
// 职责：会话列表、消息加载、流式回答（thinking/token）、节点流水线、中断生成
import { create } from "zustand";
import * as api from "../lib/api";
import { ChatSocket, type WSStatus } from "../lib/ws";
import type { Conversation, Message, PipelineNode, WSServerMessage } from "../types";

/** 流水线节点中文标签 */
export const NODE_LABELS: Record<PipelineNode, string> = {
  preprocess: "预处理",
  supervisor: "路由决策",
  search: "联网搜索",
  rag: "知识检索",
  answer: "生成回答",
  store_memory: "写入记忆",
};

export interface PipelineStage {
  node: PipelineNode;
  state: "active" | "done";
}

interface StreamState {
  thinking: string;
  answer: string;
}

interface ChatState {
  conversations: Conversation[];
  currentSessionId: string | null;
  messages: Message[];
  messagesLoading: boolean;

  streaming: boolean;
  stream: StreamState | null;
  pipeline: PipelineStage[];
  lastRoute: string | null;
  lastTokenCount: number | null;
  wsStatus: WSStatus;

  loadConversations: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  newChat: () => void;
  sendMessage: (question: string, imageFilename?: string) => void;
  abort: () => void;
  renameConversation: (sessionId: string, title: string) => Promise<void>;
  removeConversation: (sessionId: string) => Promise<void>;
  dispose: () => void;
}

// —— 模块级 WebSocket 单例（不进入 React 状态） ——
let socket: ChatSocket | null = null;

function genSessionId(): string {
  // 与后端 uuid4().hex 格式一致：32 位十六进制
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export const useChatStore = create<ChatState>((set, get) => {
  /** 处理服务端 WS 消息，驱动流式状态 */
  function handleServerMessage(msg: WSServerMessage): void {
    switch (msg.type) {
      case "status": {
        const node = msg.node as PipelineNode;
        if (!(node in NODE_LABELS)) return;
        set((s) => {
          // 已存在则不重复推入；新节点置为 active，之前的节点全部 done
          if (s.pipeline.some((p) => p.node === node)) return s;
          const pipeline: PipelineStage[] = s.pipeline.map((p) => ({ ...p, state: "done" as const }));
          pipeline.push({ node, state: "active" });
          return { pipeline };
        });
        break;
      }
      case "thinking":
        set((s) => ({
          stream: { thinking: (s.stream?.thinking ?? "") + msg.content, answer: s.stream?.answer ?? "" },
        }));
        break;
      case "token":
        set((s) => ({
          stream: { thinking: s.stream?.thinking ?? "", answer: (s.stream?.answer ?? "") + msg.content },
        }));
        break;
      case "done": {
        const { currentSessionId } = get();
        set((s) => {
          const messages = [...s.messages];
          const answerText = msg.aborted ? s.stream?.answer ?? "" : msg.answer;
          if (answerText) {
            messages.push({
              role: "assistant",
              content: answerText + (msg.aborted ? "\n\n*（已停止生成）*" : ""),
              token_count: msg.token_count,
            });
          }
          return {
            messages,
            streaming: false,
            stream: null,
            pipeline: s.pipeline.map((p) => ({ ...p, state: "done" as const })),
            lastRoute: msg.route ?? s.lastRoute,
            lastTokenCount: msg.token_count ?? null,
          };
        });
        // 首轮结束后后端会异步生成标题，刷新会话列表以同步
        if (currentSessionId) void get().loadConversations();
        break;
      }
      case "error":
        set((s) => ({
          streaming: false,
          stream: null,
          messages: [
            ...s.messages,
            { role: "assistant", content: `⚠️ 出错了：${msg.message}` },
          ],
        }));
        break;
      case "pong":
        break;
    }
  }

  /** 确保指定 session 的 WS 已连接 */
  function ensureSocket(sessionId: string): ChatSocket {
    if (socket) {
      socket.switchSession(sessionId);
      return socket;
    }
    socket = new ChatSocket({
      sessionId,
      onMessage: handleServerMessage,
      onStatus: (status) => set({ wsStatus: status }),
    });
    socket.connect();
    return socket;
  }

  return {
    conversations: [],
    currentSessionId: null,
    messages: [],
    messagesLoading: false,

    streaming: false,
    stream: null,
    pipeline: [],
    lastRoute: null,
    lastTokenCount: null,
    wsStatus: "closed",

    loadConversations: async () => {
      try {
        const conversations = await api.listConversations();
        set({ conversations });
      } catch {
        // 列表加载失败保持现状
      }
    },

    selectSession: async (sessionId) => {
      if (get().currentSessionId === sessionId) return;
      set({
        currentSessionId: sessionId,
        messages: [],
        messagesLoading: true,
        stream: null,
        streaming: false,
        pipeline: [],
      });
      try {
        const messages = await api.getMessages(sessionId);
        // 防止快速切换导致的竞态
        if (get().currentSessionId === sessionId) {
          set({ messages, messagesLoading: false });
        }
      } catch {
        if (get().currentSessionId === sessionId) set({ messagesLoading: false });
      }
      ensureSocket(sessionId);
    },

    newChat: () => {
      set({
        currentSessionId: null,
        messages: [],
        stream: null,
        streaming: false,
        pipeline: [],
        lastRoute: null,
        lastTokenCount: null,
      });
    },

    sendMessage: (question, imageFilename) => {
      const state = get();
      if (state.streaming || !question.trim()) return;

      // 新会话：前端预生成 session_id 并建立 WS
      let sessionId = state.currentSessionId;
      if (!sessionId) {
        sessionId = genSessionId();
        set({ currentSessionId: sessionId });
      }
      ensureSocket(sessionId);

      set((s) => ({
        messages: [...s.messages, { role: "user", content: question, image_filename: imageFilename || undefined }],
        streaming: true,
        stream: { thinking: "", answer: "" },
        pipeline: [],
      }));

      socket!.send({ type: "chat", question, image_filename: imageFilename || "" });
    },

    abort: () => {
      socket?.send({ type: "abort" });
    },

    renameConversation: async (sessionId, title) => {
      await api.renameConversation(sessionId, title);
      set((s) => ({
        conversations: s.conversations.map((c) => (c.session_id === sessionId ? { ...c, title } : c)),
      }));
    },

    removeConversation: async (sessionId) => {
      await api.deleteConversation(sessionId);
      set((s) => {
        const conversations = s.conversations.filter((c) => c.session_id !== sessionId);
        const patch: Partial<ChatState> = { conversations };
        if (s.currentSessionId === sessionId) {
          patch.currentSessionId = null;
          patch.messages = [];
          patch.stream = null;
          patch.streaming = false;
          patch.pipeline = [];
        }
        return patch as ChatState;
      });
    },

    dispose: () => {
      socket?.close();
      socket = null;
    },
  };
});
