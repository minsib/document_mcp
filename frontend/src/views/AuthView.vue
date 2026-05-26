<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { useAuthStore } from "../stores/auth";

const router = useRouter();
const auth = useAuthStore();

const mode = ref<"login" | "register">("login");
const form = reactive({
  username: "",
  email: "",
  full_name: "",
  password: "",
});

async function submit() {
  if (mode.value === "login") {
    await auth.login({
      username: form.username,
      password: form.password,
    });
  } else {
    await auth.register({
      username: form.username,
      email: form.email,
      full_name: form.full_name,
      password: form.password,
    });
  }

  await router.push("/app");
}
</script>

<template>
  <main class="auth-layout">
    <section class="auth-hero">
      <div class="auth-hero__badge">LangGraph Workflow + Memory</div>
      <h1>文档编辑台</h1>
      <p>
        左侧是 VSCode 风格的工作台，右侧保留 ChatGPT 式对话区，中间用于 Markdown 阅读与富文本修订。
      </p>

      <div class="auth-hero__terminal">
        <div class="auth-hero__terminal-bar">
          <span></span><span></span><span></span>
        </div>
        <pre>
document_mcp/
├── documents/
├── revisions/
├── memory/
└── chat/
        </pre>
      </div>
    </section>

    <section class="auth-card">
      <header class="auth-card__header">
        <div class="segmented-control">
          <button
            class="segmented-control__button"
            :class="{ 'is-active': mode === 'login' }"
            type="button"
            @click="mode = 'login'"
          >
            登录
          </button>
          <button
            class="segmented-control__button"
            :class="{ 'is-active': mode === 'register' }"
            type="button"
            @click="mode = 'register'"
          >
            注册
          </button>
        </div>
        <h2>{{ mode === "login" ? "回到工作台" : "创建新的工作空间账户" }}</h2>
      </header>

      <form class="auth-form" @submit.prevent="submit">
        <label>
          <span>用户名</span>
          <input v-model="form.username" type="text" autocomplete="username" required />
        </label>

        <label v-if="mode === 'register'">
          <span>邮箱</span>
          <input v-model="form.email" type="email" autocomplete="email" required />
        </label>

        <label v-if="mode === 'register'">
          <span>姓名</span>
          <input v-model="form.full_name" type="text" autocomplete="name" />
        </label>

        <label>
          <span>密码</span>
          <input v-model="form.password" type="password" autocomplete="current-password" required />
        </label>

        <p v-if="auth.error" class="form-error">{{ auth.error }}</p>

        <button class="primary-button is-wide is-large" type="submit" :disabled="auth.loading">
          {{ auth.loading ? "处理中..." : mode === "login" ? "进入主页面" : "创建账户并进入" }}
        </button>
      </form>
    </section>
  </main>
</template>
