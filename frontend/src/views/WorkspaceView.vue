<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import ActivitySidebar from "../components/ActivitySidebar.vue";
import ChatPanel from "../components/ChatPanel.vue";
import DocumentSidebar from "../components/DocumentSidebar.vue";
import VersionSidebar from "../components/VersionSidebar.vue";
import XMarkdownWorkspace from "../components/XMarkdownWorkspace.vue";
import { useAuthStore } from "../stores/auth";
import { useUiStore } from "../stores/ui";
import { useWorkspaceStore } from "../stores/workspace";
import type { RevisionItem, UiChatMessage } from "../lib/types";

const router = useRouter();
const auth = useAuthStore();
const ui = useUiStore();
const workspace = useWorkspaceStore();

const activeSection = ref<"documents" | "versions">("documents");

const selectedDocumentTitle = computed(
  () => workspace.selectedDocument?.title || "未选择文档",
);
const hasSelectedDocument = computed(() => Boolean(workspace.selectedDocumentId));
const syncKey = computed(
  () => `${workspace.selectedDocumentId || "none"}:${workspace.currentRevisionId || "none"}`,
);
const editorReadOnly = computed(() => activeSection.value === "versions");
const chatDisabled = computed(() => !workspace.selectedDocumentId || activeSection.value === "versions");

async function bootstrapWorkspace() {
  if (!auth.isAuthenticated) {
    return;
  }

  const documents = await workspace.loadDocuments();
  if (workspace.selectedDocumentId) {
    await workspace.selectDocument(workspace.selectedDocumentId);
  } else if (documents.length) {
    await workspace.selectDocument(documents[0].doc_id);
  }
}

onMounted(() => {
  bootstrapWorkspace();
});

watch(
  () => auth.isAuthenticated,
  (authenticated) => {
    if (authenticated) {
      bootstrapWorkspace();
    } else {
      workspace.resetWorkspace();
    }
  },
);

async function logout() {
  auth.logout();
  workspace.resetWorkspace();
  await router.push("/auth");
}

function openDocument(docId: string) {
  activeSection.value = "documents";
  workspace.selectDocument(docId);
}

function openRevisionDocument(docId: string) {
  workspace.selectDocument(docId);
}

function previewRevision(revId: string | null) {
  if (!workspace.selectedDocumentId) {
    return;
  }
  workspace.loadDocument(workspace.selectedDocumentId, revId);
}

function rollbackRevision(revision: RevisionItem) {
  workspace.rollbackRevision(revision);
}

function handleCandidateSelection(payload: { blockId: string; sourceMessage: string }) {
  workspace.resolveCandidateSelection(payload.blockId, payload.sourceMessage);
}

function handleConfirm(payload: { message: UiChatMessage; action: "apply" | "cancel" }) {
  workspace.respondToConfirmation(payload.message, payload.action);
}
</script>

<template>
  <main class="workspace-shell">
    <ActivitySidebar
      :active-section="activeSection"
      :theme="ui.theme"
      :user="auth.user"
      @select-section="activeSection = $event"
      @toggle-theme="ui.toggleTheme"
      @logout="logout"
    />

    <DocumentSidebar
      v-if="activeSection === 'documents'"
      :documents="workspace.documents"
      :selected-document-id="workspace.selectedDocumentId"
      :loading="workspace.pending.documents"
      :creating="workspace.pending.create"
      :create-error="workspace.errors.create"
      :search-query="workspace.searchQuery"
      @select-document="openDocument"
      @refresh-documents="workspace.loadDocuments()"
      @search-documents="workspace.loadDocuments($event)"
      @create-document="workspace.createDocument($event)"
    />

    <VersionSidebar
      v-else
      :documents="workspace.documents"
      :selected-document-id="workspace.selectedDocumentId"
      :revisions="workspace.revisions"
      :loading="workspace.pending.revisions"
      :rollbacking="workspace.pending.rollback"
      @select-document="openRevisionDocument"
      @preview-revision="previewRevision"
      @rollback-revision="rollbackRevision"
      @refresh-revisions="workspace.selectedDocumentId && workspace.loadRevisions(workspace.selectedDocumentId)"
    />

    <section class="workspace-main">
      <div v-if="workspace.notices.length" class="notice-stack">
        <div v-for="notice in workspace.notices" :key="notice" class="notice-card">
          {{ notice }}
        </div>
      </div>

      <XMarkdownWorkspace
        :title="selectedDocumentTitle"
        :markdown="workspace.currentMarkdown"
        :sync-key="syncKey"
        :has-document="hasSelectedDocument"
        :read-only="editorReadOnly"
        :saving="workspace.pending.save"
        :section-label="activeSection === 'documents' ? 'Document Management' : 'Revision Browser'"
        @save="workspace.saveCurrentDocument($event.markdown, $event.changeSummary)"
      />

      <ChatPanel
        :messages="workspace.currentChatMessages"
        :busy="workspace.pending.chat"
        :disabled="chatDisabled"
        :document-title="selectedDocumentTitle"
        @send="workspace.sendChatMessage($event)"
        @select-candidate="handleCandidateSelection"
        @confirm="handleConfirm"
      />
    </section>
  </main>
</template>
