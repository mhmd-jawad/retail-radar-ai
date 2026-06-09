import { useState, useRef, useEffect, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import {
  Bot, Send, Zap, Loader2, RefreshCw, ChevronRight,
  AlertTriangle, Boxes, ListChecks, TrendingUp, Users, Target,
  Plus, MessageSquare, Clock,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/store/auth';
import { useChatStore } from '@/store/chat';
import type { ChatSession, StoredMessage } from '@/store/chat';
import { toast } from 'sonner';

// ── Types ─────────────────────────────────────────────────────────────────────

type Role = 'user' | 'assistant';

interface Message {
  id: string;
  role: Role;
  content: string;
  tools?: string[];
  timestamp: Date;
  error?: boolean;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const ASSISTANT_BASE =
  (import.meta.env.VITE_ASSISTANT_URL as string | undefined) ??
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  (import.meta.env.PROD ? '' : 'http://localhost:8000');

async function assistantErrorMessage(res: Response): Promise<string> {
  let detail = '';
  try {
    const payload = await res.json();
    detail = typeof payload?.detail === 'string' ? payload.detail : JSON.stringify(payload);
  } catch {
    detail = await res.text().catch(() => '');
  }
  if (res.status === 401 || res.status === 403) {
    return 'Your dashboard session is not authorized for Radar Assistant. Log in again.';
  }
  if (res.status === 503) {
    return `Radar Assistant service is not ready${detail ? `: ${detail}` : ''}`;
  }
  if (res.status >= 500) {
    return `Radar Assistant backend failed${detail ? `: ${detail}` : ''}`;
  }
  return detail || `Radar Assistant request failed with HTTP ${res.status}`;
}

function randomId() {
  try {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  } catch {
    // fall through for non-secure origins
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function relativeTime(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days}d ago`;
  return new Date(isoStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

const TOOL_LABELS: Record<string, string> = {
  get_inventory_overview: 'Inventory',
  get_stockout_days: 'Stockouts',
  get_reorder_suggestions: 'Reorder',
  get_sku_velocity_trend: 'Velocity',
  get_category_performance: 'Categories',
  get_competitor_prices: 'Competitors',
  get_pending_recommendations: 'Recommendations',
  approve_recommendation: 'Approved ✓',
  reject_recommendation: 'Rejected',
  get_roadmap_summary: 'Roadmap',
  get_next_actions: 'Next actions',
  get_financial_health: 'Financials',
};

const QUICK_PROMPTS: { label: string; prompt: string; icon: React.ElementType }[] = [
  { label: 'Inventory status', prompt: 'How is my inventory right now?', icon: Boxes },
  { label: 'Pending decisions', prompt: 'Show me pending recommendations', icon: ListChecks },
  { label: "Today's focus", prompt: 'What should I focus on today?', icon: Target },
  { label: 'Competitor prices', prompt: 'What are competitors charging?', icon: Users },
  { label: 'Sales trend', prompt: 'Are sales up this week?', icon: TrendingUp },
];

// ── Markdown renderer ─────────────────────────────────────────────────────────

function renderContent(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const regex = /\*([^*\n]+)\*/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex)
      parts.push(<span key={key++}>{text.slice(lastIndex, match.index)}</span>);
    parts.push(<strong key={key++} className="font-semibold text-foreground">{match[1]}</strong>);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length)
    parts.push(<span key={key++}>{text.slice(lastIndex)}</span>);
  return <>{parts}</>;
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user';
  const time = msg.timestamp.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  const uniqueTools = msg.tools ? [...new Set(msg.tools)] : [];

  return (
    <div className={cn('flex gap-3 animate-fade-in', isUser ? 'flex-row-reverse' : 'flex-row')}>
      {!isUser && (
        <div className="shrink-0 h-8 w-8 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center mt-0.5 shadow-glow/30">
          <Bot className="h-4 w-4 text-primary" />
        </div>
      )}
      <div className={cn('flex flex-col gap-1.5 max-w-[78%]', isUser && 'items-end')}>
        <div
          className={cn(
            'rounded-2xl px-4 py-3 text-[13.5px] leading-relaxed',
            isUser
              ? 'bg-primary text-primary-foreground rounded-tr-sm shadow-glow/40'
              : cn('glass-warm rounded-tl-sm border border-border/60', msg.error && 'border-destructive/40 text-destructive'),
          )}
        >
          {isUser ? msg.content : (
            <span className="whitespace-pre-wrap text-foreground/90">{renderContent(msg.content)}</span>
          )}
        </div>

        {!isUser && uniqueTools.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-1">
            {uniqueTools.map((tool) => (
              <span key={tool} className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full bg-primary/8 text-primary/70 border border-primary/15">
                <Zap className="h-2.5 w-2.5" />
                {TOOL_LABELS[tool] ?? tool}
              </span>
            ))}
          </div>
        )}
        <span className="text-[10px] text-muted-foreground/45 px-1">{time}</span>
      </div>
    </div>
  );
}

// ── Typing indicator ──────────────────────────────────────────────────────────

function TypingDots() {
  return (
    <div className="flex gap-3 animate-fade-in">
      <div className="shrink-0 h-8 w-8 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
        <Bot className="h-4 w-4 text-primary" />
      </div>
      <div className="glass-warm rounded-2xl rounded-tl-sm px-4 py-3 border border-border/60">
        <div className="flex gap-1.5 items-center h-5">
          {[0, 1, 2].map((i) => (
            <span key={i} className="h-1.5 w-1.5 rounded-full bg-primary/50 animate-bounce"
              style={{ animationDelay: `${i * 0.18}s`, animationDuration: '0.9s' }} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Welcome state ─────────────────────────────────────────────────────────────

function WelcomeState({ onSelect }: { onSelect: (prompt: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[360px] text-center space-y-8 px-4">
      <div className="space-y-4">
        <div className="relative mx-auto h-16 w-16">
          <div className="h-16 w-16 rounded-2xl bg-primary/10 border border-primary/25 flex items-center justify-center shadow-glow">
            <Bot className="h-8 w-8 text-primary" />
          </div>
          <span className="absolute -top-1 -right-1 h-3 w-3 rounded-full bg-decision-promote animate-pulse ring-2 ring-background" />
        </div>
        <div>
          <h2 className="font-display text-[22px] font-semibold text-foreground tracking-tight">Radar AI</h2>
          <p className="text-[13px] text-muted-foreground mt-1.5 max-w-xs mx-auto leading-relaxed">
            Your senior inventory &amp; pricing analyst. Ask anything about your store.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5 w-full max-w-lg">
        {QUICK_PROMPTS.map((qp) => (
          <button key={qp.prompt} onClick={() => onSelect(qp.prompt)}
            className="group flex items-center justify-between gap-2 text-left rounded-xl border border-border/60 bg-card/40 hover:bg-card hover:border-primary/30 hover:shadow-glow/20 px-3.5 py-3 transition-all duration-150"
          >
            <div className="flex items-center gap-2 min-w-0">
              <qp.icon className="h-3.5 w-3.5 shrink-0 text-primary/60 group-hover:text-primary transition-colors" />
              <span className="text-[12px] font-medium text-foreground/70 group-hover:text-foreground leading-snug truncate">{qp.label}</span>
            </div>
            <ChevronRight className="h-3 w-3 shrink-0 text-foreground/25 group-hover:text-primary/60 transition-colors" />
          </button>
        ))}
      </div>

      <p className="text-[11px] text-muted-foreground/50">
        Ask in English or Arabic · responds with live data from your store
      </p>
    </div>
  );
}

// ── History panel ─────────────────────────────────────────────────────────────

interface HistoryPanelProps {
  sessions: ChatSession[];
  activeSessionId: string;
  loading: boolean;
  sessionsLoading: boolean;
  sessionsError: boolean;
  onNewChat: () => void;
  onSelectSession: (sid: string) => void;
  onRetry: () => void;
}

function HistoryPanel({
  sessions, activeSessionId, loading, sessionsLoading, sessionsError,
  onNewChat, onSelectSession, onRetry,
}: HistoryPanelProps) {
  return (
    <div className="w-52 shrink-0 border-r border-border/50 flex flex-col bg-sidebar/20 overflow-hidden">
      {/* New chat button */}
      <div className="p-3 border-b border-border/40">
        <button
          onClick={onNewChat}
          disabled={loading}
          className="w-full flex items-center gap-2 rounded-lg border border-border/60 bg-card/50 hover:bg-card hover:border-primary/30 px-3 py-2 text-[12.5px] font-medium text-foreground/75 hover:text-foreground transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Plus className="h-3.5 w-3.5 shrink-0 text-primary/70" />
          New chat
        </button>
      </div>

      {/* Sessions list */}
      <div className="flex-1 overflow-y-auto py-2 scrollbar-thin">
        {sessionsLoading && sessions.length === 0 ? (
          /* Skeleton — only if we have nothing to show yet */
          <ul className="px-2 space-y-1 mt-1">
            {[1, 2, 3].map((i) => (
              <li key={i} className="rounded-lg px-3 py-2.5 animate-pulse">
                <div className="h-3 bg-muted/50 rounded w-4/5 mb-1.5" />
                <div className="h-2 bg-muted/30 rounded w-2/5" />
              </li>
            ))}
          </ul>
        ) : sessionsError && sessions.length === 0 ? (
          /* Error only when nothing is cached locally */
          <div className="flex flex-col items-center justify-center gap-2.5 mt-8 px-4 text-center">
            <AlertTriangle className="h-5 w-5 text-amber-400/60" />
            <p className="text-[11px] text-muted-foreground/50 leading-relaxed">
              Could not load history
            </p>
            <button
              onClick={onRetry}
              className="inline-flex items-center gap-1.5 text-[11px] font-medium text-primary/70 hover:text-primary transition-colors"
            >
              <RefreshCw className="h-3 w-3" />
              Retry
            </button>
          </div>
        ) : sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 mt-8 px-4 text-center">
            <MessageSquare className="h-6 w-6 text-muted-foreground/30" />
            <p className="text-[11px] text-muted-foreground/50 leading-relaxed">
              Your conversations will appear here
            </p>
          </div>
        ) : (
          <ul className="px-2 space-y-0.5">
            {sessions.map((s) => {
              const isActive = s.session_id === activeSessionId;
              return (
                <li key={s.session_id}>
                  <button
                    onClick={() => onSelectSession(s.session_id)}
                    disabled={loading}
                    className={cn(
                      'w-full text-left rounded-lg px-3 py-2.5 transition-all duration-100 group disabled:cursor-not-allowed',
                      isActive
                        ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                        : 'hover:bg-sidebar-accent/50 text-sidebar-foreground/70 hover:text-sidebar-foreground',
                    )}
                  >
                    <div className="flex items-start gap-2">
                      <MessageSquare className={cn(
                        'h-3.5 w-3.5 shrink-0 mt-0.5',
                        isActive ? 'text-primary' : 'text-muted-foreground/40 group-hover:text-muted-foreground/70',
                      )} />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[12px] font-medium leading-snug">
                          {s.title || 'New conversation'}
                        </div>
                        <div className="flex items-center gap-1 mt-0.5">
                          <Clock className="h-2.5 w-2.5 text-muted-foreground/40" />
                          <span className="text-[10px] text-muted-foreground/50">
                            {relativeTime(s.last_message_at)}
                          </span>
                        </div>
                      </div>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Footer label */}
      <div className="px-4 py-2.5 border-t border-border/40">
        <p className="text-[10px] text-muted-foreground/40 text-center">Chat history</p>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ChatAssistant() {
  const user = useAuth((s) => s.user);
  const token = useAuth((s) => s.token);
  const tenantId = user?.tenant_id ?? '';
  const location = useLocation();

  // ── Persistent chat store (survives navigation AND re-login) ─────────────
  const storeSessions = useChatStore((s) => s.byTenant[tenantId]?.sessions ?? []);
  const storeActiveId = useChatStore((s) => s.byTenant[tenantId]?.activeSessionId ?? '');
  const setSessions = useChatStore((s) => s.setSessions);
  const upsertSession = useChatStore((s) => s.upsertSession);
  const setActiveSession = useChatStore((s) => s.setActiveSession);
  const setSessionMessages = useChatStore((s) => s.setSessionMessages);
  const getSessionMessages = useChatStore((s) => s.getSessionMessages);

  // ── Helpers: convert between store format and component format ────────────
  function storedToMessages(stored: StoredMessage[]): Message[] {
    return stored.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      tools: m.tools,
      timestamp: new Date(m.timestamp),
      error: m.error,
    }));
  }

  function messagesToStored(msgs: Message[]): StoredMessage[] {
    return msgs
      .filter((m) => !m.error)
      .map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        tools: m.tools ?? [],
        timestamp: m.timestamp.toISOString(),
        error: m.error,
      }));
  }

  // ── Local component state ─────────────────────────────────────────────────
  // Initialise from store so messages are visible instantly after re-login
  const [messages, setMessages] = useState<Message[]>(() => {
    const sid = storeActiveId || (typeof window !== 'undefined'
      ? localStorage.getItem(`radar-chat-sid-${tenantId}`) ?? ''
      : '');
    return sid ? storedToMessages(getSessionMessages(tenantId, sid)) : [];
  });
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(storeSessions.length === 0);
  const [sessionsError, setSessionsError] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sessionIdRef = useRef<string>('');
  const initialMessageFiredRef = useRef(false);
  const historyLoadedRef = useRef(false);

  const base = ASSISTANT_BASE.replace(/\/$/, '');

  // Derive active session from the store (persists across navigation)
  const activeSessionId = storeActiveId;

  // ── Session ID init ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!tenantId) return;
    const key = `radar-chat-sid-${tenantId}`;
    let sid = localStorage.getItem(key);
    if (!sid) {
      sid = randomId();
      localStorage.setItem(key, sid);
    }
    sessionIdRef.current = sid;
    // Sync to store if not already set
    if (!storeActiveId) {
      setActiveSession(tenantId, sid);
    } else {
      sessionIdRef.current = storeActiveId;
      localStorage.setItem(key, storeActiveId);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  // ── Load sessions list from backend ──────────────────────────────────────
  const loadSessions = useCallback(async () => {
    if (!tenantId || !token) return;
    setSessionsError(false);
    try {
      const res = await fetch(`${base}/chat/sessions`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = (await res.json()) as { sessions: ChatSession[] };
        const fetched = data.sessions ?? [];
        // Read current store state directly to avoid stale closure
        const current = useChatStore.getState().getSessions(tenantId);
        const localOnly = current.filter(
          (ls) => !fetched.some((fs) => fs.session_id === ls.session_id),
        );
        setSessions(tenantId, [...fetched, ...localOnly]);
      } else {
        setSessionsError(true);
      }
    } catch {
      setSessionsError(true);
    } finally {
      setSessionsLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, token, base]);

  useEffect(() => {
    // If store already has sessions, skip the loading skeleton immediately
    if (storeSessions.length > 0) setSessionsLoading(false);
    loadSessions();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, token]);

  // Refresh when user returns to this tab
  useEffect(() => {
    const onFocus = () => loadSessions();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [loadSessions]);

  // ── Load message history for active session on mount ─────────────────────
  // Step 1: restore from local store immediately (works offline / after re-login).
  // Step 2: sync from backend in background and merge if backend has more messages.
  useEffect(() => {
    if (!tenantId || !token || historyLoadedRef.current) return;
    historyLoadedRef.current = true;

    const sid = storeActiveId || localStorage.getItem(`radar-chat-sid-${tenantId}`);
    if (!sid) return;

    sessionIdRef.current = sid;
    setActiveSession(tenantId, sid);

    // Restore from store immediately — no network needed
    const cached = useChatStore.getState().getSessionMessages(tenantId, sid);
    if (cached.length > 0) {
      setMessages(storedToMessages(cached));
    }

    // Background sync with backend to pick up any messages missed locally
    fetch(`${base}/chat/history?session_id=${encodeURIComponent(sid)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { messages?: Array<{ role: string; content: string; tools_used?: string[]; ts?: string }> } | null) => {
        if (data?.messages?.length) {
          // Use backend data if it has more messages than local cache
          const backendMsgs = data.messages.map((m) => ({
            id: randomId(),
            role: m.role as Role,
            content: m.content,
            tools: m.tools_used ?? [],
            timestamp: m.ts ? new Date(m.ts) : new Date(),
          }));
          if (backendMsgs.length >= cached.length) {
            setMessages(backendMsgs);
            setSessionMessages(tenantId, sid, messagesToStored(backendMsgs));
          }
        }
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, token]);

  // ── Switch to a past session ──────────────────────────────────────────────
  const switchSession = useCallback(async (sid: string) => {
    if (loading || sid === sessionIdRef.current) return;
    const key = `radar-chat-sid-${tenantId}`;
    localStorage.setItem(key, sid);
    sessionIdRef.current = sid;
    setActiveSession(tenantId, sid);

    // Restore from local store immediately — instant, no spinner
    const cached = useChatStore.getState().getSessionMessages(tenantId, sid);
    setMessages(cached.length > 0 ? storedToMessages(cached) : []);

    // Background sync with backend
    try {
      const res = await fetch(`${base}/chat/history?session_id=${encodeURIComponent(sid)}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = (await res.json()) as { messages?: Array<{ role: string; content: string; tools_used?: string[]; ts?: string }> };
        if (data?.messages?.length) {
          const backendMsgs = data.messages.map((m) => ({
            id: randomId(),
            role: m.role as Role,
            content: m.content,
            tools: m.tools_used ?? [],
            timestamp: m.ts ? new Date(m.ts) : new Date(),
          }));
          if (backendMsgs.length >= cached.length) {
            setMessages(backendMsgs);
            setSessionMessages(tenantId, sid, messagesToStored(backendMsgs));
          }
        }
      }
    } catch {
      // non-fatal — cached messages already shown
    }
  }, [loading, tenantId, token, base, setActiveSession, setSessionMessages]);

  // ── New chat ──────────────────────────────────────────────────────────────
  function newChat() {
    if (!tenantId) return;

    // Snapshot current session into the store before switching away
    const prevSid = sessionIdRef.current;
    if (prevSid && messages.length > 0) {
      const firstUserMsg = messages.find((m) => m.role === 'user');
      const localTitle = firstUserMsg
        ? firstUserMsg.content.slice(0, 60) + (firstUserMsg.content.length > 60 ? '…' : '')
        : 'New conversation';
      upsertSession(tenantId, {
        session_id: prevSid,
        title: localTitle,
        last_message_at: new Date().toISOString(),
        created_at: new Date().toISOString(),
      });
      // Also persist messages so they survive re-login
      setSessionMessages(tenantId, prevSid, messagesToStored(messages));
    }

    const newSid = randomId();
    localStorage.setItem(`radar-chat-sid-${tenantId}`, newSid);
    sessionIdRef.current = newSid;
    setActiveSession(tenantId, newSid);
    setMessages([]);
    setInput('');
    loadSessions();
  }

  // ── Initial message from router state (e.g. from Financial page) ──────────
  useEffect(() => {
    const initialMessage = (location.state as { initialMessage?: string } | null)?.initialMessage;
    if (!initialMessage || initialMessageFiredRef.current || !tenantId) return;
    initialMessageFiredRef.current = true;
    window.history.replaceState({}, '');
    sendMessage(initialMessage);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  // ── Auto-scroll ───────────────────────────────────────────────────────────
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // ── Auto-resize textarea ──────────────────────────────────────────────────
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 130)}px`;
  }, [input]);

  // ── Send message ──────────────────────────────────────────────────────────
  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || loading || !tenantId) return;

      setMessages((prev) => [
        ...prev,
        { id: randomId(), role: 'user', content: trimmed, timestamp: new Date() },
      ]);
      setInput('');
      setLoading(true);

      try {
        const res = await fetch(`${base}/chat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            message: trimmed,
            session_id: sessionIdRef.current,
            tenant_id: tenantId,
          }),
        });

        if (!res.ok) throw new Error(await assistantErrorMessage(res));

        const data = (await res.json()) as { reply: string; tools_used: string[]; session_id: string };

        // If backend assigned a new session_id, sync it everywhere
        if (data.session_id && data.session_id !== sessionIdRef.current) {
          localStorage.setItem(`radar-chat-sid-${tenantId}`, data.session_id);
          sessionIdRef.current = data.session_id;
          setActiveSession(tenantId, data.session_id);
        }

        const assistantMsg: Message = {
          id: randomId(),
          role: 'assistant',
          content: data.reply,
          tools: data.tools_used,
          timestamp: new Date(),
        };

        setMessages((prev) => {
          const next = [...prev, assistantMsg];
          // Persist full conversation to store after every reply
          const currentSid = data.session_id || sessionIdRef.current;
          if (currentSid) setSessionMessages(tenantId, currentSid, messagesToStored(next));
          return next;
        });

        // Optimistically persist session in store so sidebar shows it immediately
        const currentSid = data.session_id || sessionIdRef.current;
        if (currentSid) {
          upsertSession(tenantId, {
            session_id: currentSid,
            title: trimmed.slice(0, 60) + (trimmed.length > 60 ? '…' : ''),
            last_message_at: new Date().toISOString(),
            created_at: new Date().toISOString(),
          });
        }

        // Background sync with backend to get canonical title/timestamp
        loadSessions();

      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Unknown error';
        const authError = msg.includes('not authorized') || msg.includes('Log in again');
        const serviceError = msg.includes('service is not ready');
        const backendError = msg.includes('backend failed');
        setMessages((prev) => [
          ...prev,
          {
            id: randomId(),
            role: 'assistant',
            content: authError
              ? 'Your session is not authorized for Radar Assistant. Please log in again.'
              : serviceError
              ? 'Radar Assistant is starting up. Try again in a moment.'
              : backendError
              ? 'Radar Assistant reached the backend, but it failed while answering. Please try again.'
              : 'Something went wrong. Please try again in a moment.',
            timestamp: new Date(),
            error: true,
          },
        ]);
        toast.error('Radar AI error', { description: msg });
      } finally {
        setLoading(false);
      }
    },
    [loading, tenantId, token, base, loadSessions, upsertSession, setActiveSession, setSessionMessages],
  );

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  const hasMessages = messages.length > 0 || loading;

  return (
    <>
      <TopBar title="Radar Assistant" subtitle="AI inventory & pricing analyst" />

      <div className="flex" style={{ height: 'calc(100vh - 4rem)' }}>

        {/* ── Chat history sidebar ── */}
        <HistoryPanel
          sessions={storeSessions}
          activeSessionId={activeSessionId}
          loading={loading}
          sessionsLoading={sessionsLoading}
          sessionsError={sessionsError}
          onNewChat={newChat}
          onSelectSession={switchSession}
          onRetry={loadSessions}
        />

        {/* ── Chat area ── */}
        <div className="flex-1 flex flex-col min-w-0">

          {/* Messages */}
          <div className="flex-1 min-h-0 overflow-y-auto px-4 lg:px-8 py-6 space-y-5 scrollbar-thin">
            {!hasMessages ? (
              <WelcomeState onSelect={(p) => sendMessage(p)} />
            ) : (
              <>
                {messages.map((msg) => (
                  <MessageBubble key={msg.id} msg={msg} />
                ))}
                {loading && <TypingDots />}
              </>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input area */}
          <div className="shrink-0 border-t border-border/50 bg-background/95 backdrop-blur-sm px-4 lg:px-8 py-4">
            <div
              className={cn(
                'relative flex items-end gap-3 rounded-2xl border bg-card/50 px-4 py-3 transition-all duration-150',
                loading
                  ? 'border-border/50 opacity-80'
                  : 'border-border/70 focus-within:border-primary/40 focus-within:shadow-glow/15',
              )}
            >
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about inventory, pricing, competitors, or decisions…"
                rows={1}
                disabled={loading}
                className="flex-1 resize-none bg-transparent text-[13.5px] text-foreground placeholder:text-muted-foreground/50 focus:outline-none leading-relaxed min-h-[24px] max-h-[130px] disabled:cursor-wait"
              />
              <button
                onClick={() => sendMessage(input)}
                disabled={!input.trim() || loading}
                aria-label="Send message"
                className={cn(
                  'shrink-0 h-8 w-8 rounded-xl flex items-center justify-center transition-all duration-150',
                  input.trim() && !loading
                    ? 'bg-primary text-primary-foreground shadow-glow hover:bg-primary/90 hover:shadow-glow/80'
                    : 'bg-muted/60 text-muted-foreground cursor-not-allowed',
                )}
              >
                {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
              </button>
            </div>

            <div className="flex items-center justify-between mt-2 px-1">
              <p className="text-[10.5px] text-muted-foreground/40">
                Enter to send · Shift+Enter for new line
              </p>
              {!tenantId && (
                <p className="inline-flex items-center gap-1 text-[10.5px] text-amber-400/70">
                  <AlertTriangle className="h-3 w-3" />
                  No tenant session — log in again
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
