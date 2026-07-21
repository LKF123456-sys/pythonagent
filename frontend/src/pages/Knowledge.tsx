// 知识库页面：文档拖拽上传（PDF/docx/txt…）+ 文档列表 + 删除
import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import * as api from "../lib/api";
import { toast } from "../lib/toast";
import type { DocumentInfo } from "../types";
import { IconFile, IconTrash } from "../components/icons";

const ACCEPT_EXT = [".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".json", ".html", ".py"];

function extOf(filename: string): string {
  const i = filename.lastIndexOf(".");
  return i >= 0 ? filename.slice(i + 1) : "file";
}

export default function Knowledge() {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState<string | null>(null);
  const [dragover, setDragover] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setDocs(await api.listDocuments());
    } catch (e) {
      toast(`加载文档列表失败：${api.errDetail(e)}`, "error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const upload = async (file: File) => {
    setUploading(file.name);
    try {
      const result = await api.uploadDocument(file);
      toast(`「${result.filename}」已入库，切分为 ${result.chunks} 个片段`, "success");
      await refresh();
    } catch (e) {
      toast(`上传失败：${api.errDetail(e)}`, "error");
    } finally {
      setUploading(null);
    }
  };

  const remove = async (filename: string) => {
    try {
      await api.deleteDocument(filename);
      toast("文档已删除", "success");
      await refresh();
    } catch (e) {
      toast(`删除失败：${api.errDetail(e)}`, "error");
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragover(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void upload(file);
  };

  const totalChunks = docs.reduce((sum, d) => sum + d.chunks, 0);

  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <div>
            <div className="page-kicker">// Knowledge Base</div>
            <h1 className="page-title">知识库</h1>
            <p className="page-desc">上传文档构建 RAG 检索库，智能体回答时将自动引用相关片段</p>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <span className="tag tag-blue">{docs.length} 篇文档</span>
            <span className="tag tag-amber">{totalChunks} 个切片</span>
          </div>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPT_EXT.join(",")}
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void upload(f);
            e.target.value = "";
          }}
        />

        <div
          className={`dropzone ${dragover ? "dragover" : ""}`}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragover(true);
          }}
          onDragLeave={() => setDragover(false)}
          onDrop={onDrop}
        >
          {uploading ? (
            <>
              <div className="dropzone-icon"><span className="spinner" style={{ width: 26, height: 26, margin: "0 auto", display: "block" }} /></div>
              <div className="dropzone-main">正在解析并入库「{uploading}」…</div>
              <div className="dropzone-sub">文本提取 → 语义切片 → 向量化</div>
            </>
          ) : (
            <>
              <div className="dropzone-icon">⇪</div>
              <div className="dropzone-main">拖拽文档到此处，或点击选择文件</div>
              <div className="dropzone-sub">支持 PDF / DOCX / TXT / MD / CSV / JSON / HTML / PY</div>
            </>
          )}
        </div>

        <div className="panel" style={{ marginTop: 22 }}>
          <div className="panel-head">
            <span className="panel-title">已入库文档</span>
            <button className="btn btn-ghost" style={{ height: 30, fontSize: 12 }} onClick={() => void refresh()}>
              刷新
            </button>
          </div>
          <div className="panel-body flush">
            {loading ? (
              <div style={{ display: "grid", placeItems: "center", padding: 40 }}>
                <span className="spinner" />
              </div>
            ) : docs.length === 0 ? (
              <div style={{ padding: "38px 20px", textAlign: "center", color: "var(--text-3)", fontSize: 13 }}>
                知识库为空 —— 上传第一份文档开始构建
              </div>
            ) : (
              docs.map((d, i) => (
                <motion.div
                  key={d.filename}
                  className="doc-row"
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                >
                  <div className="doc-icon">{extOf(d.filename)}</div>
                  <div className="doc-info">
                    <div className="doc-name">{d.filename}</div>
                    <div className="doc-meta">
                      {d.chunks} chunks{d.timestamp ? ` · ${new Date(d.timestamp).toLocaleString("zh-CN")}` : ""}
                    </div>
                  </div>
                  <button className="btn-icon" title="删除文档" onClick={() => void remove(d.filename)}>
                    <IconTrash style={{ width: 15, height: 15 }} />
                  </button>
                </motion.div>
              ))
            )}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text-3)", fontSize: 12 }}>
          <IconFile style={{ width: 13, height: 13 }} />
          文档内容经语义切片后存入 ChromaDB，仅用于检索增强，不会被用于模型训练
        </div>
      </div>
    </div>
  );
}
