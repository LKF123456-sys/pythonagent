// 统计面板：Token 用量（按日柱状图）+ 汇总指标
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import * as api from "../lib/api";
import { toast } from "../lib/toast";
import type { TokenStats } from "../types";

export default function Stats() {
  const [stats, setStats] = useState<TokenStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .getTokenStats(days)
      .then((data) => {
        if (!cancelled) setStats(data);
      })
      .catch((e) => toast(`加载统计失败：${api.errDetail(e)}`, "error"))
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  const daily = stats?.daily ?? [];
  const maxTokens = Math.max(1, ...daily.map((d) => d.total_tokens));
  const totalMessages = daily.reduce((s, d) => s + d.message_count, 0);
  const avgPerDay = daily.length > 0 ? Math.round((stats?.total_tokens ?? 0) / daily.length) : 0;
  const peak = daily.reduce((best, d) => (d.total_tokens > best.total_tokens ? d : best), daily[0]);

  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <div>
            <div className="page-kicker">// Analytics</div>
            <h1 className="page-title">用量统计</h1>
            <p className="page-desc">Token 消耗与对话活跃度（仅统计你的账户）</p>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                className={`btn ${days === d ? "btn-primary" : "btn-ghost"}`}
                style={{ height: 32, fontSize: 12.5 }}
                onClick={() => setDays(d)}
              >
                {d} 天
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="page-loading" style={{ height: 300 }}>
            <span className="spinner" />
          </div>
        ) : (
          <>
            <div className="stat-grid">
              <motion.div className="stat-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
                <div className="stat-label">总 Token 用量</div>
                <div className="stat-value">
                  {(stats?.total_tokens ?? 0).toLocaleString()}
                  <span className="stat-unit">tokens</span>
                </div>
              </motion.div>
              <motion.div className="stat-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
                <div className="stat-label">助手消息数</div>
                <div className="stat-value">{totalMessages.toLocaleString()}</div>
              </motion.div>
              <motion.div className="stat-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
                <div className="stat-label">日均消耗</div>
                <div className="stat-value">
                  {avgPerDay.toLocaleString()}
                  <span className="stat-unit">/天</span>
                </div>
              </motion.div>
              <motion.div className="stat-card" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
                <div className="stat-label">峰值日</div>
                <div className="stat-value" style={{ fontSize: 22, paddingTop: 8 }}>
                  {peak ? peak.date.slice(5) : "—"}
                  {peak && <span className="stat-unit">{peak.total_tokens.toLocaleString()} tk</span>}
                </div>
              </motion.div>
            </div>

            <div className="panel">
              <div className="panel-head">
                <span className="panel-title">每日 Token 用量</span>
                <span className="tag tag-muted">近 {days} 天</span>
              </div>
              <div className="panel-body">
                {daily.length === 0 ? (
                  <div style={{ textAlign: "center", color: "var(--text-3)", padding: "30px 0", fontSize: 13 }}>
                    该时间范围内暂无用量记录
                  </div>
                ) : (
                  <div className="bar-chart">
                    {daily.map((d) => (
                      <div className="bar-col" key={d.date} title={`${d.date}：${d.total_tokens} tokens / ${d.message_count} 条`}>
                        <div
                          className="bar"
                          style={{ height: `${Math.max(2, (d.total_tokens / maxTokens) * 100)}%` }}
                        />
                        <span className="bar-label">{d.date.slice(8)}</span>
                      </div>
                    ))}
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
