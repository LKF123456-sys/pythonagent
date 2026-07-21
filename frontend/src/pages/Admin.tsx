// 管理页面（admin 角色）：系统统计 + 用户管理（禁用/启用）+ 深度健康检查
import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import * as api from "../lib/api";
import { toast } from "../lib/toast";
import { useAuthStore } from "../store/auth";
import type { AdminUser, HealthReport, SystemStats } from "../types";
import { IconActivity, IconRefresh, IconShield, IconUsers } from "../components/icons";

const HEALTH_LABEL: Record<string, { text: string; cls: string; dot: string }> = {
  ok: { text: "正常", cls: "tag-green", dot: "dot-green" },
  degraded: { text: "降级", cls: "tag-amber", dot: "dot-amber" },
  error: { text: "异常", cls: "tag-red", dot: "dot-red" },
};

export default function Admin() {
  const user = useAuthStore((s) => s.user);
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [healthLoading, setHealthLoading] = useState(false);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [s, u] = await Promise.all([api.getSystemStats(), api.listUsers()]);
      setStats(s);
      setUsers(u);
    } catch (e) {
      toast(`加载管理数据失败：${api.errDetail(e)}`, "error");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      setHealth(await api.getHealth());
    } catch (e) {
      toast(`健康检查失败：${api.errDetail(e)}`, "error");
    } finally {
      setHealthLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
    void loadHealth();
  }, [loadAll, loadHealth]);

  const toggleActive = async (u: AdminUser) => {
    try {
      await api.setUserActive(u.id, !u.is_active);
      setUsers((prev) => prev.map((x) => (x.id === u.id ? { ...x, is_active: !x.is_active } : x)));
      toast(u.is_active ? `已禁用 ${u.username}` : `已启用 ${u.username}`, "success");
    } catch (e) {
      toast(`操作失败：${api.errDetail(e)}`, "error");
    }
  };

  if (!user?.is_admin) {
    return (
      <div className="page">
        <div className="empty-state">
          <IconShield style={{ width: 40, height: 40, color: "var(--text-3)" }} />
          <div className="empty-title">需要管理员权限</div>
          <div className="empty-sub">当前账户无法访问管理页面</div>
        </div>
      </div>
    );
  }

  const overall = health ? HEALTH_LABEL[health.status] ?? HEALTH_LABEL.error : null;

  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <div>
            <div className="page-kicker">// Administration</div>
            <h1 className="page-title">管理后台</h1>
            <p className="page-desc">用户管理 · 系统统计 · 组件健康状态</p>
          </div>
          <button className="btn btn-ghost" onClick={() => { void loadAll(); void loadHealth(); }}>
            <IconRefresh style={{ width: 14, height: 14 }} /> 刷新
          </button>
        </div>

        {loading ? (
          <div className="page-loading" style={{ height: 300 }}>
            <span className="spinner" />
          </div>
        ) : (
          <>
            <div className="stat-grid">
              {[
                { label: "注册用户", value: stats?.user_count ?? 0, icon: <IconUsers style={{ width: 15, height: 15 }} /> },
                { label: "会话总数", value: stats?.conversation_count ?? 0, icon: null },
                { label: "消息总数", value: stats?.message_count ?? 0, icon: null },
                { label: "Token 总用量", value: stats?.total_tokens ?? 0, icon: <IconActivity style={{ width: 15, height: 15 }} /> },
              ].map((item, i) => (
                <motion.div
                  key={item.label}
                  className="stat-card"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                >
                  <div className="stat-label" style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    {item.icon}
                    {item.label}
                  </div>
                  <div className="stat-value">{item.value.toLocaleString()}</div>
                </motion.div>
              ))}
            </div>

            {/* 用户管理 */}
            <div className="panel">
              <div className="panel-head">
                <span className="panel-title">用户管理</span>
                <span className="tag tag-muted">{users.length} 个账户</span>
              </div>
              <div className="panel-body flush">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>用户名</th>
                      <th>角色</th>
                      <th>注册时间</th>
                      <th>状态</th>
                      <th style={{ textAlign: "right" }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.id}>
                        <td className="mono">#{u.id}</td>
                        <td style={{ color: "var(--text-1)" }}>
                          {u.username}
                          {u.id === user.user_id && <span className="tag tag-amber" style={{ marginLeft: 8 }}>当前</span>}
                        </td>
                        <td>{u.is_admin ? <span className="tag tag-amber">管理员</span> : <span className="tag tag-muted">用户</span>}</td>
                        <td className="mono">{u.created_at ? new Date(u.created_at).toLocaleDateString("zh-CN") : "—"}</td>
                        <td>
                          {u.is_active ? (
                            <span className="tag tag-green"><span className="dot dot-green" />活跃</span>
                          ) : (
                            <span className="tag tag-red">已禁用</span>
                          )}
                        </td>
                        <td style={{ textAlign: "right" }}>
                          {u.id !== user.user_id && (
                            <button
                              className={`switch ${u.is_active ? "on" : ""}`}
                              title={u.is_active ? "点击禁用" : "点击启用"}
                              onClick={() => void toggleActive(u)}
                            />
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* 健康状态 */}
            <div className="panel">
              <div className="panel-head">
                <span className="panel-title" style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  系统健康
                  {overall && <span className={`tag ${overall.cls}`}><span className={`dot ${overall.dot}`} />{overall.text}</span>}
                </span>
                <button className="btn btn-ghost" style={{ height: 30, fontSize: 12 }} onClick={() => void loadHealth()} disabled={healthLoading}>
                  {healthLoading ? <span className="spinner" style={{ width: 12, height: 12 }} /> : "重新检查"}
                </button>
              </div>
              <div className="panel-body">
                {!health ? (
                  <div style={{ textAlign: "center", color: "var(--text-3)", fontSize: 13, padding: "16px 0" }}>
                    {healthLoading ? "检查中…" : "暂无数据"}
                  </div>
                ) : (
                  <div className="health-grid">
                    {Object.entries(health.components).map(([name, comp]) => {
                      const meta = HEALTH_LABEL[comp.status] ?? HEALTH_LABEL.error;
                      return (
                        <div className="health-card" key={name}>
                          <div className="health-name">
                            <span className={`dot ${meta.dot}`} />
                            {name}
                          </div>
                          <div className="health-detail">
                            {comp.detail || meta.text}
                            {comp.models && comp.models.length > 0 && (
                              <div style={{ marginTop: 4, color: "var(--blue)" }}>{comp.models.join(" · ")}</div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
