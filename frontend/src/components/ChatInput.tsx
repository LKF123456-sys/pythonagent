// 输入区：自适应高度 textarea + 图片上传预览 + 发送/停止生成
import { useEffect, useRef, useState } from "react";
import * as api from "../lib/api";
import { useChatStore } from "../store/chat";
import { IconImage, IconSend, IconStop, IconX } from "./icons";
import { toast } from "../lib/toast";

export function ChatInput() {
  const [text, setText] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string>("");
  const [imageServerName, setImageServerName] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const streaming = useChatStore((s) => s.streaming);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const abort = useChatStore((s) => s.abort);

  // 自适应高度
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [text]);

  const pickImage = (file: File) => {
    if (!file.type.startsWith("image/")) {
      toast("仅支持图片文件", "error");
      return;
    }
    setImageFile(file);
    setImagePreview(URL.createObjectURL(file));
    // 立即上传到后端，发送时仅传 filename
    setUploading(true);
    api
      .uploadImage(file)
      .then((filename) => {
        setImageServerName(filename);
        setUploading(false);
      })
      .catch((e) => {
        setUploading(false);
        setImageFile(null);
        setImagePreview("");
        toast(`图片上传失败：${api.errDetail(e)}`, "error");
      });
  };

  const clearImage = () => {
    if (imagePreview) URL.revokeObjectURL(imagePreview);
    setImageFile(null);
    setImagePreview("");
    setImageServerName("");
  };

  const submit = () => {
    const question = text.trim();
    if (!question || streaming) return;
    if (imageFile && (!imageServerName || uploading)) {
      toast("图片仍在上传，请稍候", "info");
      return;
    }
    sendMessage(question, imageServerName || undefined);
    setText("");
    clearImage();
    textareaRef.current?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="composer">
      {(imageFile || uploading) && (
        <div className="composer-attachments">
          <div className="attach-chip">
            {imagePreview ? <img src={imagePreview} alt="预览" /> : <span className="spinner" />}
            <span>{imageFile?.name ?? "上传中…"}</span>
            {uploading && <span style={{ color: "var(--text-3)" }}>上传中</span>}
            {!uploading && imageServerName && <span style={{ color: "var(--green)" }}>✓</span>}
            <button className="btn-icon" style={{ width: 20, height: 20 }} onClick={clearImage}>
              <IconX style={{ width: 12, height: 12 }} />
            </button>
          </div>
        </div>
      )}

      <div className="composer-box">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) pickImage(f);
            e.target.value = "";
          }}
        />
        <button
          className="btn-icon"
          title="附加图片（视觉分析）"
          onClick={() => fileInputRef.current?.click()}
          disabled={streaming}
        >
          <IconImage style={{ width: 18, height: 18 }} />
        </button>
        <textarea
          ref={textareaRef}
          rows={1}
          value={text}
          placeholder="输入问题，Enter 发送，Shift+Enter 换行…"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
        />
        {streaming ? (
          <button className="send-btn stop" onClick={abort} title="停止生成">
            <IconStop />
          </button>
        ) : (
          <button className="send-btn" onClick={submit} disabled={!text.trim()} title="发送">
            <IconSend />
          </button>
        )}
      </div>

      <div className="composer-hint">
        <span>多智能体协同 · 路由 / 搜索 / RAG / 记忆</span>
        <span>{text.length > 0 ? `${text.length} 字` : "v2.0"}</span>
      </div>
    </div>
  );
}
