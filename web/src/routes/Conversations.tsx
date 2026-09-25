import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import type { Conversation } from "../api/types";
import "./Conversations.css";

export function Conversations() {
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.listConversations().then((page) => {
      if (!cancelled) setConversations(page.items);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function startChat() {
    setCreating(true);
    try {
      const conversation = await api.createConversation("New chat");
      navigate(`/conversations/${conversation.id}`);
    } finally {
      setCreating(false);
    }
  }

  const isEmpty = conversations !== null && conversations.length === 0;

  return (
    <div>
      <div className="conversations__header">
        <h1 className="conversations__title">Chats</h1>
        <Button onClick={() => void startChat()} loading={creating}>
          New chat
        </Button>
      </div>

      {conversations === null ? (
        <div className="documents__skeleton" aria-busy="true" aria-label="Loading conversations">
          {[0, 1, 2].map((i) => (
            <div key={i} className="documents__skeleton-row" />
          ))}
        </div>
      ) : isEmpty ? (
        <EmptyState
          icon="💬"
          title="No conversations yet"
          body="Start a chat to ask grounded questions about your documents."
          action={
            <Button onClick={() => void startChat()} loading={creating}>
              Start a chat
            </Button>
          }
        />
      ) : (
        <ul className="conversations__list">
          {conversations.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className="conversations__row"
                onClick={() => navigate(`/conversations/${c.id}`)}
              >
                <span className="conversations__name">{c.title}</span>
                <span className="conversations__updated">
                  {new Date(c.updatedAt).toLocaleString()}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
