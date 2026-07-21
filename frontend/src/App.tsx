// 根布局：导航 rail（对话/知识库/统计/管理）+ 环境背景 + 内容区
import { NavLink, Outlet } from "react-router-dom";
import { useAuthStore } from "./store/auth";
import { ToastHost } from "./lib/toast";
import { IconBook, IconChart, IconChat, IconFactory, IconShield } from "./components/icons";

const NAV_ITEMS = [
  { to: "/", label: "对话", icon: IconChat, end: true },
  { to: "/manufacturing", label: "工业智造", icon: IconFactory, end: false },
  { to: "/knowledge", label: "知识库", icon: IconBook, end: false },
  { to: "/stats", label: "统计", icon: IconChart, end: false },
];

export default function App() {
  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false);

  return (
    <>
      <div className="ambient" />
      <div className="shell">
        <nav className="nav-rail">
          <div className="brand-mark" title="Nexus 多智能体系统">N</div>
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              title={item.label}
              className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
            >
              <item.icon />
            </NavLink>
          ))}
          {isAdmin && (
            <NavLink
              to="/admin"
              title="管理后台"
              className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
            >
              <IconShield />
            </NavLink>
          )}
          <div className="nav-spacer" />
        </nav>
        <Outlet />
      </div>
      <ToastHost />
    </>
  );
}
