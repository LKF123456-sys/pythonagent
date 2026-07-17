import type { Conversation } from "../types";
import { useAuthStore } from "../store/auth";

interface Props {
  conversations: Conversation[];
  activeId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

// 左侧边栏：新建对话 + 历史会话列表 + 用户信息/登出
export default function Sidebar({ conversations, activeId, onSelect, onNew, onDelete }: Props) {
  const username = useAuthStore((s) => s.username);
  const logout = useAuthStore((s) => s.logout);

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <button className="new-chat-btn" onClick={onNew}>
          ＋ 新建对话
        </button>
      </div>

      <div className="conv-list">
        {conversations.map((c) => (
          <div
            key={c.session_id}
            className={`conv-item ${c.session_id === activeId ? "active" : ""}`}
            onClick={() => onSelect(c.session_id)}
          >
            <span className="conv-title">{c.title || "未命名对话"}</span>
            <button
              className="conv-del"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(c.session_id);
              }}
              title="删除"
            >
              🗑
            </button>
          </div>
        ))}
      </div>

      <div className="sidebar-footer">
        <span>👤 {username}</span>
        <button className="logout-btn" onClick={logout}>
          登出
        </button>
      </div>
    </div>
  );
}
