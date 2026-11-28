import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError, apiClient } from '../api/client';
import type { ChatMessage, Conversation, RunEvent } from '../api/client';

export function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [streaming, setStreaming] = useState(false);
  const stopStream = useRef<(() => void) | null>(null);
  const messageEnd = useRef<HTMLDivElement>(null);
  const language = typeof window !== 'undefined' && window.localStorage.getItem('i18nextLng') === 'ar' ? 'ar' : 'en';
  const labels = language === 'ar'
    ? { title: 'المحادثة', send: 'إرسال', placeholder: 'اكتب رسالتك…', new: 'محادثة جديدة' }
    : { title: 'Chat', send: 'Send', placeholder: 'Write a message…', new: 'New chat' };

  const loadMessages = useCallback(async (id: string) => {
    setLoading(true);
    setError('');
    try {
      const items = await apiClient.listMessages(id);
      setMessages(items);
    } catch (cause: unknown) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    async function initialize() {
      setLoading(true);
      try {
        const list = await apiClient.listConversations();
        if (!active) return;
        setConversations(list);
        if (list.length > 0) {
          setMessages([]);
          setConversationId(list[0].id);
        } else {
          const created = await apiClient.createConversation();
          if (!active) return;
          setConversations([created]);
          setConversationId(created.id);
          setMessages([]);
        }
      } catch (cause: unknown) {
        if (active) setError(errorMessage(cause));
      } finally {
        if (active) setLoading(false);
      }
    }
    void initialize();
    return () => { active = false; stopStream.current?.(); };
  }, []);

  useEffect(() => {
    if (conversationId) void loadMessages(conversationId);
  }, [conversationId, loadMessages]);

  useEffect(() => {
    messageEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  async function newConversation() {
    setError('');
    stopStream.current?.();
    try {
      const conversation = await apiClient.createConversation();
      setConversations((current) => [conversation, ...current]);
      setConversationId(conversation.id);
      setMessages([]);
    } catch (cause: unknown) {
      setError(errorMessage(cause));
    }
  }

  async function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || sending || !conversationId) return;
    setDraft('');
    setError('');
    setSending(true);
    setStreaming(true);
    const optimistic: ChatMessage = { id: `pending-${Date.now()}`, role: 'user', content };
    setMessages((current) => [...current, optimistic]);
    try {
      const sent = await apiClient.sendMessage(conversationId, content);
      setMessages((current) => current.map((message) => message.id === optimistic.id ? sent : message));
      if (sent.run_id) {
        stopStream.current?.();
        stopStream.current = apiClient.subscribeToRun(sent.run_id, (event) => applyRunEvent(event), () => {
          setStreaming(false);
          setError('The live response connection was interrupted. Refresh the conversation to see saved messages.');
        });
      } else {
        setStreaming(false);
      }
    } catch (cause: unknown) {
      setMessages((current) => current.filter((message) => message.id !== optimistic.id));
      setDraft(content);
      setStreaming(false);
      setError(errorMessage(cause));
    } finally {
      setSending(false);
    }
  }

  function applyRunEvent(event: RunEvent) {
    const text = event.content ?? event.message ?? (typeof event.data?.content === 'string' ? event.data.content : '');
    if (event.event_type === 'agent.stream' || event.event_type === 'agent.message' || event.event_type === 'run.completed') {
      if (text) {
        setMessages((current) => {
          const index = current.findIndex((message) => message.id === `stream-${event.run_id ?? 'active'}`);
          const streamed: ChatMessage = { id: `stream-${event.run_id ?? 'active'}`, role: 'assistant', content: text };
          if (index < 0) return [...current, streamed];
          return current.map((message, position) => position === index ? { ...message, content: message.content + text } : message);
        });
      }
    }
    if (event.event_type === 'run.completed' || event.event_type === 'run.failed' || event.event_type === 'run.cancelled') {
      setStreaming(false);
      stopStream.current?.();
      stopStream.current = null;
    }
  }

  return (
    <main className="chat-page" aria-labelledby="chat-heading">
      <aside className="conversation-sidebar" aria-label="Conversations">
        <button type="button" className="new-chat-button" onClick={() => void newConversation()}>{labels.new}</button>
        <ul>
          {conversations.map((conversation) => (
            <li key={conversation.id}>
              <button type="button" className={conversation.id === conversationId ? 'conversation-active' : ''}
                onClick={() => setConversationId(conversation.id)}>
                {conversation.title || 'New conversation'}
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <section className="chat-content">
        <header className="chat-header">
          <div><p className="eyebrow">Workspace</p><h1 id="chat-heading" data-testid="chat-heading">{labels.title}</h1></div>
          {streaming && <span data-testid="streaming-indicator" className="streaming-status" role="status">Generating…</span>}
        </header>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="message-list" aria-live="polite" aria-busy={loading}>
          {loading && <p role="status">Loading conversation…</p>}
          {!loading && messages.length === 0 && <p className="empty-chat">Start a conversation by sending a message.</p>}
          {messages.map((message) => (
            <article key={message.id} data-testid={message.role === 'assistant' ? 'assistant-message' : 'chat-message'}
              className={`message message-${message.role}`}>
              <strong>{message.role === 'assistant' ? 'Agent' : message.role === 'user' ? 'You' : message.role}</strong>
              <p dir="auto">{message.content}</p>
            </article>
          ))}
          <div ref={messageEnd} />
        </div>
        <form className="composer" onSubmit={submitMessage}>
          <label className="sr-only" htmlFor="message-input">{labels.placeholder}</label>
          <textarea id="message-input" data-testid="message-input" value={draft} onChange={(event) => setDraft(event.target.value)}
            placeholder={labels.placeholder} rows={2} disabled={sending} />
          <button data-testid="send-button" type="submit" disabled={sending || !draft.trim()}>{labels.send}</button>
        </form>
      </section>
    </main>
  );
}

function errorMessage(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : 'Unable to load the conversation. Please try again.';
}
