import { useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/auth";

// 登录 / 注册页面
export default function Login() {
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const register = useAuthStore((s) => s.register);

  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (mode === "login") {
        await login(username, password);
      } else {
        await register(username, password);
      }
      navigate("/", { replace: true });
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || "操作失败";
      setError(typeof detail === "string" ? detail : "操作失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>多智能体对话系统</h1>
        <p className="sub">{mode === "login" ? "登录以继续" : "创建新账户"}</p>

        {error && <div className="err-msg">{error}</div>}

        <div className="field">
          <label>用户名</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="2-50 个字符"
            autoComplete="username"
          />
        </div>

        <div className="field">
          <label>密码</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="至少 6 位"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
        </div>

        <button className="btn-primary" type="submit" disabled={loading}>
          {loading ? "请稍候…" : mode === "login" ? "登录" : "注册"}
        </button>

        <div className="switch-mode">
          {mode === "login" ? (
            <>
              还没有账户？<a onClick={() => setMode("register")}>立即注册</a>
            </>
          ) : (
            <>
              已有账户？<a onClick={() => setMode("login")}>返回登录</a>
            </>
          )}
        </div>
      </form>
    </div>
  );
}
