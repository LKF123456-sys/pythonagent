// 认证状态管理（zustand）
import { create } from "zustand";
import * as api from "../api/client";

interface AuthState {
  token: string | null;
  username: string | null;
  userId: number | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: api.getToken(),
  username: localStorage.getItem("agent_username"),
  userId: null,
  isAuthenticated: !!api.getToken(),

  login: async (username, password) => {
    const res = await api.login(username, password);
    api.setToken(res.access_token);
    localStorage.setItem("agent_username", res.username);
    set({
      token: res.access_token,
      username: res.username,
      userId: res.user_id,
      isAuthenticated: true,
    });
  },

  register: async (username, password) => {
    const res = await api.register(username, password);
    api.setToken(res.access_token);
    localStorage.setItem("agent_username", res.username);
    set({
      token: res.access_token,
      username: res.username,
      userId: res.user_id,
      isAuthenticated: true,
    });
  },

  logout: () => {
    api.clearToken();
    localStorage.removeItem("agent_username");
    set({ token: null, username: null, userId: null, isAuthenticated: false });
  },
}));
