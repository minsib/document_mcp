import { computed, reactive, ref } from "vue";
import { defineStore } from "pinia";

import { api } from "../lib/api";
import type {
  ChatEditResponse,
  ChatSessionMessage,
  ConfirmResponse,
  DocumentListItem,
  RevisionItem,
  UiChatMessage,
} from "../lib/types";
import { useAuthStore } from "./auth";

function isoNow() {
  return new Date().toISOString();
}

function createUiMessage(message: Partial<UiChatMessage> & Pick<UiChatMessage, "role" | "content">): UiChatMessage {
  return {
    id: crypto.randomUUID(),
    createdAt: isoNow(),
    ...message,
  };
}

function mapAssistantResponse(response: ChatEditResponse, sourceMessage: string): UiChatMessage {
  return createUiMessage({
    role: "assistant",
    content: response.message,
    status: response.status,
    preview: response.preview || undefined,
    candidates: response.candidates || undefined,
    clarification: response.clarification || undefined,
    confirmToken: response.confirm_token,
    previewHash: response.preview_hash,
    sourceMessage,
  });
}

function mapSessionMessage(message: ChatSessionMessage): UiChatMessage {
  const meta = message.meta || {};
  return {
    id: message.msg_id,
    role: message.role === "assistant" ? "assistant" : "user",
    content: message.content,
    createdAt: message.created_at,
    status: typeof meta.status === "string" ? (meta.status as UiChatMessage["status"]) : undefined,
    preview: meta.preview as UiChatMessage["preview"],
    candidates: meta.candidates as UiChatMessage["candidates"],
    clarification: meta.clarification as UiChatMessage["clarification"],
    confirmToken: typeof meta.confirm_token === "string" ? meta.confirm_token : undefined,
    previewHash: typeof meta.preview_hash === "string" ? meta.preview_hash : undefined,
  };
}

export const useWorkspaceStore = defineStore("workspace", () => {
  const auth = useAuthStore();

  const documents = ref<DocumentListItem[]>([]);
  const selectedDocumentId = ref<string | null>(null);
  const currentMarkdown = ref("");
  const currentRevisionId = ref<string | null>(null);
  const revisions = ref<RevisionItem[]>([]);
  const chatSessionsByDoc = ref<Record<string, string>>({});
  const chatMessagesByDoc = ref<Record<string, UiChatMessage[]>>({});
  const searchQuery = ref("");
  const notices = ref<string[]>([]);

  const pending = reactive({
    documents: false,
    create: false,
    content: false,
    save: false,
    revisions: false,
    chat: false,
    rollback: false,
  });

  const errors = reactive({
    documents: "",
    create: "",
    content: "",
    save: "",
    revisions: "",
    chat: "",
    rollback: "",
  });

  const selectedDocument = computed(() =>
    documents.value.find((item) => item.doc_id === selectedDocumentId.value) || null,
  );

  const currentChatMessages = computed(() =>
    selectedDocumentId.value ? chatMessagesByDoc.value[selectedDocumentId.value] || [] : [],
  );

  function syncApiToken() {
    api.setAccessToken(auth.accessToken);
  }

  function pushNotice(message: string) {
    notices.value = [message, ...notices.value].slice(0, 3);
  }

  function setDocumentMessages(docId: string, messages: UiChatMessage[]) {
    chatMessagesByDoc.value = {
      ...chatMessagesByDoc.value,
      [docId]: messages,
    };
  }

  function appendMessage(docId: string, message: UiChatMessage) {
    setDocumentMessages(docId, [...(chatMessagesByDoc.value[docId] || []), message]);
  }

  async function loadDocuments(query = searchQuery.value) {
    syncApiToken();
    pending.documents = true;
    errors.documents = "";
    searchQuery.value = query;
    try {
      const response = await api.listDocuments(query);
      documents.value = response.documents;
      if (!selectedDocumentId.value && response.documents.length) {
        selectedDocumentId.value = response.documents[0].doc_id;
      }
      return response.documents;
    } catch (err) {
      errors.documents = err instanceof Error ? err.message : "加载文档失败";
      throw err;
    } finally {
      pending.documents = false;
    }
  }

  async function loadDocument(docId: string, revId?: string | null) {
    syncApiToken();
    pending.content = true;
    errors.content = "";
    try {
      const response = await api.exportDocument(docId, revId);
      selectedDocumentId.value = docId;
      currentMarkdown.value = response.content;
      currentRevisionId.value = response.rev_id;
      return response;
    } catch (err) {
      errors.content = err instanceof Error ? err.message : "加载文档内容失败";
      throw err;
    } finally {
      pending.content = false;
    }
  }

  async function loadRevisions(docId: string) {
    syncApiToken();
    pending.revisions = true;
    errors.revisions = "";
    try {
      const response = await api.listRevisions(docId);
      revisions.value = response.revisions;
      const activeRevision = response.revisions.find((item) => item.is_active);
      documents.value = documents.value.map((document) =>
        document.doc_id === docId
          ? {
              ...document,
              active_rev_id: activeRevision?.rev_id || document.active_rev_id,
            }
          : document,
      );
      return response.revisions;
    } catch (err) {
      errors.revisions = err instanceof Error ? err.message : "加载版本失败";
      throw err;
    } finally {
      pending.revisions = false;
    }
  }

  async function hydrateChatHistory(docId: string) {
    syncApiToken();
    const sessionId = chatSessionsByDoc.value[docId];
    if (!sessionId) {
      return;
    }
    try {
      const session = await api.getChatSession(sessionId);
      setDocumentMessages(
        docId,
        session.messages.map(mapSessionMessage),
      );
    } catch (err) {
      // Session history is useful but not critical for the workspace.
    }
  }

  async function selectDocument(docId: string, revId?: string | null) {
    await Promise.all([loadDocument(docId, revId), loadRevisions(docId)]);
    await hydrateChatHistory(docId);
  }

  async function createDocument(payload: { title: string; content?: string; file?: File | null }) {
    syncApiToken();
    pending.create = true;
    errors.create = "";
    try {
      const response = await api.uploadDocument(payload);
      await loadDocuments();
      await selectDocument(response.doc_id);
      pushNotice(`已创建文档《${response.title}》`);
      return response;
    } catch (err) {
      errors.create = err instanceof Error ? err.message : "创建文档失败";
      pushNotice(errors.create);
      return null;
    } finally {
      pending.create = false;
    }
  }

  async function saveCurrentDocument(markdown: string, changeSummary?: string) {
    if (!selectedDocumentId.value) {
      return;
    }

    syncApiToken();
    pending.save = true;
    errors.save = "";
    try {
      const response = await api.updateDocumentContent(selectedDocumentId.value, {
        content: markdown,
        change_summary: changeSummary,
      });
      currentMarkdown.value = markdown;
      currentRevisionId.value = response.rev_id;
      await Promise.all([loadDocuments(), loadRevisions(selectedDocumentId.value)]);
      pushNotice(response.message);
      return response;
    } catch (err) {
      errors.save = err instanceof Error ? err.message : "保存文档失败";
      throw err;
    } finally {
      pending.save = false;
    }
  }

  async function rollbackRevision(revision: RevisionItem) {
    if (!selectedDocumentId.value) {
      return;
    }

    syncApiToken();
    pending.rollback = true;
    errors.rollback = "";
    try {
      const response = await api.rollbackRevision(selectedDocumentId.value, {
        target_rev_id: revision.rev_id,
        target_rev_no: revision.rev_no,
      });
      await selectDocument(selectedDocumentId.value);
      pushNotice(response.message);
      return response;
    } catch (err) {
      errors.rollback = err instanceof Error ? err.message : "回滚失败";
      throw err;
    } finally {
      pending.rollback = false;
    }
  }

  async function sendChatMessage(message: string, userSelection?: string, skipEcho = false) {
    if (!selectedDocumentId.value) {
      return;
    }

    syncApiToken();
    const docId = selectedDocumentId.value;
    const sessionId = chatSessionsByDoc.value[docId] || crypto.randomUUID();
    pending.chat = true;
    errors.chat = "";

    if (!skipEcho) {
      appendMessage(
        docId,
        createUiMessage({
          role: "user",
          content: message,
        }),
      );
    }

    try {
      const response = await api.chatEdit({
        doc_id: docId,
        session_id: sessionId,
        message,
        user_selection: userSelection,
      });

      chatSessionsByDoc.value = {
        ...chatSessionsByDoc.value,
        [docId]: response.session_id || sessionId,
      };

      appendMessage(docId, mapAssistantResponse(response, message));

      if (response.status === "applied" && response.export_md) {
        currentMarkdown.value = response.export_md;
        currentRevisionId.value = response.new_rev_id || currentRevisionId.value;
        await Promise.all([loadDocuments(), loadRevisions(docId)]);
      }

      return response;
    } catch (err) {
      errors.chat = err instanceof Error ? err.message : "发送消息失败";
      appendMessage(
        docId,
        createUiMessage({
          role: "system",
          content: errors.chat,
        }),
      );
      throw err;
    } finally {
      pending.chat = false;
    }
  }

  async function resolveCandidateSelection(blockId: string, sourceMessage: string) {
    if (!selectedDocumentId.value) {
      return;
    }

    appendMessage(
      selectedDocumentId.value,
      createUiMessage({
        role: "system",
        content: "已选择候选段落，继续执行定位。",
      }),
    );
    return sendChatMessage(sourceMessage, blockId, true);
  }

  async function respondToConfirmation(message: UiChatMessage, action: "apply" | "cancel") {
    if (!selectedDocumentId.value) {
      return;
    }
    if (!message.confirmToken || !message.previewHash) {
      return;
    }

    syncApiToken();
    const docId = selectedDocumentId.value;
    const sessionId = chatSessionsByDoc.value[docId];
    if (!sessionId) {
      return;
    }

    pending.chat = true;
    errors.chat = "";
    try {
      const response: ConfirmResponse = await api.confirmEdit({
        session_id: sessionId,
        doc_id: docId,
        confirm_token: message.confirmToken,
        preview_hash: message.previewHash,
        action,
      });

      appendMessage(
        docId,
        createUiMessage({
          role: "assistant",
          content: response.message,
          status: response.status,
        }),
      );

      if (response.status === "applied" && response.export_md) {
        currentMarkdown.value = response.export_md;
        currentRevisionId.value = response.new_rev_id || currentRevisionId.value;
        await Promise.all([loadDocuments(), loadRevisions(docId)]);
      }

      if (response.status === "cancelled") {
        pushNotice("已取消本次修改");
      }

      return response;
    } catch (err) {
      errors.chat = err instanceof Error ? err.message : "确认修改失败";
      throw err;
    } finally {
      pending.chat = false;
    }
  }

  function resetWorkspace() {
    documents.value = [];
    selectedDocumentId.value = null;
    currentMarkdown.value = "";
    currentRevisionId.value = null;
    revisions.value = [];
    chatSessionsByDoc.value = {};
    chatMessagesByDoc.value = {};
    searchQuery.value = "";
    notices.value = [];
  }

  return {
    documents,
    selectedDocumentId,
    selectedDocument,
    currentMarkdown,
    currentRevisionId,
    revisions,
    currentChatMessages,
    searchQuery,
    notices,
    pending,
    errors,
    loadDocuments,
    loadDocument,
    loadRevisions,
    selectDocument,
    createDocument,
    saveCurrentDocument,
    rollbackRevision,
    sendChatMessage,
    resolveCandidateSelection,
    respondToConfirmation,
    resetWorkspace,
  };
});
