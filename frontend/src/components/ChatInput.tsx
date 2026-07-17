import { useRef, useState, KeyboardEvent } from "react";
import * as api from "../api/client";

interface Props {
  disabled: boolean;
  onSend: (question: string, imageFilename: string) => void;
  onDocUploaded: (filename: string, chunks: number) => void;
}

// 底部输入区：文本输入 + 图片上传 + 文档上传（RAG）
export default function ChatInput({ disabled, onSend, onDocUploaded }: Props) {
  const [text, setText] = useState("");
  const [imageFilename, setImageFilename] = useState("");
  const [uploading, setUploading] = useState(false);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const docInputRef = useRef<HTMLInputElement>(null);

  function submit() {
    const q = text.trim();
    if (!q || disabled) return;
    onSend(q, imageFilename);
    setText("");
    setImageFilename("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  async function handleImage(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const filename = await api.uploadImage(file);
      setImageFilename(filename);
    } catch (err) {
      alert("图片上传失败");
    } finally {
      setUploading(false);
      if (imageInputRef.current) imageInputRef.current.value = "";
    }
  }

  async function handleDoc(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const res = await api.uploadDocument(file);
      onDocUploaded(res.filename, res.chunks);
    } catch (err) {
      alert("文档上传失败");
    } finally {
      setUploading(false);
      if (docInputRef.current) docInputRef.current.value = "";
    }
  }

  return (
    <div className="input-area">
      <div className="input-inner">
        <div className="toolbar">
          <button
            className="tool-btn"
            onClick={() => imageInputRef.current?.click()}
            disabled={uploading}
          >
            📷 图片
          </button>
          <button
            className="tool-btn"
            onClick={() => docInputRef.current?.click()}
            disabled={uploading}
          >
            📄 文档(RAG)
          </button>
          {imageFilename && <span className="attach-tag">已附加图片：{imageFilename}</span>}
          {uploading && <span className="attach-tag">上传中…</span>}
          <input
            ref={imageInputRef}
            type="file"
            accept="image/*"
            style={{ display: "none" }}
            onChange={handleImage}
          />
          <input
            ref={docInputRef}
            type="file"
            accept=".txt,.md,.csv,.json,.pdf,.html,.py,.java,.js,.ts"
            style={{ display: "none" }}
            onChange={handleDoc}
          />
        </div>

        <div className="input-row">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            rows={1}
          />
          <button className="send-btn" onClick={submit} disabled={disabled || !text.trim()}>
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
