// Mirrors data-api/openapi.yaml (WLI-16). Keep in sync with the published contract.

export interface Account {
  id: string;
}

export type DocumentStatus = "uploaded" | "processing" | "ready" | "failed";

export interface DocumentRecord {
  id: string;
  originalFilename: string;
  byteSize: number;
  status: DocumentStatus;
  failureCode: string | null;
  createdAt: string;
}

export interface DocumentPage {
  items: DocumentRecord[];
  nextCursor: string | null;
}

export interface ChunkLocation {
  kind: "page" | "line";
  start: number;
  end: number;
}

export interface Chunk {
  id: string;
  documentId: string;
  location: ChunkLocation;
  text: string;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
}

export interface ConversationPage {
  items: Conversation[];
  nextCursor: string | null;
}

export type MessageRole = "user" | "assistant";
export type MessageStatus = "completed" | "failed";

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  createdAt: string;
}

export interface Citation {
  documentId: string;
  documentName: string;
  chunkId: string;
  location: ChunkLocation;
}

export type AnswerKind = "answered" | "no_documents" | "no_relevant_context";

export interface Answer {
  kind: AnswerKind;
  text: string;
  citations: Citation[];
}

export interface AskResponse {
  message: Message;
  answer: Answer;
}

export interface MessagePage {
  items: Message[];
  nextCursor: string | null;
}

export type ErrorCode =
  | "validation_error"
  | "unauthenticated"
  | "not_found"
  | "state_conflict"
  | "idempotency_conflict"
  | "file_too_large"
  | "unsupported_media_type"
  | "capacity_exhausted"
  | "model_unavailable"
  | "model_timeout";

export interface ApiErrorBody {
  error: {
    code: ErrorCode;
    message: string;
    requestId: string;
  };
}
