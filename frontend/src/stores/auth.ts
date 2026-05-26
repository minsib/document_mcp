import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { api } from "../lib/api";
import type { UserProfile } from "../lib/types";

const ACCESS_TOKEN_KEY = "document_mcp.access_token";
const REFRESH_TOKEN_KEY = "document_mcp.refresh_token";

export const useAuthStore = defineStore("auth", () => {
  const accessToken = ref("");
  const refreshToken = ref("");
  const user = ref<UserProfile | null>(null);
  const ready = ref(false);
  const loading = ref(false);
  const error = ref("");

  const isAuthenticated = computed(() => Boolean(accessToken.value && user.value));

  function persistTokens() {
    if (accessToken.value) {
      localStorage.setItem(ACCESS_TOKEN_KEY, accessToken.value);
    } else {
      localStorage.removeItem(ACCESS_TOKEN_KEY);
    }

    if (refreshToken.value) {
      localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken.value);
    } else {
      localStorage.removeItem(REFRESH_TOKEN_KEY);
    }
  }

  function applyTokens(tokens?: { access_token?: string; refresh_token?: string }) {
    accessToken.value = tokens?.access_token || "";
    refreshToken.value = tokens?.refresh_token || "";
    api.setAccessToken(accessToken.value);
    persistTokens();
  }

  async function initialize() {
    if (ready.value) {
      return;
    }

    accessToken.value = localStorage.getItem(ACCESS_TOKEN_KEY) || "";
    refreshToken.value = localStorage.getItem(REFRESH_TOKEN_KEY) || "";
    api.setAccessToken(accessToken.value);

    if (!accessToken.value) {
      ready.value = true;
      return;
    }

    try {
      user.value = await api.getCurrentUser();
    } catch (err) {
      clearAuth();
    } finally {
      ready.value = true;
    }
  }

  async function login(payload: { username: string; password: string }) {
    loading.value = true;
    error.value = "";
    try {
      const tokens = await api.login(payload);
      applyTokens(tokens);
      user.value = await api.getCurrentUser();
      return user.value;
    } catch (err) {
      error.value = err instanceof Error ? err.message : "登录失败";
      throw err;
    } finally {
      loading.value = false;
      ready.value = true;
    }
  }

  async function register(payload: {
    username: string;
    email: string;
    full_name?: string;
    password: string;
  }) {
    loading.value = true;
    error.value = "";
    try {
      await api.register(payload);
      return await login({ username: payload.username, password: payload.password });
    } catch (err) {
      error.value = err instanceof Error ? err.message : "注册失败";
      throw err;
    } finally {
      loading.value = false;
      ready.value = true;
    }
  }

  function clearAuth() {
    accessToken.value = "";
    refreshToken.value = "";
    user.value = null;
    api.setAccessToken("");
    persistTokens();
  }

  function logout() {
    clearAuth();
    ready.value = true;
  }

  return {
    accessToken,
    refreshToken,
    user,
    ready,
    loading,
    error,
    isAuthenticated,
    initialize,
    login,
    register,
    logout,
  };
});
