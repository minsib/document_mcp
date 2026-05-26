<script setup lang="ts">
import type { DocumentListItem, RevisionItem } from "../lib/types";

defineProps<{
  documents: DocumentListItem[];
  selectedDocumentId: string | null;
  revisions: RevisionItem[];
  loading: boolean;
  rollbacking: boolean;
}>();

const emit = defineEmits<{
  (event: "select-document", docId: string): void;
  (event: "preview-revision", revId: string | null): void;
  (event: "rollback-revision", revision: RevisionItem): void;
  (event: "refresh-revisions"): void;
}>();

function formatRevisionMeta(revision: RevisionItem) {
  const tag = revision.is_active ? "当前版本" : `历史版本 #${revision.rev_no}`;
  return `${tag} · ${new Date(revision.created_at).toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}
</script>

<template>
  <section class="sidebar-panel">
    <header class="sidebar-panel__header">
      <div>
        <p class="sidebar-panel__eyebrow">Timeline</p>
        <h2>版本管理</h2>
      </div>
      <button class="ghost-button" type="button" @click="emit('refresh-revisions')">刷新</button>
    </header>

    <div class="sidebar-panel__toolbar is-stacked">
      <label class="inline-field">
        <span>文档</span>
        <select
          :value="selectedDocumentId || ''"
          @change="emit('select-document', ($event.target as HTMLSelectElement).value)"
        >
          <option disabled value="">请选择文档</option>
          <option v-for="document in documents" :key="document.doc_id" :value="document.doc_id">
            {{ document.title }}
          </option>
        </select>
      </label>
      <button class="ghost-button is-wide" type="button" @click="emit('preview-revision', null)">
        查看当前活跃版本
      </button>
    </div>

    <div class="sidebar-panel__list">
      <article
        v-for="revision in revisions"
        :key="revision.rev_id"
        class="revision-row"
      >
        <button
          class="revision-row__preview"
          type="button"
          @click="emit('preview-revision', revision.rev_id)"
        >
          <div class="revision-row__content">
            <strong>版本 {{ revision.rev_no }}</strong>
            <span>{{ formatRevisionMeta(revision) }}</span>
            <small>{{ revision.change_summary || "无变更说明" }}</small>
          </div>
        </button>
        <button
          v-if="!revision.is_active"
          class="ghost-button"
          type="button"
          :disabled="rollbacking"
          @click="emit('rollback-revision', revision)"
        >
          回滚
        </button>
      </article>

      <div v-if="!revisions.length && !loading" class="sidebar-panel__empty">
        先在文档管理中创建或选中文档，再查看版本历史。
      </div>
    </div>
  </section>
</template>
