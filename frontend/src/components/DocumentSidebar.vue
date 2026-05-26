<script setup lang="ts">
import { ref, watch } from "vue";

import type { DocumentListItem } from "../lib/types";

const props = defineProps<{
  documents: DocumentListItem[];
  selectedDocumentId: string | null;
  loading: boolean;
  creating: boolean;
  createError: string;
  searchQuery: string;
}>();

const emit = defineEmits<{
  (event: "select-document", docId: string): void;
  (event: "search-documents", query: string): void;
  (event: "create-document", payload: { title: string; content?: string; file?: File | null }): void;
  (event: "refresh-documents"): void;
}>();

const showComposer = ref(false);
const title = ref("");
const content = ref("");
const file = ref<File | null>(null);
const localQuery = ref(props.searchQuery);
const validationError = ref("");

function resetComposer() {
  title.value = "";
  content.value = "";
  file.value = null;
  validationError.value = "";
  showComposer.value = false;
}

function inferTitleFromFile(selectedFile: File | null) {
  if (!selectedFile?.name) {
    return "";
  }
  return selectedFile.name.replace(/\.[^.]+$/, "").trim();
}

function submitCreate() {
  const resolvedTitle = title.value.trim() || inferTitleFromFile(file.value) || "未命名文档";
  const trimmedContent = content.value.trim();

  if (!file.value && !trimmedContent) {
    validationError.value = "请填写 Markdown 内容或上传一个文档文件。";
    return;
  }

  validationError.value = "";

  emit("create-document", {
    title: resolvedTitle,
    content: file.value ? undefined : trimmedContent,
    file: file.value,
  });
}

function updateFile(event: Event) {
  const input = event.target as HTMLInputElement;
  file.value = input.files?.[0] || null;
  if (!title.value.trim() && file.value) {
    title.value = inferTitleFromFile(file.value);
  }
  validationError.value = "";
}

function formatMeta(document: DocumentListItem) {
  const size = Math.max(1, Math.round(document.total_chars / 1000));
  return `${document.total_blocks} 块 · ${size}KB`;
}

watch(
  () => props.creating,
  (creating, previousCreating) => {
    if (previousCreating && !creating && !props.createError) {
      resetComposer();
    }
  },
);
</script>

<template>
  <section class="sidebar-panel">
    <header class="sidebar-panel__header">
      <div>
        <p class="sidebar-panel__eyebrow">Workspace</p>
        <h2>文档管理</h2>
      </div>
      <button class="ghost-button" type="button" @click="emit('refresh-documents')">刷新</button>
    </header>

    <div class="sidebar-panel__toolbar">
      <input
        v-model="localQuery"
        class="search-input"
        type="search"
        placeholder="按标题搜索文档"
        @keyup.enter="emit('search-documents', localQuery)"
      />
      <button class="primary-button" type="button" @click="showComposer = !showComposer">
        {{ showComposer ? "收起" : "新建文档" }}
      </button>
    </div>

    <section v-if="showComposer" class="composer-card">
      <label>
        <span>标题</span>
        <input
          v-model="title"
          type="text"
          placeholder="例如：产品需求文档；上传文件时可留空自动取文件名"
          @input="validationError = ''"
        />
      </label>
      <label>
        <span>Markdown 内容</span>
        <textarea
          v-model="content"
          rows="8"
          placeholder="可直接粘贴 Markdown，或改为上传文件。"
          :disabled="Boolean(file)"
          @input="validationError = ''"
        />
      </label>
      <label class="file-field">
        <span>上传文件</span>
        <input type="file" accept=".md,.markdown,.txt,.docx" @change="updateFile" />
        <small>{{ file ? file.name : "支持 Markdown / TXT / DOCX" }}</small>
      </label>
      <p v-if="validationError" class="form-error">{{ validationError }}</p>
      <p v-else-if="createError" class="form-error">{{ createError }}</p>
      <button class="primary-button is-wide" type="button" :disabled="creating" @click="submitCreate">
        {{ creating ? "创建中..." : "创建并打开" }}
      </button>
    </section>

    <div class="sidebar-panel__list">
      <button
        v-for="document in documents"
        :key="document.doc_id"
        class="document-row"
        :class="{ 'is-active': selectedDocumentId === document.doc_id }"
        type="button"
        @click="emit('select-document', document.doc_id)"
      >
        <div class="document-row__glyph">
          <span>{{ document.title.slice(0, 1).toUpperCase() }}</span>
        </div>
        <div class="document-row__body">
          <strong>{{ document.title }}</strong>
          <span>{{ formatMeta(document) }}</span>
        </div>
      </button>

      <div v-if="!documents.length && !loading" class="sidebar-panel__empty">
        暂无文档，先创建一份 Markdown 或 DOCX 文档。
      </div>
    </div>
  </section>
</template>
