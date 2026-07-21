// 认证状态管理（Zustand）
import { create } from "zustand";
import * as api from "../lib/api";
import type { UserInfo } from "../types";

interface AuthState {
  user: UserInfo | null;
  isAuthenticated: boolean;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  hydrate: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: !!api.getAccessToken(),
  loading: false,

  login: async (username, password) => {
    const data = await api.login(username, password);
    api.setTokens(data.access_token, data.refresh_token);
    set({
      isAuthenticated: true,
      user: {
        user_id: data.user_id,
        username: data.username,
        is_admin: data.is_admin,
        created_at: "",
      },
    });
  },

  register: async (username, password) => {
    const data = await api.register(username, password);
    api.setTokens(data.access_token, data.refresh_token);
    set({
      isAuthenticated: true,
      user: {
        user_id: data.user_id,
        username: data.username,
        is_admin: data.is_admin,
        created_at: "",
      },
    });
  },

  logout: async () => {
    const refresh = api.getRefreshToken() ?? undefined;
    try {
      await api.logout(refresh);
    } catch {
      // 即使后端登出失败也清除本地凭证
    }
    api.clearTokens();
    set({ user: null, isAuthenticated: false });
  },

  hydrate: async () => {
    if (!api.getAccessToken()) {
      set({ isAuthenticated: false, user: null });
      return;
    }
    set({ loading: true });
    try {
      const me = await api.fetchMe();
      set({ user: me, isAuthenticated: true, loading: false });
    } catch {
      api.clearTokens();
      set({ user: null, isAuthenticated: false, loading: false });
    }
  },
}));
