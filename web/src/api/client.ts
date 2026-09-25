import type {
  Account,
  ApiErrorBody,
  AskResponse,
  Chunk,
  Conversation,
  ConversationPage,
  DocumentPage,
  DocumentRecord,
  MessagePage,
} from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  code: ApiErrorBody["error"]["code"];
  requestId: string;
  status: number;
  retryAfter: number | null;

  constructor(status: number, body: ApiErrorBody, retryAfter: number | null) {
    super(body.error.message);
    this.code = body.error.code;
    this.requestId = body.error.requestId;
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

// Same-origin credentialed requests only (R6): relative URLs, no cross-origin
// fetch target is ever constructed from user or server input.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    credentials: "same-origin",
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : null;

  if (!response.ok) {
    const retryAfterHeader = response.headers.get("Retry-After");
    const retryAfter = retryAfterHeader ? Number.parseInt(retryAfterHeader, 10) : null;
    if (payload && typeof payload === "object" && "error" in payload) {
      throw new ApiError(response.status, payload as ApiErrorBody, retryAfter);
    }
    throw new ApiError(
      response.status,
      { error: { code: "validation_error", message: "Request failed", requestId: "unknown" } },
      retryAfter,
    );
  }

  return payload as T;
}

function randomKey(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

export const api = {
  register: (email: string, password: string) =>
    request<Account>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  login: (email: string, password: string) =>
    request<Account>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  logout: () => request<void>("/auth/logout", { method: "POST" }),

  me: () => request<Account>("/auth/me"),

  listDocuments: (cursor?: string) =>
    request<DocumentPage>(`/documents${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`),

  uploadDocument: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentRecord>("/documents", {
      method: "POST",
      body: form,
      headers: { "Idempotency-Key": randomKey() },
    });
  },

  getDocument: (documentId: string) => request<DocumentRecord>(`/documents/${documentId}`),

  deleteDocument: (documentId: string) =>
    request<void>(`/documents/${documentId}`, { method: "DELETE" }),

  getChunk: (documentId: string, chunkId: string) =>
    request<Chunk>(`/documents/${documentId}/chunks/${chunkId}`),

  listConversations: (cursor?: string) =>
    request<ConversationPage>(
      `/conversations${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
    ),

  createConversation: (title: string) =>
    request<Conversation>("/conversations", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),

  getConversation: (conversationId: string) =>
    request<Conversation>(`/conversations/${conversationId}`),

  renameConversation: (conversationId: string, title: string) =>
    request<Conversation>(`/conversations/${conversationId}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  listMessages: (conversationId: string, cursor?: string) =>
    request<MessagePage>(
      `/conversations/${conversationId}/messages${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
    ),

  ask: (conversationId: string, text: string) =>
    request<AskResponse>(`/conversations/${conversationId}/messages`, {
      method: "POST",
      body: JSON.stringify({ text, clientRequestId: randomKey() }),
    }),
};
