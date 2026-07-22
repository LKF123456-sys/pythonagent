// 消息气泡：用户/助手，含思考面板、Markdown 渲染、图片显示、操作栏（复制/重新生成）
import { useState } from "react";
import { motion } from "framer-motion";
import type { Message } from "../types";
import { Markdown } from "./Markdown";
import { ThinkingPanel } from "./ThinkingPanel";
import { IconCheck, IconCopy, IconRefresh } from "./icons";
import { toast } from "../lib/toast";
import { getAccessToken } from "../lib/api";

interface Props {
  message: Message;
  /** 是否为流式中的消息（显示光标，思考面板 live） */
  streaming?: boolean;
  /** 流式中的思考内容 */
  thinking?: string;
  username?: string;
  onRegenerate?: () => void;
  isLast?: boolean;
}

export function MessageBubble({ message, streaming = false, thinking, username, onRegenerate, isLast }: Props) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === "user";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      toast("已复制到剪贴板", "success");
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      toast("复制失败", "error");
    }
  };

  return (
    <motion.div
      className={`msg-row ${message.role}`}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
    >
      <div className="msg-avatar">{isUser ? (username?.[0]?.toUpperCase() ?? "U") : "N"}</div>
      <div className="msg-body">
        <div className="msg-meta">
          <span className="msg-role">{isUser ? (username ?? "你") : "Nexus"}</span>
          {!isUser && !streaming && message.token_count != null && message.token_count > 0 && (
            <span className="tag tag-muted">{message.token_count} tokens</span>
          )}
        </div>

        {!isUser && thinking && <ThinkingPanel content={thinking} live={streaming} />}

        {(message.content || streaming || message.image_filename) && (
          <div className="msg-bubble">
            {isUser ? (
              <>
                {message.image_filename && (
                  <img
                    className="msg-bubble-image"
                    src={`/api/v1/uploads/${message.image_filename}?token=${getAccessToken() ?? ""}`}
                    alt="上传图片"
                    loading="lazy"
                  />
                )}
                <span style={{ whiteSpace: "pre-wrap" }}>{message.content}</span>
              </>
            ) : (
              <>
                <Markdown content={message.content} />
                {streaming && <span className="stream-caret" />}
              </>
            )}
          </div>
        )}

        {!streaming && message.content && (
          <div className="msg-actions">
            <button className="btn-icon" onClick={copy} title="复制内容">
              {copied ? <IconCheck style={{ color: "var(--green)" }} /> : <IconCopy />}
            </button>
            {!isUser && isLast && onRegenerate && (
              <button className="btn-icon" onClick={onRegenerate} title="重新生成">
                <IconRefresh />
              </button>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}
