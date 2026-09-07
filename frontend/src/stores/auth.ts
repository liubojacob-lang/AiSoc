import { create } from "zustand";
import { api, setAccessToken } from "@/api/client";
import type { User } from "@/api/types";

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  loadMe: () => Promise<void>;
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  ready: false,

  async login(email, password) {
    const tokens = await api.post<{ access_token: string }>("/api/v1/auth/login", { email, password });
    setAccessToken(tokens.access_token);
    const me = await api.get<User>("/api/v1/auth/me");
    set({ user: me, ready: true });
  },

  async logout() {
    try {
      await api.post("/api/v1/auth/logout");
    } finally {
      setAccessToken(null);
      set({ user: null });
    }
  },

  async loadMe() {
    try {
      // page reload: access token lives in memory only — recover via refresh cookie
      const tokens = await api.post<{ access_token: string }>("/api/v1/auth/refresh");
      setAccessToken(tokens.access_token);
      const me = await api.get<User>("/api/v1/auth/me");
      set({ user: me, ready: true });
    } catch {
      set({ user: null, ready: true });
    }
  },
}));

export const hasRole = (user: User | null, ...roles: string[]) =>
  !!user && roles.some((r) => user.roles.includes(r));
