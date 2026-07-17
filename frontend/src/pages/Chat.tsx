import { useEffect, useState, useCallback, useRef } from "react";
import Sidebar from "../components/Sidebar";
import MessageList from "../components/MessageList";
import ChatInput from "../components/ChatInput";
import * as api from "../api/client";
import type { Conversation, Message } from "../types";

// 生成 8 位随机会话 id（与后端 uuid[:8] 风格一致）
function genSessionId(): string {
  return Math.random().toString(36).slice(2, 10);
}

// 主聊天页面
export default function Chat() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string>(genSessionId());
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState("");
  const [statusNode, setStatusNode] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const isFirstTurnRef = useRef(true);

  // 加载历史会话列表
  const refreshConversations = useCallback(async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch {
      /* 忽略 */
    }
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  // 选择一个历史会话，加载其消息
  async function handleSelect(id: string) {
    if (id === activeId) return;
    setActiveId(id);
    setStreaming("");
    setStatusNode("");
    try {
      const msgs = await api.getMessages(id);
      setMessages(msgs);
      isFirstTurnRef.current = msgs.length === 0;
    } catch {
      setMessages([]);
    }
  }

  // 新建对话
  function handleNew() {
    setActiveId(genSessionId());
    setMessages([]);
    setStreaming("");
    setStatusNode("");
    isFirstTurnRef.current = true;
  }

  // 删除对话
  async function handleDelete(id: string) {
    if (!confirm("确定删除该对话？")) return;
    await api.deleteConversation(id);
    if (id === activeId) handleNew();
    await refreshConversations();
  }

  // 发送消息（流式）
  async function handleSend(question: string, imageFilename: string) {
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setStreaming("");
    setStatusNode("");
    setIsStreaming(true);

    let acc = "";
    try {
      await api.chatStream(
        {
          question,
          sessionId: activeId,
          imageFilename,
          isFirstTurn: isFirstTurnRef.current,
        },
        (event) => {
          if (event.type === "status") {
            setStatusNode(event.node);
          } else if (event.type === "token") {
            acc += event.content;
            setStreaming(acc);
          } else if (event.type === "error") {
            acc += `\n\n⚠️ 出错：${event.error}`;
            setStreaming(acc);
          }
        }
      );
    } catch (err: any) {
      acc += `\n\n⚠️ 请求失败：${err?.message || err}`;
    } finally {
      setMessages((prev) => [...prev, { role: "assistant", content: acc }]);
      setStreaming("");
      setStatusNode("");
      setIsStreaming(false);
      isFirstTurnRef.current = false;
      // 首轮结束后刷新会话列表（后端已落库）
      refreshConversations();
    }
  }

  function handleDocUploaded(filename: string, chunks: number) {
    setMessages((prev) => [
      ...prev,
      { role: "assistant", content: `📄 已将文档 **${filename}** 加入知识库（${chunks} 个切片），现在可以就其内容提问。` },
    ]);
  }

  return (
    <div className="app-layout">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={handleSelect}
        onNew={handleNew}
        onDelete={handleDelete}
      />
      <div className="chat-main">
        <MessageList
          messages={messages}
          streaming={streaming}
          statusNode={statusNode}
          isStreaming={isStreaming}
        />
        <ChatInput disabled={isStreaming} onSend={handleSend} onDocUploaded={handleDocUploaded} />
      </div>
    </div>
  );
}
