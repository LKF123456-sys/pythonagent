// 登录/注册页：分屏布局（左品牌视觉 + 粒子网格动态背景，右表单）
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { useAuthStore } from "../store/auth";
import { errDetail } from "../lib/api";

/** 粒子网格画布：漂移节点 + 近邻连线（琥珀/冷蓝双色） */
function ParticleField() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    let w = 0;
    let h = 0;
    const DPR = Math.min(window.devicePixelRatio || 1, 2);

    interface P { x: number; y: number; vx: number; vy: number; r: number; amber: boolean }
    let pts: P[] = [];

    const resize = () => {
      const rect = canvas.parentElement!.getBoundingClientRect();
      w = rect.width;
      h = rect.height;
      canvas.width = w * DPR;
      canvas.height = h * DPR;
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      const count = Math.min(70, Math.floor((w * h) / 16000));
      pts = Array.from({ length: count }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.35,
        vy: (Math.random() - 0.5) * 0.35,
        r: 1.2 + Math.random() * 1.8,
        amber: Math.random() < 0.45,
      }));
    };

    const LINK = 130;
    const tick = () => {
      ctx.clearRect(0, 0, w, h);
      // 连线
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const dx = pts[i].x - pts[j].x;
          const dy = pts[i].y - pts[j].y;
          const dist = Math.hypot(dx, dy);
          if (dist < LINK) {
            const alpha = (1 - dist / LINK) * 0.16;
            ctx.strokeStyle = `rgba(150, 172, 200, ${alpha})`;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(pts[i].x, pts[i].y);
            ctx.lineTo(pts[j].x, pts[j].y);
            ctx.stroke();
          }
        }
      }
      // 节点
      for (const p of pts) {
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0 || p.x > w) p.vx *= -1;
        if (p.y < 0 || p.y > h) p.vy *= -1;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = p.amber ? "rgba(232, 169, 78, 0.75)" : "rgba(127, 160, 196, 0.6)";
        ctx.fill();
      }
      raf = requestAnimationFrame(tick);
    };

    resize();
    tick();
    window.addEventListener("resize", resize);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return <canvas ref={canvasRef} className="login-canvas" />;
}

const AGENT_NODES = [
  { name: "supervisor", color: "var(--amber)" },
  { name: "search-agent", color: "var(--blue)" },
  { name: "rag-agent", color: "var(--blue)" },
  { name: "answer-agent", color: "var(--amber)" },
];

export default function Login() {
  const navigate = useNavigate();
  const { login, register, isAuthenticated } = useAuthStore();

  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isAuthenticated) navigate("/", { replace: true });
  }, [isAuthenticated, navigate]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!username.trim() || !password) {
      setError("请输入用户名和密码");
      return;
    }
    if (mode === "register" && password !== confirm) {
      setError("两次输入的密码不一致");
      return;
    }
    setLoading(true);
    try {
      if (mode === "login") {
        await login(username.trim(), password);
      } else {
        await register(username.trim(), password);
      }
      navigate("/", { replace: true });
    } catch (err) {
      setError(errDetail(err, mode === "login" ? "登录失败" : "注册失败"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-wrap">
      {/* 左侧：品牌视觉区 */}
      <div className="login-visual">
        <ParticleField />

        <div className="login-brand">
          <div className="brand-mark">N</div>
          <div>
            <div className="login-brand-name">NEXUS</div>
            <div className="login-brand-sub">MULTI-AGENT SYSTEM</div>
          </div>
        </div>

        <div>
          <motion.h1
            className="login-headline"
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          >
            一个问题，
            <br />
            调度<em>一整支</em>智能体编队
          </motion.h1>
          <motion.p
            className="login-desc"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.12 }}
          >
            Supervisor 实时路由决策，搜索、RAG 检索、视觉分析与长期记忆协同工作 ——
            每一次回答背后，都是完整的节点流水线。
          </motion.p>
          <motion.div
            className="login-nodes"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6, delay: 0.28 }}
            style={{ marginTop: 26 }}
          >
            {AGENT_NODES.map((n) => (
              <span className="login-node" key={n.name}>
                <span className="dot" style={{ background: n.color, boxShadow: `0 0 8px ${n.color}` }} />
                {n.name}
              </span>
            ))}
          </motion.div>
        </div>

        <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-3)", letterSpacing: "0.08em" }}>
          LANGGRAPH · DEEPSEEK · CHROMADB · TAVILY
        </div>
      </div>

      {/* 右侧：表单区 */}
      <div className="login-form-side">
        <motion.div
          className="login-card"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, delay: 0.1 }}
        >
          <div className="login-tabs">
            <button className={`login-tab ${mode === "login" ? "active" : ""}`} onClick={() => { setMode("login"); setError(""); }}>
              登录
            </button>
            <button className={`login-tab ${mode === "register" ? "active" : ""}`} onClick={() => { setMode("register"); setError(""); }}>
              注册
            </button>
          </div>

          <h2 className="login-title">{mode === "login" ? "欢迎回来" : "创建账户"}</h2>
          <p className="login-sub">
            {mode === "login" ? "登录后继续你的对话" : "注册后即可开始多智能体对话"}
          </p>

          {error && <div className="login-error">{error}</div>}

          <form onSubmit={submit}>
            <label className="label" htmlFor="username">用户名</label>
            <input
              id="username"
              className="field"
              value={username}
              autoComplete="username"
              placeholder="3-20 个字符"
              onChange={(e) => setUsername(e.target.value)}
              style={{ marginBottom: 16 }}
            />
            <label className="label" htmlFor="password">密码</label>
            <input
              id="password"
              className="field"
              type="password"
              value={password}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              placeholder="至少 6 位"
              onChange={(e) => setPassword(e.target.value)}
              style={{ marginBottom: mode === "register" ? 16 : 24 }}
            />
            {mode === "register" && (
              <>
                <label className="label" htmlFor="confirm">确认密码</label>
                <input
                  id="confirm"
                  className="field"
                  type="password"
                  value={confirm}
                  autoComplete="new-password"
                  placeholder="再次输入密码"
                  onChange={(e) => setConfirm(e.target.value)}
                  style={{ marginBottom: 24 }}
                />
              </>
            )}
            <button className="btn btn-primary" type="submit" disabled={loading} style={{ width: "100%", height: 44 }}>
              {loading ? <span className="spinner" /> : mode === "login" ? "登 录" : "注 册"}
            </button>
          </form>
        </motion.div>
      </div>
    </div>
  );
}
