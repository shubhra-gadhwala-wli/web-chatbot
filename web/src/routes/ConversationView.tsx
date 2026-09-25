import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { CitationChip, groupCitations } from "../components/CitationChip";
import { useSpeechRecognition, isSpeechRecognitionSupported } from "../hooks/useSpeechRecognition";
import type { AnswerKind, Citation, Conversation, Message } from "../api/types";
import "./ConversationView.css";

const ttsSupported = "speechSynthesis" in window;

interface PendingTurn {
  userMessageId: string;
  text: string;
}

interface FailedTurn {
  text: string;
  kind: "error" | "busy";
  retryAfter: number | null;
}

function speak(text: string) {
  if (!ttsSupported) return;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

export function ConversationView() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();
  const [conversation, setConversation] = useState<Conversation | null | "not_found">(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [answersByMessageId, setAnswersByMessageId] = useState<Record<string, { kind: AnswerKind; citations: Citation[] }>>({});
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<PendingTurn | null>(null);
  const [failedTurn, setFailedTurn] = useState<FailedTurn | null>(null);
  const [voiceUnsupportedDismissed, setVoiceUnsupportedDismissed] = useState(false);
  const [ttsOn, setTtsOn] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const onTranscript = useCallback((text: string, _isFinal: boolean) => {
    setInput(text);
  }, []);
  const { listening, errorMessage: micError, start: startMic, stop: stopMic } =
    useSpeechRecognition(onTranscript);

  useEffect(() => {
    if (!conversationId) return;
    let cancelled = false;
    api
      .getConversation(conversationId)
      .then((c) => {
        if (cancelled) return;
        setConversation(c);
        return api.listMessages(conversationId);
      })
      .then((page) => {
        if (cancelled || !page) return;
        setMessages(page.items);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setConversation("not_found");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, pending, failedTurn]);

  async function submit(text: string) {
    if (!conversationId || !text.trim() || pending) return;
    setInput("");
    setFailedTurn(null);
    const optimisticId = `optimistic-${crypto.randomUUID()}`;
    setMessages((prev) => [
      ...prev,
      { id: optimisticId, role: "user", content: text, status: "completed", createdAt: new Date().toISOString() },
    ]);
    setPending({ userMessageId: optimisticId, text });
    try {
      const result = await api.ask(conversationId, text);
      // AskResponse.message is the assistant's reply; the optimistic user
      // bubble (already rendered) is left as-is rather than replaced.
      setMessages((prev) => [...prev, result.message]);
      setAnswersByMessageId((prev) => ({
        ...prev,
        [result.message.id]: { kind: result.answer.kind, citations: result.answer.citations },
      }));
      if (ttsOn && result.answer.kind === "answered") {
        speak(result.answer.text);
      }
    } catch (err) {
      if (err instanceof ApiError && (err.status === 502 || err.status === 504)) {
        setFailedTurn({ text, kind: "error", retryAfter: null });
      } else if (err instanceof ApiError && err.status === 429) {
        setFailedTurn({ text, kind: "busy", retryAfter: err.retryAfter });
      } else {
        setFailedTurn({ text, kind: "error", retryAfter: null });
      }
    } finally {
      setPending(null);
    }
  }

  if (conversation === "not_found") {
    return (
      <div className="conversation-view__not-found">
        <p>This conversation couldn&apos;t be found.</p>
        <Link to="/conversations">Back to chats</Link>
      </div>
    );
  }

  const showVoiceNotice =
    !voiceUnsupportedDismissed && !isSpeechRecognitionSupported() && !ttsSupported;

  return (
    <div className="conversation-view">
      <header className="conversation-view__header">
        <button type="button" className="conversation-view__back" onClick={() => navigate("/conversations")} aria-label="Back to chats">
          ‹
        </button>
        <h1 className="conversation-view__title">{conversation === null ? "Loading…" : conversation.title}</h1>
        {ttsSupported ? (
          <label className="conversation-view__voice-toggle">
            <input type="checkbox" checked={ttsOn} onChange={(e) => setTtsOn(e.target.checked)} />
            Voice replies: {ttsOn ? "On" : "Off"}
          </label>
        ) : null}
      </header>

      <div className="conversation-view__list" ref={listRef}>
        {messages.length === 0 && !pending ? (
          <p className="conversation-view__hint">Ask a question about your documents to get started.</p>
        ) : null}
        {messages.map((m) => {
          const answer = answersByMessageId[m.id];
          if (m.role === "user") {
            return (
              <div key={m.id} className="bubble bubble--user">
                {m.content}
              </div>
            );
          }
          if (answer && answer.kind !== "answered") {
            return (
              <div key={m.id} className="bubble bubble--assistant bubble--info">
                <p>{m.content}</p>
                {answer.kind === "no_documents" ? (
                  <Link to="/documents" className="bubble__cta">
                    Upload a document
                  </Link>
                ) : null}
              </div>
            );
          }
          return (
            <div key={m.id} className="bubble bubble--assistant">
              <p>{m.content}</p>
              {answer && answer.citations.length > 0 ? (
                <div className="bubble__citations">
                  {groupCitations(answer.citations).map((g) => (
                    <CitationChip key={g.documentId} group={g} />
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
        {pending ? (
          <div className="bubble bubble--assistant bubble--pending" aria-live="polite">
            <span className="typing-indicator" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            <span className="typing-indicator__fallback">Thinking…</span>
          </div>
        ) : null}
        {failedTurn ? (
          <div className="bubble bubble--assistant bubble--error" role="alert">
            {failedTurn.kind === "error" ? (
              <>
                <p>Couldn&apos;t generate a response — try again.</p>
                <button type="button" className="bubble__cta" onClick={() => void submit(failedTurn.text)}>
                  Retry
                </button>
              </>
            ) : (
              <RetryCountdown
                seconds={failedTurn.retryAfter ?? 5}
                onRetry={() => void submit(failedTurn.text)}
              />
            )}
          </div>
        ) : null}
      </div>

      {showVoiceNotice ? (
        <p className="conversation-view__voice-notice">
          Voice input isn&apos;t available in this browser — try Chrome.{" "}
          <button type="button" onClick={() => setVoiceUnsupportedDismissed(true)}>
            Dismiss
          </button>
        </p>
      ) : null}
      {micError ? (
        <p className="conversation-view__mic-error" role="alert">
          {micError}
        </p>
      ) : null}

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void submit(input);
        }}
      >
        {isSpeechRecognitionSupported() ? (
          <button
            type="button"
            className={`composer__mic ${listening ? "composer__mic--listening" : ""}`}
            aria-label={listening ? "Stop voice input" : "Start voice input"}
            onClick={() => (listening ? stopMic() : startMic())}
          >
            🎤
          </button>
        ) : null}
        <textarea
          className="composer__input"
          rows={1}
          value={input}
          placeholder="Ask a question…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit(input);
            }
          }}
          disabled={pending !== null}
        />
        <button
          type="submit"
          className="composer__send"
          aria-label="Send"
          disabled={pending !== null || input.trim().length === 0}
        >
          ➤
        </button>
      </form>
    </div>
  );
}

function RetryCountdown({ seconds, onRetry }: { seconds: number; onRetry: () => void }) {
  const [remaining, setRemaining] = useState(seconds);
  useEffect(() => {
    if (remaining <= 0) return;
    const t = setTimeout(() => setRemaining((r) => r - 1), 1000);
    return () => clearTimeout(t);
  }, [remaining]);
  return (
    <>
      <p>The assistant is busy right now — try again in a moment.</p>
      <button type="button" className="bubble__cta" onClick={onRetry} disabled={remaining > 0}>
        {remaining > 0 ? `Retry in ${remaining}s` : "Retry"}
      </button>
    </>
  );
}
