import { useState, useRef, useEffect, useCallback } from 'react';
import {
  BotMessageSquare, Send, Loader2, RefreshCw,
  BarChart3, Bell, DollarSign, Megaphone, Target, Users,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { adminAssistantChat } from '@/lib/adapter';
import { toast } from 'sonner';
import { AdminHeader } from './AdminDashboard';

type Role = 'user' | 'assistant';

interface Message {
  id: string;
  role: Role;
  content: string;
  tools?: string[];
  timestamp: Date;
  error?: boolean;
}

const TOOL_LABELS: Record<string, string> = {
  get_platform_outcomes: 'Outcomes',
  get_financial_health: 'Financial',
  get_campaigns_activity: 'Campaigns',
  list_tenants: 'Tenants',
  get_pending_items: 'Pending',
};

const QUICK_PROMPTS: { label: string; prompt: string; icon: React.ElementType }[] = [
  { label: 'At-risk shops', prompt: 'Which shops are at financial risk right now?', icon: DollarSign },
  { label: 'Model accuracy', prompt: 'How accurate are PROMOTE decisions this month?', icon: Target },
  { label: 'Pending items', prompt: "What's pending — measurements, requests, notifications?", icon: Bell },
  { label: 'Missing financials', prompt: "Which tenants haven't submitted financials this month?", icon: BarChart3 },
  { label: 'Campaign activity', prompt: 'Show me campaign activity this week', icon: Megaphone },
  { label: 'Top performers', prompt: 'Which tenant is getting the best recommendation accuracy?', icon: Users },
];

function renderContent(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const boldRegex = /\*\*(.*?)\*\*|\*(.*?)\*/g;
  let lastIndex = 0;
  let match;
  while ((match = boldRegex.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
    parts.push(<strong key={match.index}>{match[1] ?? match[2]}</strong>);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}

export default function AdminAssistant() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId] = useState(() => `admin-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const autoResize = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
  }, []);

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || loading) return;
    const userMsg: Message = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: text.trim(),
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    setLoading(true);

    try {
      const resp = await adminAssistantChat(text.trim(), sessionId);
      const assistantMsg: Message = {
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: resp.reply,
        tools: resp.tools_used,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (e: any) {
      const errMsg: Message = {
        id: `e-${Date.now()}`,
        role: 'assistant',
        content: e?.message || 'Assistant error — check that the backend is running.',
        timestamp: new Date(),
        error: true,
      };
      setMessages((prev) => [...prev, errMsg]);
    } finally {
      setLoading(false);
    }
  }, [loading, sessionId]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <AdminHeader title="Admin Assistant" subtitle="Ask platform-level questions — outcomes, financial health, campaigns, pending items" />

      <div className="flex-1 overflow-y-auto px-4 lg:px-8 py-6 space-y-4">
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center h-full gap-8 max-w-2xl mx-auto text-center">
            <div className="h-16 w-16 rounded-2xl bg-gradient-data flex items-center justify-center shadow-glow">
              <BotMessageSquare className="h-8 w-8 text-primary-foreground" />
            </div>
            <div>
              <h2 className="font-display text-2xl font-bold mb-2">Platform Intelligence Assistant</h2>
              <p className="text-muted-foreground text-[14px]">
                Ask about recommendation accuracy, financial risk, campaign activity, or any pending operational items across all shops.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3 w-full">
              {QUICK_PROMPTS.map((p) => (
                <button
                  key={p.label}
                  onClick={() => sendMessage(p.prompt)}
                  disabled={loading}
                  className="flex items-center gap-3 p-3 rounded-xl border border-border bg-card/80 hover:border-primary/40 hover:bg-primary/5 text-left transition group disabled:opacity-50"
                >
                  <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 group-hover:bg-primary/20 transition">
                    <p.icon className="h-4 w-4 text-primary" />
                  </div>
                  <span className="text-[13px] font-medium text-foreground leading-snug">{p.label}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg) => (
              <div key={msg.id} className={cn('flex gap-3 max-w-4xl mx-auto', msg.role === 'user' && 'justify-end')}>
                {msg.role === 'assistant' && (
                  <div className="h-7 w-7 rounded-full bg-gradient-data flex items-center justify-center shrink-0 mt-1 shadow-glow-sm">
                    <BotMessageSquare className="h-3.5 w-3.5 text-primary-foreground" />
                  </div>
                )}
                <div className={cn('max-w-[78%]', msg.role === 'user' ? 'ml-auto' : '')}>
                  <div className={cn(
                    'rounded-2xl px-4 py-3 text-[14px] leading-relaxed',
                    msg.role === 'user'
                      ? 'bg-gradient-data text-primary-foreground rounded-br-md'
                      : msg.error
                      ? 'bg-decision-clear/10 border border-decision-clear/30 text-foreground rounded-bl-md'
                      : 'bg-card border border-border text-foreground rounded-bl-md',
                  )}>
                    {msg.role === 'assistant'
                      ? msg.content.split('\n').map((line, i) => (
                          <p key={i} className={i > 0 ? 'mt-1.5' : ''}>{renderContent(line)}</p>
                        ))
                      : msg.content
                    }
                  </div>
                  {msg.tools && msg.tools.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      {msg.tools.map((t) => (
                        <span key={t} className="text-[10.5px] font-mono px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                          {TOOL_LABELS[t] ?? t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex gap-3 max-w-4xl mx-auto">
                <div className="h-7 w-7 rounded-full bg-gradient-data flex items-center justify-center shrink-0 mt-1 shadow-glow-sm">
                  <BotMessageSquare className="h-3.5 w-3.5 text-primary-foreground" />
                </div>
                <div className="flex items-center gap-1 px-4 py-3 rounded-2xl rounded-bl-md bg-card border border-border">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="h-2 w-2 rounded-full bg-primary/60 animate-bounce"
                      style={{ animationDelay: `${i * 150}ms` }}
                    />
                  ))}
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </>
        )}
      </div>

      {/* Input bar */}
      <div className="border-t border-border bg-background/80 backdrop-blur-md px-4 lg:px-8 py-4">
        <div className="max-w-4xl mx-auto">
          {messages.length > 0 && (
            <button
              onClick={() => setMessages([])}
              className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground hover:text-foreground transition mb-3"
            >
              <RefreshCw className="h-3 w-3" /> New conversation
            </button>
          )}
          <div className="flex items-end gap-3 rounded-xl border border-border bg-card/80 px-4 py-3 focus-within:border-primary/50 focus-within:shadow-glow-sm transition">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => { setInput(e.target.value); autoResize(); }}
              onKeyDown={handleKeyDown}
              placeholder="Ask about platform health, model accuracy, at-risk shops…"
              rows={1}
              disabled={loading}
              className="flex-1 resize-none bg-transparent text-[14px] leading-relaxed outline-none placeholder:text-muted-foreground/50 disabled:opacity-50"
            />
            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || loading}
              className="h-8 w-8 rounded-lg bg-gradient-data flex items-center justify-center shrink-0 shadow-glow-sm hover:opacity-90 transition disabled:opacity-30 disabled:cursor-not-allowed"
            >
              {loading ? <Loader2 className="h-4 w-4 text-primary-foreground animate-spin" /> : <Send className="h-4 w-4 text-primary-foreground" />}
            </button>
          </div>
          <p className="text-[11px] text-muted-foreground/50 mt-2 text-center">
            Platform-scoped assistant — accesses all tenant data
          </p>
        </div>
      </div>
    </div>
  );
}
