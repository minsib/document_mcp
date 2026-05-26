<script setup lang="ts">
import { computed } from "vue";

import type { UserProfile } from "../lib/types";

const props = defineProps<{
  activeSection: "documents" | "versions";
  theme: "light" | "dark";
  user: UserProfile | null;
}>();

const emit = defineEmits<{
  (event: "select-section", section: "documents" | "versions"): void;
  (event: "toggle-theme"): void;
  (event: "logout"): void;
}>();

const userInitials = computed(() => {
  const name = props.user?.full_name || props.user?.username || "U";
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
});

const themeLabel = computed(() => (props.theme === "light" ? "夜间模式" : "日间模式"));
</script>

<template>
  <aside class="activity-bar">
    <div class="activity-bar__brand">
      <div class="activity-bar__brand-mark">D</div>
      <div class="activity-bar__brand-copy">
        <strong>Docs</strong>
        <span>MCP</span>
      </div>
    </div>

    <nav class="activity-bar__nav">
      <button
        class="activity-bar__button"
        :class="{ 'is-active': activeSection === 'documents' }"
        type="button"
        @click="emit('select-section', 'documents')"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M6 4.5h7.5L18 9v10.5H6z"
            fill="none"
            stroke="currentColor"
            stroke-linejoin="round"
            stroke-width="1.6"
          />
          <path d="M13.5 4.5V9H18" fill="none" stroke="currentColor" stroke-width="1.6" />
          <path d="M8.5 12.5h7M8.5 16h7" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.6" />
        </svg>
        <span>文档管理</span>
      </button>

      <button
        class="activity-bar__button"
        :class="{ 'is-active': activeSection === 'versions' }"
        type="button"
        @click="emit('select-section', 'versions')"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M5 7.5h14M5 12h14M5 16.5h9"
            fill="none"
            stroke="currentColor"
            stroke-linecap="round"
            stroke-width="1.8"
          />
          <circle cx="17.5" cy="16.5" r="3" fill="none" stroke="currentColor" stroke-width="1.6" />
        </svg>
        <span>版本管理</span>
      </button>

      <button class="activity-bar__theme" type="button" @click="emit('toggle-theme')">
        <svg v-if="theme === 'light'" viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M12 4.5v2.2M12 17.3v2.2M6.7 6.7l1.6 1.6M15.7 15.7l1.6 1.6M4.5 12h2.2M17.3 12h2.2M6.7 17.3l1.6-1.6M15.7 8.3l1.6-1.6"
            fill="none"
            stroke="currentColor"
            stroke-linecap="round"
            stroke-width="1.7"
          />
          <circle cx="12" cy="12" r="3.5" fill="none" stroke="currentColor" stroke-width="1.7" />
        </svg>
        <svg v-else viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M18 15.4A7.2 7.2 0 0 1 8.6 6a7.8 7.8 0 1 0 9.4 9.4Z"
            fill="none"
            stroke="currentColor"
            stroke-linejoin="round"
            stroke-width="1.7"
          />
        </svg>
        <span>{{ themeLabel }}</span>
      </button>
    </nav>

    <div class="activity-bar__user">
      <div class="activity-bar__avatar">{{ userInitials }}</div>
      <div class="activity-bar__profile">
        <strong>{{ user?.full_name || user?.username || "未登录" }}</strong>
        <span>{{ user?.username || "Guest" }}</span>
      </div>
      <button class="activity-bar__logout" type="button" @click="emit('logout')">退出</button>
    </div>
  </aside>
</template>
