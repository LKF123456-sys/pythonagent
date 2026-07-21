// 聊天主页面：侧边栏 + 消息流 + 节点流水线 + 输入区
import { useEffect, useMemo, useRef } from "react";
import { useChatStore } from "../store/chat";
import { useAuthStore } from "../store/auth";
import { Sidebar } from "../components/Sidebar";
import { MessageBubble } from "../components/MessageBubble";
import { NodePipeline } from "../components/NodePipeline";
import { ChatInput } from "../components/ChatInput";
import type { WSStatus } from "../lib/ws";

const WS_STATUS_TEXT: Record<WSStatus, string> = {
  connecting: "连接中",
  open: "实时通道",
  closed: "未连接",
  reconnecting: "重连中",
};

const SUGGESTIONS = [
  "帮我搜索一下 LangGraph 的最新进展",
  "用 RAG 检索知识库里关于部署的说明",
  "解释一下什么是多智能体系统，并举个例子",
  "计算 (128 * 256) / 3 的结果",
];

export default function Chat() {
  const user = useAuthStore((s) => s.user);
  const conversations = useChatStore((s) => s.conversations);
  const currentSessionId = useChatStore((s) => s.currentSessionId);
  const messages = useChatStore((s) => s.messages);
  const messagesLoading = useChatStore((s) => s.messagesLoading);
  const streaming = useChatStore((s) => s.streaming);
  const stream = useChatStore((s) => s.stream);
  const pipeline = useChatStore((s) => s.pipeline);
  const wsStatus = useChatStore((s) => s.wsStatus);
  const loadConversations = useChatStore((s) => s.loadConversations);
  const sendMessage = useChatStore((s) => s.sendMessage);

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  // 消息/流式内容变化时自动滚动到底部
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, stream?.answer, stream?.thinking, messagesLoading]);

  const currentTitle = useMemo(() => {
    const conv = conversations.find((c) => c.session_id === currentSessionId);
    return conv?.title || "新的对话";
  }, [conversations, currentSessionId]);

  const regenerate = () => {
    // 找到最后一条用户消息重新发送
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        sendMessage(messages[i].content);
        return;
      }
    }
  };

  const wsDotClass =
    wsStatus === "open" ? "dot-green" : wsStatus === "connecting" || wsStatus === "reconnecting" ? "dot-amber" : "dot-muted";

  return (
    <div className="chat-layout">
      <Sidebar />

      <main className="chat-main">
        <div className="chat-header">
          <div className="chat-header-title">{currentTitle}</div>
          <div className="ws-indicator">
            <span className={`dot ${wsDotClass}`} />
            {WS_STATUS_TEXT[wsStatus]}
          </div>
        </div>

        <NodePipeline stages={pipeline} visible={streaming || pipeline.length > 0} />

        <div className="messages" ref={scrollRef}>
          {messages.length === 0 && !streaming && !messagesLoading ? (
            <div className="empty-state">
              <div className="empty-glyph">N·</div>
              <div className="empty-title">向 Nexus 编队提问</div>
              <div className="empty-sub">Supervisor 会自动路由到搜索、知识库或直接回答</div>
              <div className="empty-chips">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="empty-chip" onClick={() => sendMessage(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messagesLoading && (
                <div style={{ display: "grid", placeItems: "center", padding: 40 }}>
                  <span className="spinner" />
                </div>
              )}
              {messages.map((m, i) => (
                <MessageBubble
                  key={i}
                  message={m}
                  username={user?.username}
                  isLast={i === messages.length - 1}
                  onRegenerate={regenerate}
                />
              ))}
              {streaming && stream && (
                <MessageBubble
                  message={{ role: "assistant", content: stream.answer }}
                  streaming
                  thinking={stream.thinking}
                  username={user?.username}
                />
              )}
            </>
          )}
        </div>

        <ChatInput />
      </main>
    </div>
  );
}
