<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { QuillEditor } from "@vueup/vue-quill";
import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";
import TurndownService from "turndown";

const props = defineProps<{
  title: string;
  markdown: string;
  syncKey: string;
  hasDocument: boolean;
  readOnly: boolean;
  saving: boolean;
  sectionLabel: string;
}>();

const emit = defineEmits<{
  (event: "save", payload: { markdown: string; changeSummary?: string }): void;
}>();

const isEditing = ref(false);
const changeSummary = ref("");
const richTextHtml = ref("");

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
});
const turndown = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
});

function syncRichTextFromMarkdown() {
  richTextHtml.value = DOMPurify.sanitize(markdown.render(props.markdown || ""));
}

watch(
  () => [props.syncKey, props.markdown, props.readOnly],
  () => {
    syncRichTextFromMarkdown();
    changeSummary.value = "";
    isEditing.value = false;
  },
  { immediate: true },
);

const previewHtml = computed(() => DOMPurify.sanitize(markdown.render(props.markdown || "")));
const markdownFromEditor = computed(() => turndown.turndown(richTextHtml.value || "").trim());
const dirty = computed(() => markdownFromEditor.value !== props.markdown.trim());
const modeLabel = computed(() => {
  if (props.readOnly) {
    return "版本预览";
  }
  return isEditing.value ? "编辑中" : "双击正文进入编辑";
});

function enterEditing() {
  if (!props.hasDocument || props.readOnly) {
    return;
  }
  isEditing.value = true;
}

function cancelEditing() {
  syncRichTextFromMarkdown();
  changeSummary.value = "";
  isEditing.value = false;
}

function saveDocument() {
  emit("save", {
    markdown: markdownFromEditor.value,
    changeSummary: changeSummary.value.trim() || undefined,
  });
}
</script>

<template>
  <section class="workspace-panel">
    <header class="workspace-panel__header">
      <div>
        <p class="workspace-panel__eyebrow">{{ sectionLabel }}</p>
        <h2>{{ title || "选择文档开始编辑" }}</h2>
      </div>

      <div v-if="hasDocument" class="workspace-panel__actions">
        <span class="workspace-panel__mode-pill" :class="{ 'is-editing': isEditing && !readOnly }">
          {{ modeLabel }}
        </span>

        <div v-if="!readOnly && isEditing" class="workspace-panel__save">
          <input
            v-model="changeSummary"
            type="text"
            maxlength="120"
            placeholder="填写版本说明（可选）"
          />
          <button class="ghost-button" type="button" :disabled="saving" @click="cancelEditing">
            退出编辑
          </button>
          <button class="primary-button" type="button" :disabled="saving || !dirty" @click="saveDocument">
            {{ saving ? "保存中..." : "保存为新版本" }}
          </button>
        </div>
      </div>
    </header>

    <div v-if="hasDocument" class="workspace-panel__body" :class="{ 'is-editor-only': isEditing && !readOnly }">
      <article
        v-if="readOnly || !isEditing"
        class="markdown-preview"
        :class="{ 'is-interactive': !readOnly }"
        @dblclick="enterEditing"
      >
        <div v-html="previewHtml" />
      </article>

      <div v-if="!readOnly && isEditing" class="rich-editor-shell">
        <QuillEditor
          v-model:content="richTextHtml"
          class="rich-editor"
          content-type="html"
          theme="snow"
          toolbar="full"
        />
      </div>
    </div>

    <div v-else class="workspace-panel__empty-state">
      <div class="workspace-panel__empty-card">
        <p class="workspace-panel__eyebrow">Ready</p>
        <h3>还没有打开文档</h3>
        <p>从左侧选择已有文档，或者先新建一份 Markdown / DOCX 文档再开始编辑。</p>
      </div>
    </div>
  </section>
</template>
