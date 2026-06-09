/**
 * Persistent chat store — survives React navigation AND re-login.
 *
 * Sessions list + message content are keyed by tenantId so each retailer
 * has fully isolated history. Data is written to localStorage so it
 * survives logout → login cycles without any backend call.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface ChatSession {
  session_id: string;
  title: string | null;
  last_message_at: string;
  created_at: string;
}

export interface StoredMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  tools: string[];
  timestamp: string; // ISO string (Date is not JSON-serialisable)
  error?: boolean;
}

interface TenantChatState {
  sessions: ChatSession[];
  activeSessionId: string;
  /** Messages per session_id — kept for offline re-login display */
  messages: Record<string, StoredMessage[]>;
}

interface ChatStoreState {
  byTenant: Record<string, TenantChatState>;

  setSessions: (tenantId: string, sessions: ChatSession[]) => void;
  upsertSession: (tenantId: string, session: ChatSession) => void;
  setActiveSession: (tenantId: string, sessionId: string) => void;
  getSessions: (tenantId: string) => ChatSession[];
  getActiveSessionId: (tenantId: string) => string;

  /** Replace stored messages for a session (called after every send/load) */
  setSessionMessages: (tenantId: string, sessionId: string, messages: StoredMessage[]) => void;
  /** Read stored messages for a session */
  getSessionMessages: (tenantId: string, sessionId: string) => StoredMessage[];
}

const MAX_MESSAGES_PER_SESSION = 200;

export const useChatStore = create<ChatStoreState>()(
  persist(
    (set, get) => ({
      byTenant: {},

      setSessions: (tenantId, sessions) =>
        set((state) => ({
          byTenant: {
            ...state.byTenant,
            [tenantId]: {
              sessions,
              activeSessionId: state.byTenant[tenantId]?.activeSessionId ?? '',
              messages: state.byTenant[tenantId]?.messages ?? {},
            },
          },
        })),

      upsertSession: (tenantId, session) =>
        set((state) => {
          const current = state.byTenant[tenantId]?.sessions ?? [];
          const withoutOld = current.filter((s) => s.session_id !== session.session_id);
          return {
            byTenant: {
              ...state.byTenant,
              [tenantId]: {
                sessions: [session, ...withoutOld],
                activeSessionId: state.byTenant[tenantId]?.activeSessionId ?? '',
                messages: state.byTenant[tenantId]?.messages ?? {},
              },
            },
          };
        }),

      setActiveSession: (tenantId, sessionId) =>
        set((state) => ({
          byTenant: {
            ...state.byTenant,
            [tenantId]: {
              sessions: state.byTenant[tenantId]?.sessions ?? [],
              activeSessionId: sessionId,
              messages: state.byTenant[tenantId]?.messages ?? {},
            },
          },
        })),

      getSessions: (tenantId) => get().byTenant[tenantId]?.sessions ?? [],
      getActiveSessionId: (tenantId) => get().byTenant[tenantId]?.activeSessionId ?? '',

      setSessionMessages: (tenantId, sessionId, messages) =>
        set((state) => {
          const tenant = state.byTenant[tenantId] ?? {
            sessions: [],
            activeSessionId: '',
            messages: {},
          };
          return {
            byTenant: {
              ...state.byTenant,
              [tenantId]: {
                ...tenant,
                messages: {
                  ...tenant.messages,
                  // Trim to cap to avoid localStorage bloat
                  [sessionId]: messages.slice(-MAX_MESSAGES_PER_SESSION),
                },
              },
            },
          };
        }),

      getSessionMessages: (tenantId, sessionId) =>
        get().byTenant[tenantId]?.messages?.[sessionId] ?? [],
    }),
    {
      name: 'radar-chat-store',
      partialize: (state) => ({ byTenant: state.byTenant }),
    },
  ),
);
