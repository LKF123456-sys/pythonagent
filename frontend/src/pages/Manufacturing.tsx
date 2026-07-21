// 工业智能制造垂直多智能体页面（增强版：图片上传 + 文档RAG + Token用量 + 历史会话）
import { useCallback, useEffect, useRef, useState } from "react";
import { MfgSocket, type MfgWSStatus } from "../lib/mfg-ws";
import { MessageBubble } from "../components/MessageBubble";
import { Markdown } from "../components/Markdown";
import { useAuthStore } from "../store/auth";
import type { Conversation, Message, WSServerMessage } from "../types";
import { IconSend, IconStop, IconImage, IconX, IconFile, IconTrash, IconPlus } from "../components/icons";
import { getAccessToken, errDetail, listConversations, getMessages } from "../lib/api";
import { toast } from "../lib/toast";
import axios from "axios";

// 工业节点展示名
const MFG_NODE_LABELS: Record<string, string> = {
  mfg_preprocess: "加载领域知识",
  mfg_supervisor: "工业任务路由",
  fault_diagnosis: "故障诊断分析",
  process_optimization: "工艺参数分析",
  predictive_maintenance: "设备健康评估",
  knowledge_qa: "工业知识检索",
  mfg_answer: "生成专业回答",
  mfg_store_memory: "写入工业记忆",
};

const WS_STATUS_TEXT: Record<MfgWSStatus, string> = {
  connecting: "连接中",
  open: "实时通道",
  closed: "未连接",
  reconnecting: "重连中",
};

// 快捷入口
const QUICK_ACTIONS = [
  { label: "故障码查询", icon: "🔧", question: "查询故障码 E001 的原因和维修方案" },
  { label: "设备健康检查", icon: "📊", question: "对工业机器人进行设备健康评估，已运行 3000 小时" },
  { label: "工艺参数分析", icon: "⚙️", question: "注塑成型出现缩痕缺陷，请分析工艺参数并给出优化建议" },
  { label: "维护计划", icon: "📋", question: "空压机已运行 4500 小时，请推荐维护计划" },
  { label: "传感器数据", icon: "📡", question: "模拟数控机床的传感器实时数据并分析状态" },
  { label: "安全知识", icon: "🛡️", question: "设备检修时的 LOTO（上锁挂牌）安全规程是什么？" },
];

const ACCEPT_DOC_EXT = [".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".json", ".html", ".py"];

interface StreamState {
  thinking: string;
  answer: string;
}

interface MfgDoc {
  filename: string;
  chunks: number;
  timestamp?: string;
}

function genSessionId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

// 带 JWT 的 HTTP 实例
function mfgHttp() {
  const token = getAccessToken();
  return axios.create({
    baseURL: "",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
}

export default function Manufacturing() {
  const user = useAuthStore((s) => s.user);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [stream, setStream] = useState<StreamState | null>(null);
  const [pipeline, setPipeline] = useState<string[]>([]);
  const [wsStatus, setWsStatus] = useState<MfgWSStatus>("closed");
  const [totalTokens, setTotalTokens] = useState(0);

  // 历史会话
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messagesLoading, setMessagesLoading] = useState(false);

  // 图片上传状态
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState("");
  const [imageServerName, setImageServerName] = useState("");
  const [imageUploading, setImageUploading] = useState(false);

  // 文档面板
  const [showDocPanel, setShowDocPanel] = useState(false);
  const [docs, setDocs] = useState<MfgDoc[]>([]);
  const [docUploading, setDocUploading] = useState<string | null>(null);

  const socketRef = useRef<MfgSocket | null>(null);
  const sessionIdRef = useRef<string>(genSessionId());
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const imgInputRef = useRef<HTMLInputElement>(null);
  const docInputRef = useRef<HTMLInputElement>(null);

  // 加载工业会话列表
  const loadMfgConversations = useCallback(async () => {
    try {
      const convs = await listConversations("mfg");
      setConversations(convs);
    } catch {
      // 静默失败
    }
  }, []);

  // 处理服务端消息
  const handleServerMessage = useCallback((msg: WSServerMessage) => {
    switch (msg.type) {
      case "status":
        setPipeline((prev) => {
          if (prev.includes(msg.node)) return prev;
          return [...prev, msg.node];
        });
        break;
      case "thinking":
        setStream((s) => ({ thinking: (s?.thinking ?? "") + msg.content, answer: s?.answer ?? "" }));
        break;
      case "token":
        setStream((s) => ({ thinking: s?.thinking ?? "", answer: (s?.answer ?? "") + msg.content }));
        break;
      case "done": {
        const answerText = msg.aborted ? "" : msg.answer;
        const tokens = msg.token_count ?? 0;
        if (tokens > 0) setTotalTokens((prev) => prev + tokens);
        setMessages((prev) => {
          if (answerText) return [...prev, { role: "assistant", content: answerText, token_count: tokens }];
          return prev;
        });
        setStreaming(false);
        setStream(null);
        // 刷新会话列表（首轮结束后后端会创建会话记录）
        void loadMfgConversations();
        break;
      }
      case "error":
        setMessages((prev) => [...prev, { role: "assistant", content: `⚠️ 出错了：${msg.message}` }]);
        setStreaming(false);
        setStream(null);
        break;
      case "pong":
        break;
    }
  }, [loadMfgConversations]);

  // 初始化时加载会话列表
  useEffect(() => {
    void loadMfgConversations();
  }, [loadMfgConversations]);

  // 选择历史会话
  const selectSession = async (sessionId: string) => {
    if (currentSessionId === sessionId) return;
    setCurrentSessionId(sessionId);
    sessionIdRef.current = sessionId;
    setMessages([]);
    setMessagesLoading(true);
    setStream(null);
    setStreaming(false);
    setPipeline([]);
    try {
      const msgs = await getMessages(sessionId);
      setMessages(msgs);
    } catch {
      // 静默失败
    } finally {
      setMessagesLoading(false);
    }
    // 切换 WS 会话
    socketRef.current?.switchSession(sessionId);
  };

  // 新建对话
  const newChat = () => {
    const newId = genSessionId();
    sessionIdRef.current = newId;
    setCurrentSessionId(null);
    setMessages([]);
    setStream(null);
    setStreaming(false);
    setPipeline([]);
    setTotalTokens(0);
    socketRef.current?.switchSession(newId);
  };

  // 初始化 WebSocket
  useEffect(() => {
    const socket = new MfgSocket({
      sessionId: sessionIdRef.current,
      onMessage: handleServerMessage,
      onStatus: setWsStatus,
    });
    socket.connect();
    socketRef.current = socket;
    return () => {
      socket.close();
      socketRef.current = null;
    };
  }, [handleServerMessage]);

  // 自动滚动
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, stream?.answer, stream?.thinking]);

  // textarea 自适应高度
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  }, [input]);

  // 加载文档列表
  const refreshDocs = useCallback(async () => {
    try {
      const { data } = await mfgHttp().get("/api/manufacturing/documents");
      setDocs(data.documents ?? []);
    } catch {
      // 静默失败
    }
  }, []);

  useEffect(() => {
    if (showDocPanel) void refreshDocs();
  }, [showDocPanel, refreshDocs]);

  // 图片上传
  const pickImage = async (file: File) => {
    if (!file.type.startsWith("image/")) {
      toast("仅支持图片文件", "error");
      return;
    }
    setImageFile(file);
    setImagePreview(URL.createObjectURL(file));
    setImageUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await mfgHttp().post("/api/manufacturing/upload-image", form);
      setImageServerName(data.filename);
      setImageUploading(false);
    } catch (e) {
      setImageUploading(false);
      setImageFile(null);
      setImagePreview("");
      toast(`图片上传失败：${errDetail(e)}`, "error");
    }
  };

  const clearImage = () => {
    if (imagePreview) URL.revokeObjectURL(imagePreview);
    setImageFile(null);
    setImagePreview("");
    setImageServerName("");
  };

  // 文档上传
  const uploadDoc = async (file: File) => {
    setDocUploading(file.name);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await mfgHttp().post("/api/manufacturing/documents/upload", form);
      toast(`「${data.filename}」已入库，切分为 ${data.chunks} 个片段`, "success");
      await refreshDocs();
    } catch (e) {
      toast(`文档上传失败：${errDetail(e)}`, "error");
    } finally {
      setDocUploading(null);
    }
  };

  const deleteDoc = async (filename: string) => {
    try {
      await mfgHttp().delete(`/api/manufacturing/documents/${encodeURIComponent(filename)}`);
      toast(`已删除「${filename}」`, "success");
      await refreshDocs();
    } catch (e) {
      toast(`删除失败：${errDetail(e)}`, "error");
    }
  };

  // 发送消息
  const sendMessage = (question: string) => {
    if (streaming || !question.trim()) return;
    if (imageFile && (!imageServerName || imageUploading)) {
      toast("图片仍在上传，请稍候", "info");
      return;
    }
    // 新会话时设置 sessionId
    if (!currentSessionId) {
      setCurrentSessionId(sessionIdRef.current);
    }
    setMessages((prev) => [...prev, { role: "user", content: question, image_filename: imageServerName || undefined }]);
    setStreaming(true);
    setStream({ thinking: "", answer: "" });
    setPipeline([]);
    socketRef.current?.send({
      type: "chat",
      question,
      image_filename: imageServerName || undefined,
    });
    clearImage();
  };

  const abort = () => {
    socketRef.current?.send({ type: "abort" });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendMessage(input);
    setInput("");
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSubmit(e as unknown as React.FormEvent);
    }
  };

  const wsDotClass =
    wsStatus === "open" ? "dot-green" : wsStatus === "connecting" || wsStatus === "reconnecting" ? "dot-amber" : "dot-muted";

  return (
    <div className="mfg-layout">
      {/* 历史会话侧边栏 */}
      <aside className="mfg-sidebar">
        <div className="mfg-sidebar-head">
          <span className="mfg-sidebar-title">工业会话</span>
          <button className="btn-icon" title="新建对话" onClick={newChat}>
            <IconPlus style={{ width: 15, height: 15 }} />
          </button>
        </div>
        <div className="mfg-sidebar-list">
          {conversations.length === 0 && (
            <div className="mfg-sidebar-empty">还没有对话，开始第一段吧</div>
          )}
          {conversations.map((c) => (
            <button
              key={c.session_id}
              className={`mfg-conv-item ${c.session_id === currentSessionId ? "active" : ""}`}
              onClick={() => void selectSession(c.session_id)}
            >
              <span className="mfg-conv-title">{c.title || "未命名对话"}</span>
            </button>
          ))}
        </div>
      </aside>

      <main className="mfg-main">
        {/* 头部 */}
        <div className="mfg-header">
          <div className="mfg-header-left">
            <span className="mfg-badge">工业智造</span>
            <span className="mfg-title">智能制造多智能体助手</span>
          </div>
          <div className="mfg-header-right">
            <span className="mfg-token-badge" title="本次会话累计 Token 用量">
              🪙 {totalTokens.toLocaleString()} tokens
            </span>
            <button
              className={`mfg-doc-toggle ${showDocPanel ? "active" : ""}`}
              onClick={() => setShowDocPanel(!showDocPanel)}
              title="工业知识库（RAG 文档管理）"
            >
              <IconFile style={{ width: 15, height: 15 }} />
              <span>知识库</span>
            </button>
            <div className="ws-indicator">
              <span className={`dot ${wsDotClass}`} />
              {WS_STATUS_TEXT[wsStatus]}
            </div>
          </div>
        </div>

        {/* 节点流水线 */}
        {pipeline.length > 0 && (
          <div className="mfg-pipeline">
            {pipeline.map((node, i) => (
              <span key={node} className={`mfg-pipeline-node ${i === pipeline.length - 1 && streaming ? "active" : "done"}`}>
                {MFG_NODE_LABELS[node] || node}
              </span>
            ))}
          </div>
        )}

        <div className="mfg-body">
          {/* 消息区 */}
          <div className="messages" ref={scrollRef}>
            {messagesLoading ? (
              <div style={{ display: "grid", placeItems: "center", padding: 40 }}>
                <span className="spinner" />
              </div>
            ) : messages.length === 0 && !streaming ? (
              <div className="mfg-empty">
                <div className="mfg-empty-icon">🏭</div>
                <div className="mfg-empty-title">工业智能制造多智能体系统</div>
                <div className="mfg-empty-sub">
                  覆盖设备故障诊断 · 生产工艺优化 · 预测性维护 · 工业知识问答 · 图片识别
                </div>
                <div className="mfg-quick-grid">
                  {QUICK_ACTIONS.map((action) => (
                    <button
                      key={action.label}
                      className="mfg-quick-btn"
                      onClick={() => sendMessage(action.question)}
                    >
                      <span className="mfg-quick-icon">{action.icon}</span>
                      <span className="mfg-quick-label">{action.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {messages.map((m, i) => (
                  <MessageBubble key={i} message={m} username={user?.username} isLast={i === messages.length - 1} />
                ))}
                {streaming && stream && (
                  <div className="msg-row assistant">
                    <div className="msg-bubble">
                      {stream.thinking && (
                        <details className="thinking-block" open>
                          <summary>思考过程</summary>
                          <Markdown content={stream.thinking} />
                        </details>
                      )}
                      {stream.answer && <Markdown content={stream.answer} />}
                      {!stream.answer && !stream.thinking && <span className="spinner" />}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>

          {/* 文档面板（侧边抽屉） */}
          {showDocPanel && (
            <aside className="mfg-doc-panel">
              <div className="mfg-doc-panel-header">
                <span>📚 工业知识库</span>
                <button className="btn-icon" onClick={() => setShowDocPanel(false)}>
                  <IconX style={{ width: 14, height: 14 }} />
                </button>
              </div>
              <div className="mfg-doc-upload-zone" onClick={() => docInputRef.current?.click()}>
                <input
                  ref={docInputRef}
                  type="file"
                  accept={ACCEPT_DOC_EXT.join(",")}
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void uploadDoc(f);
                    e.target.value = "";
                  }}
                />
                {docUploading ? (
                  <span className="spinner" />
                ) : (
                  <span>📄 点击上传文档（PDF/Word/TXT/CSV…）</span>
                )}
              </div>
              <div className="mfg-doc-list">
                {docs.length === 0 ? (
                  <div className="mfg-doc-empty">暂无文档，上传后自动解析入库</div>
                ) : (
                  docs.map((doc) => (
                    <div key={doc.filename} className="mfg-doc-item">
                      <div className="mfg-doc-info">
                        <span className="mfg-doc-name" title={doc.filename}>{doc.filename}</span>
                        <span className="mfg-doc-meta">{doc.chunks} 片段</span>
                      </div>
                      <button className="btn-icon" onClick={() => void deleteDoc(doc.filename)} title="删除">
                        <IconTrash style={{ width: 13, height: 13 }} />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </aside>
          )}
        </div>

        {/* 输入区 */}
        <form className="mfg-input-area" onSubmit={handleSubmit}>
          {/* 图片附件预览 */}
          {(imageFile || imageUploading) && (
            <div className="mfg-attach-row">
              <div className="mfg-attach-chip">
                {imagePreview ? <img src={imagePreview} alt="预览" /> : <span className="spinner" />}
                <span className="mfg-attach-name">{imageFile?.name ?? "上传中…"}</span>
                {imageUploading && <span className="mfg-attach-status">上传中</span>}
                {!imageUploading && imageServerName && <span className="mfg-attach-ok">✓</span>}
                <button type="button" className="btn-icon" style={{ width: 20, height: 20 }} onClick={clearImage}>
                  <IconX style={{ width: 12, height: 12 }} />
                </button>
              </div>
            </div>
          )}

          <div className="mfg-composer-box">
            <input
              ref={imgInputRef}
              type="file"
              accept="image/*"
              style={{ display: "none" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void pickImage(f);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              className="btn-icon"
              title="附加图片（设备铭牌/故障截图/仪表盘）"
              onClick={() => imgInputRef.current?.click()}
              disabled={streaming}
            >
              <IconImage style={{ width: 18, height: 18 }} />
            </button>
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              placeholder="描述设备故障、工艺问题或维护需求…（支持上传图片辅助诊断）"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={streaming}
            />
            {streaming ? (
              <button type="button" className="mfg-send-btn stop" onClick={abort} title="停止生成">
                <IconStop width={18} height={18} />
              </button>
            ) : (
              <button type="submit" className="mfg-send-btn" disabled={!input.trim()} title="发送">
                <IconSend width={18} height={18} />
              </button>
            )}
          </div>

          <div className="mfg-composer-hint">
            <span>工业多智能体 · 故障诊断 / 工艺优化 / 预测维护 / 知识问答 / 视觉识别</span>
            <span>{input.length > 0 ? `${input.length} 字` : "Enter 发送"}</span>
          </div>
        </form>
      </main>
    </div>
  );
}
