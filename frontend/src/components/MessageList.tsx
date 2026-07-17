import ReactMarkdown from "react-markdown";
import { useEffect, useRef } from "react";
import type { Message } from "../types";

interface Props {
  messages: Message[];
  streaming: string;
  statusNode: string;
  isStreaming: boolean;
}

// 消息列表：渲染历史消息 + 正在流式生成的内容
export default function MessageList({ messages, streaming, statusNode, isStreaming }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming, statusNode]);

  const nodeLabel: Record<string, string> = {
    supervisor: "调度中…",
    search_agent: "联网搜索中…",
    rag_agent: "检索知识库中…",
    vision_agent: "识别图片中…",
    chat_agent: "思考中…",
    store_memory: "记忆存储中…",
  };

  if (messages.length === 0 && !isStreaming) {
    return <div className="empty-hint">开始新的对话吧 👋</div>;
  }

  return (
    <div className="messages">
      {messages.map((m, i) => (
        <div key={i} className={`msg-row ${m.role}`}>
          <div className="msg-avatar">{m.role === "user" ? "🧑" : "🤖"}</div>
          <div className="msg-bubble">
            {m.role === "assistant" ? (
              <ReactMarkdown>{m.content}</ReactMarkdown>
            ) : (
              m.content
            )}
          </div>
        </div>
      ))}

      {isStreaming && statusNode && (
        <div className="status-line">{nodeLabel[statusNode] || statusNode}</div>
      )}

      {isStreaming && streaming && (
        <div className="msg-row assistant">
          <div className="msg-avatar">🤖</div>
          <div className="msg-bubble">
            <ReactMarkdown>{streaming}</ReactMarkdown>
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
