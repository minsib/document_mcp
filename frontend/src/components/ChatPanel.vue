<script setup lang="ts">
import { computed, ref } from "vue";

import type { UiChatMessage } from "../lib/types";

const props = defineProps<{
  messages: UiChatMessage[];
  busy: boolean;
  disabled: boolean;
  documentTitle: string;
}>();

const emit = defineEmits<{
  (event: "send", message: string): void;
  (event: "select-candidate", payload: { blockId: string; sourceMessage: string }): void;
  (event: "confirm", payload: { message: UiChatMessage; action: "apply" | "cancel" }): void;
}>();

const draft = ref("");

const actionableMessages = computed(() =>
  props.messages.filter((message) => message.role === "assistant"),
);

function submit() {
  const value = draft.value.trim();
  if (!value || props.disabled || props.busy) {
    return;
  }
  emit("send", value);
  draft.value = "";
}
</script>

<template>
  <aside class="chat-panel">
    <header class="chat-panel__header">
      <div>
        <p class="chat-panel__eyebrow">Chat Console</p>
        <h2>{{ documentTitle || "对话式编辑" }}</h2>
      </div>
      <span class="chat-panel__status" :class="{ 'is-busy': busy }">
        {{ busy ? "智能体处理中" : disabled ? "请选择文档" : "就绪" }}
      </span>
    </header>

    <div class="chat-panel__stream">
      <div v-if="!messages.length" class="chat-panel__empty">
        右侧用于对话式编辑。你可以直接描述修改要求，系统会给出预览、消歧或确认。
      </div>

      <article
        v-for="message in messages"
        :key="message.id"
        class="chat-message"
        :class="`is-${message.role}`"
      >
        <header class="chat-message__meta">
          <strong>{{ message.role === "user" ? "你" : message.role === "assistant" ? "助手" : "系统" }}</strong>
          <span>{{ new Date(message.createdAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) }}</span>
        </header>

        <div class="chat-message__body">{{ message.content }}</div>

        <div v-if="message.clarification" class="chat-message__clarification">
          <strong>{{ message.clarification.message }}</strong>
          <p>{{ message.clarification.question || message.clarification.reason }}</p>
        </div>

        <div v-if="message.candidates?.length" class="chat-message__actions">
          <button
            v-for="candidate in message.candidates"
            :key="candidate.block_id"
            class="candidate-chip"
            type="button"
            @click="emit('select-candidate', { blockId: candidate.block_id, sourceMessage: message.sourceMessage || '' })"
          >
            <strong>{{ candidate.heading_context }}</strong>
            <span>{{ candidate.snippet }}</span>
          </button>
        </div>

        <div v-if="message.preview" class="chat-message__preview">
          <header>
            <strong>预览 {{ message.preview.total_changes }} 处修改</strong>
            <span>{{ message.preview.estimated_impact }}</span>
          </header>
          <div v-for="diff in message.preview.diffs" :key="diff.block_id" class="diff-card">
            <p class="diff-card__heading">{{ diff.heading_context }}</p>
            <div class="diff-card__pair">
              <div>
                <small>修改前</small>
                <p>{{ diff.before_snippet }}</p>
              </div>
              <div>
                <small>修改后</small>
                <p>{{ diff.after_snippet }}</p>
              </div>
            </div>
          </div>

          <div class="chat-message__preview-actions">
            <button class="primary-button" type="button" @click="emit('confirm', { message, action: 'apply' })">
              应用修改
            </button>
            <button class="ghost-button" type="button" @click="emit('confirm', { message, action: 'cancel' })">
              取消
            </button>
          </div>
        </div>
      </article>
    </div>

    <footer class="chat-panel__composer">
      <textarea
        v-model="draft"
        rows="4"
        :disabled="disabled || busy"
        placeholder="例如：把技术架构那段的 FastAPI 改成 Django，并保持语气专业。"
        @keydown.enter.exact.prevent="submit"
      />
      <button class="primary-button is-wide" type="button" :disabled="disabled || busy" @click="submit">
        发送编辑请求
      </button>
    </footer>
  </aside>
</template>
