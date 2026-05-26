import { ref } from "vue";
import { defineStore } from "pinia";

export type ThemeMode = "light" | "dark";

const THEME_KEY = "document_mcp.theme";

export const useUiStore = defineStore("ui", () => {
  const theme = ref<ThemeMode>("light");

  function applyTheme(nextTheme: ThemeMode) {
    theme.value = nextTheme;
    document.documentElement.dataset.theme = nextTheme;
    document.documentElement.style.colorScheme = nextTheme;
    localStorage.setItem(THEME_KEY, nextTheme);
  }

  function initializeTheme() {
    const storedTheme = localStorage.getItem(THEME_KEY);
    const resolvedTheme: ThemeMode = storedTheme === "dark" ? "dark" : "light";
    applyTheme(resolvedTheme);
  }

  function toggleTheme() {
    applyTheme(theme.value === "light" ? "dark" : "light");
  }

  return {
    theme,
    initializeTheme,
    toggleTheme,
    applyTheme,
  };
});
