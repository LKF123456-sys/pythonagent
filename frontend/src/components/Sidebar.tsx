// 会话侧边栏：搜索、时间分组（今天/7天/更早）、右键菜单（重命名/导出/删除）、用户信息
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import * as api from "../lib/api";
import { useChatStore } from "../store/chat";
import { useAuthStore } from "../store/auth";
import { toast } from "../lib/toast";
import type { Conversation } from "../types";
import {
  IconDownload,
  IconEdit,
  IconLogout,
  IconMore,
  IconPlus,
  IconSearch,
  IconTrash,
} from "./icons";

type MenuState = { sessionId: string; x: number; y: number } | null;

function groupLabel(dateStr: string): "今天" | "最近 7 天" | "更早" {
  const d = new Date(dateStr);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const t = d.getTime();
  if (t >= startOfToday) return "今天";
  if (t >= startOfToday - 6 * 86400_000) return "最近 7 天";
  return "更早";
}

export function Sidebar() {
  const navigate = useNavigate();
  const conversations = useChatStore((s) => s.conversations);
  const currentSessionId = useChatStore((s) => s.currentSessionId);
  const selectSession = useChatStore((s) => s.selectSession);
  const newChat = useChatStore((s) => s.newChat);
  const renameConversation = useChatStore((s) => s.renameConversation);
  const removeConversation = useChatStore((s) => s.removeConversation);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  const [query, setQuery] = useState("");
  const [menu, setMenu] = useState<MenuState>(null);
  const [renameTarget, setRenameTarget] = useState<Conversation | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // 点击其他区域关闭菜单
  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenu(null);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [menu]);

  const groups = useMemo(() => {
    const filtered = conversations.filter((c) => c.title.toLowerCase().includes(query.toLowerCase()));
    const map: Record<string, Conversation[]> = { 今天: [], "最近 7 天": [], 更早: [] };
    for (const c of filtered) map[groupLabel(c.updated_at || c.created_at)].push(c);
    return map;
  }, [conversations, query]);

  const openMenu = (e: React.MouseEvent, sessionId: string) => {
    e.preventDefault();
    e.stopPropagation();
    setMenu({ sessionId, x: e.clientX, y: e.clientY });
  };

  const doExport = async (sessionId: string, format: "markdown" | "json") => {
    setMenu(null);
    try {
      const blob = await api.exportConversation(sessionId, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `conversation-${sessionId.slice(0, 8)}.${format === "markdown" ? "md" : "json"}`;
      a.click();
      URL.revokeObjectURL(url);
      toast("导出成功", "success");
    } catch (e) {
      toast(`导出失败：${api.errDetail(e)}`, "error");
    }
  };

  const doRename = async () => {
    if (!renameTarget || !renameValue.trim()) return;
    try {
      await renameConversation(renameTarget.session_id, renameValue.trim());
      toast("已重命名", "success");
    } catch (e) {
      toast(`重命名失败：${api.errDetail(e)}`, "error");
    }
    setRenameTarget(null);
  };

  const doDelete = async () => {
    if (!deleteTarget) return;
    try {
      await removeConversation(deleteTarget.session_id);
      toast("会话已删除", "success");
    } catch (e) {
      toast(`删除失败：${api.errDetail(e)}`, "error");
    }
    setDeleteTarget(null);
  };

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <div className="sidebar-title-row">
          <span className="sidebar-title">会话</span>
          <button className="btn-icon" title="新建对话" onClick={newChat}>
            <IconPlus style={{ width: 16, height: 16 }} />
          </button>
        </div>
        <div className="search-box">
          <IconSearch />
          <input
            placeholder="搜索会话…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>

      <div className="sidebar-list">
        {conversations.length === 0 && (
          <div style={{ padding: "28px 12px", textAlign: "center", color: "var(--text-3)", fontSize: 12.5 }}>
            还没有对话，开始第一段吧
          </div>
        )}
        {(Object.keys(groups) as Array<keyof typeof groups>).map((label) =>
          groups[label].length > 0 ? (
            <div key={label}>
              <div className="conv-group-label">{label}</div>
              {groups[label].map((c) => (
                <button
                  key={c.session_id}
                  className={`conv-item ${c.session_id === currentSessionId ? "active" : ""} ${
                    menu?.sessionId === c.session_id ? "menu-open" : ""
                  }`}
                  onClick={() => selectSession(c.session_id)}
                  onContextMenu={(e) => openMenu(e, c.session_id)}
                >
                  <span className="conv-item-title">{c.title || "未命名对话"}</span>
                  <span
                    className="more-btn"
                    role="button"
                    tabIndex={-1}
                    onClick={(e) => openMenu(e as unknown as React.MouseEvent, c.session_id)}
                  >
                    <IconMore style={{ width: 14, height: 14 }} />
                  </span>
                </button>
              ))}
            </div>
          ) : null
        )}
      </div>

      <div className="sidebar-foot">
        <div className="user-avatar">{user?.username?.[0]?.toUpperCase() ?? "?"}</div>
        <div className="user-meta">
          <div className="user-name">{user?.username ?? "…"}</div>
          <div className="user-role">{user?.is_admin ? "管理员" : "普通用户"}</div>
        </div>
        <button className="btn-icon" title="退出登录" onClick={handleLogout}>
          <IconLogout style={{ width: 16, height: 16 }} />
        </button>
      </div>

      {/* 右键/更多菜单 */}
      {menu && (
        <div
          className="ctx-menu"
          ref={menuRef}
          style={{
            left: Math.min(menu.x, window.innerWidth - 170),
            top: Math.min(menu.y, window.innerHeight - 160),
          }}
        >
          <button
            className="ctx-menu-item"
            onClick={() => {
              const target = conversations.find((c) => c.session_id === menu.sessionId);
              setRenameTarget(target ?? null);
              setRenameValue(target?.title ?? "");
              setMenu(null);
            }}
          >
            <IconEdit /> 重命名
          </button>
          <button className="ctx-menu-item" onClick={() => doExport(menu.sessionId, "markdown")}>
            <IconDownload /> 导出 Markdown
          </button>
          <button className="ctx-menu-item" onClick={() => doExport(menu.sessionId, "json")}>
            <IconDownload /> 导出 JSON
          </button>
          <button
            className="ctx-menu-item danger"
            onClick={() => {
              const target = conversations.find((c) => c.session_id === menu.sessionId);
              setDeleteTarget(target ?? null);
              setMenu(null);
            }}
          >
            <IconTrash /> 删除
          </button>
        </div>
      )}

      {/* 重命名模态框 */}
      {renameTarget && (
        <div className="modal-mask" onClick={() => setRenameTarget(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">重命名会话</div>
            <input
              className="field"
              value={renameValue}
              autoFocus
              maxLength={60}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && doRename()}
            />
            <div className="modal-actions">
              <button className="btn btn-ghost" onClick={() => setRenameTarget(null)}>
                取消
              </button>
              <button className="btn btn-primary" onClick={doRename}>
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 删除确认模态框 */}
      {deleteTarget && (
        <div className="modal-mask" onClick={() => setDeleteTarget(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">删除会话</div>
            <p style={{ color: "var(--text-2)", fontSize: 13.5 }}>
              确定删除「{deleteTarget.title || "未命名对话"}」吗？该操作不可恢复。
            </p>
            <div className="modal-actions">
              <button className="btn btn-ghost" onClick={() => setDeleteTarget(null)}>
                取消
              </button>
              <button className="btn btn-danger" onClick={doDelete}>
                删除
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
