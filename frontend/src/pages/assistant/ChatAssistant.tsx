import { useState, useRef, useEffect, useCallback } from 'react';
import { TopBar } from '@/components/layout/TopBar';
import {
  Bot, Send, Zap, Loader2, RefreshCw, ChevronRight,
  AlertTriangle, Boxes, ListChecks, DollarSign, TrendingUp, Users, Target,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/store/auth';
import { useSettings } from '@/store/settings';
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
  (import.meta.env.PROD ? '/assistant-api' : 'http://localhost:8004');

const TOOL_LABELS: Record<string, string> = {
  get_inventory_overview: 'Inventory',
  get_stockout_days: 'Stockouts',
  get_reorder_suggestions: 'Reorder',
  get_sku_velocity_trend: 'Velocity',
  get_category_performance: 'Categories',
  get_financials: 'Financials',
  get_revenue_trend: 'Revenue',
  get_competitor_prices: 'Competitors',
  get_pending_recommendations: 'Recommendations',
  approve_recommendation: 'Approved ✓',
  reject_recommendation: 'Rejected',
  get_decision_progress: 'Progress',
  get_roadmap_summary: 'Roadmap',
  get_next_actions: 'Next actions',
};

const QUICK_PROMPTS: { label: string; prompt: string; icon: React.ElementType }[] = [
  { label: 'Inventory status', prompt: 'How is my inventory right now?', icon: Boxes },
  { label: 'Pending decisions', prompt: 'Show me pending recommendations', icon: ListChecks },
  { label: "Today's focus", prompt: 'What should I focus on today?', icon: Target },
  { label: 'Sales trend', prompt: 'Are sales up this week?', icon: TrendingUp },
  { label: 'Competitor prices', prompt: 'What are competitors charging?', icon: Users },
  { label: 'Cash position', prompt: 'How much cash do I have?', icon: DollarSign },
];

// ── Markdown renderer — handles Telegram *bold* syntax ────────────────────────

function renderContent(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const regex = /\*([^*\n]+)\*/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(<span key={key++}>{text.slice(lastIndex, match.index)}</span>);
    }
    parts.push(
      <strong key={key++} className="font-semibold text-foreground">
        {match[1]}
      </strong>,
    );
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(<span key={key++}>{text.slice(lastIndex)}</span>);
  }

  return <>{parts}</>;
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user';
  const time = msg.timestamp.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  const uniqueTools = msg.tools ? [...new Set(msg.tools)] : [];

  return (
    <div className={cn('flex gap-3 animate-fade-in', isUser ? 'flex-row-reverse' : 'flex-row')}>
      {/* AI avatar */}
      {!isUser && (
        <div className="shrink-0 h-8 w-8 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center mt-0.5 shadow-glow/30">
          <Bot className="h-4 w-4 text-primary" />
        </div>
      )}

      <div className={cn('flex flex-col gap-1.5 max-w-[78%]', isUser && 'items-end')}>
        {/* Bubble */}
        <div
          className={cn(
            'rounded-2xl px-4 py-3 text-[13.5px] leading-relaxed',
            isUser
              ? 'bg-primary text-primary-foreground rounded-tr-sm shadow-glow/40'
              : cn(
                  'glass-warm rounded-tl-sm border border-border/60',
                  msg.error && 'border-destructive/40 text-destructive',
                ),
          )}
        >
          {isUser ? (
            msg.content
          ) : (
            <span className="whitespace-pre-wrap text-foreground/90">
              {renderContent(msg.content)}
            </span>
          )}
        </div>

        {/* Tool call chips */}
        {!isUser && uniqueTools.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-1">
            {uniqueTools.map((tool) => (
              <span
                key={tool}
                className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full bg-primary/8 text-primary/70 border border-primary/15"
              >
                <Zap className="h-2.5 w-2.5" />
                {TOOL_LABELS[tool] ?? tool}
              </span>
            ))}
          </div>
        )}

        {/* Timestamp */}
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
            <span
              key={i}
              className="h-1.5 w-1.5 rounded-full bg-primary/50 animate-bounce"
              style={{ animationDelay: `${i * 0.18}s`, animationDuration: '0.9s' }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Empty / welcome state ─────────────────────────────────────────────────────

function WelcomeState({ onSelect }: { onSelect: (prompt: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[360px] text-center space-y-8 px-4">
      {/* Icon + title */}
      <div className="space-y-4">
        <div className="relative mx-auto h-16 w-16">
          <div className="h-16 w-16 rounded-2xl bg-primary/10 border border-primary/25 flex items-center justify-center shadow-glow">
            <Bot className="h-8 w-8 text-primary" />
          </div>
          <span className="absolute -top-1 -right-1 h-3 w-3 rounded-full bg-decision-promote animate-pulse ring-2 ring-background" />
        </div>
        <div>
          <h2 className="font-display text-[22px] font-semibold text-foreground tracking-tight">
            Radar AI
          </h2>
          <p className="text-[13px] text-muted-foreground mt-1.5 max-w-xs mx-auto leading-relaxed">
            Your senior inventory &amp; pricing analyst. Ask anything about your store.
          </p>
        </div>
      </div>

      {/* Quick prompts */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5 w-full max-w-lg">
        {QUICK_PROMPTS.map((qp) => (
          <button
            key={qp.prompt}
            onClick={() => onSelect(qp.prompt)}
            className="group flex items-center justify-between gap-2 text-left rounded-xl border border-border/60 bg-card/40 hover:bg-card hover:border-primary/30 hover:shadow-glow/20 px-3.5 py-3 transition-all duration-150"
          >
            <div className="flex items-center gap-2 min-w-0">
              <qp.icon className="h-3.5 w-3.5 shrink-0 text-primary/60 group-hover:text-primary transition-colors" />
              <span className="text-[12px] font-medium text-foreground/70 group-hover:text-foreground leading-snug truncate">
                {qp.label}
              </span>
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

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ChatAssistant() {
  const user = useAuth((s) => s.user);
  const token = useAuth((s) => s.token);
  const tenantId = user?.tenant_id ?? '';

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sessionIdRef = useRef<string>('');

  // Stable session ID per tenant, persisted in sessionStorage
  useEffect(() => {
    if (!tenantId) return;
    const key = `radar-chat-sid-${tenantId}`;
    let sid = sessionStorage.getItem(key);
    if (!sid) {
      sid = crypto.randomUUID();
      sessionStorage.setItem(key, sid);
    }
    sessionIdRef.current = sid;
  }, [tenantId]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 130)}px`;
  }, [input]);

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || loading || !tenantId) return;

      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: 'user', content: trimmed, timestamp: new Date() },
      ]);
      setInput('');
      setLoading(true);

      try {
        const assistantBase = ASSISTANT_BASE.replace(/\/$/, '');
        const res = await fetch(`${assistantBase}/chat`, {
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

        if (!res.ok) {
          if (res.status === 401 || res.status === 403) {
            throw new Error('Your dashboard session is not authorized for Radar Assistant. Log in again.');
          }
          const errText = await res.text().catch(() => '');
          throw new Error(errText || `HTTP ${res.status}`);
        }

        const data = (await res.json()) as { reply: string; tools_used: string[] };
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: data.reply,
            tools: data.tools_used,
            timestamp: new Date(),
          },
        ]);
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Unknown error';
        const authError = msg.includes('not authorized') || msg.includes('Log in again');
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            content:
              authError
                ? 'Your session is not authorized for Radar Assistant. Please log in again.'
                : 'Something went wrong — please try again in a moment. If the issue persists, check that the assistant service is running.',
            timestamp: new Date(),
            error: true,
          },
        ]);
        toast.error('Radar AI error', { description: msg });
      } finally {
        setLoading(false);
      }
    },
    [loading, tenantId, token],
  );

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  function newChat() {
    if (!tenantId) return;
    const key = `radar-chat-sid-${tenantId}`;
    const newSid = crypto.randomUUID();
    sessionStorage.setItem(key, newSid);
    sessionIdRef.current = newSid;
    setMessages([]);
    setInput('');
  }

  const hasMessages = messages.length > 0 || loading;

  return (
    <>
      <TopBar
        title="Radar Assistant"
        subtitle="AI inventory & pricing analyst"
        actions={
          hasMessages ? (
            <button
              onClick={newChat}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-[12px] font-medium text-foreground/60 hover:text-foreground hover:bg-muted/50 border border-border/50 transition-all"
            >
              <RefreshCw className="h-3 w-3" />
              New chat
            </button>
          ) : undefined
        }
      />

      {/* Chat layout — fixed height so input stays at bottom */}
      <div className="flex flex-col" style={{ height: 'calc(100vh - 4rem)' }}>
        {/* ── Messages ── */}
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

        {/* ── Input area ── */}
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

            {/* Send button */}
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
              {loading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
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
    </>
  );
}
