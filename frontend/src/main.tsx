// 应用入口：路由 + 认证守卫 + 会话状态水合
import React, { useEffect } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import App from "./App";
import Login from "./pages/Login";
import Chat from "./pages/Chat";
import Knowledge from "./pages/Knowledge";
import Manufacturing from "./pages/Manufacturing";
import Stats from "./pages/Stats";
import Admin from "./pages/Admin";
import { useAuthStore } from "./store/auth";
import "./index.css";

/** 路由守卫：未认证跳转登录 */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** 启动时从本地令牌恢复用户信息 */
function AuthBootstrap() {
  const hydrate = useAuthStore((s) => s.hydrate);
  useEffect(() => {
    void hydrate();
  }, [hydrate]);
  return null;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthBootstrap />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <App />
            </RequireAuth>
          }
        >
          <Route index element={<Chat />} />
          <Route path="manufacturing" element={<Manufacturing />} />
          <Route path="knowledge" element={<Knowledge />} />
          <Route path="stats" element={<Stats />} />
          <Route path="admin" element={<Admin />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
