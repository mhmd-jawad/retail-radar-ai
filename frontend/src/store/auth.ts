import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AuthUser } from '@/types/domain';

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  adminBackup: { token: string; user: AuthUser } | null;
  setSession: (token: string, user: AuthUser) => void;
  setUser: (user: AuthUser | null) => void;
  clearSession: () => void;
  startImpersonation: (token: string, user: AuthUser) => void;
  stopImpersonation: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      adminBackup: null,
      setSession: (token, user) => set({ token, user }),
      setUser: (user) => set({ user }),
      clearSession: () => set({ token: null, user: null, adminBackup: null }),
      startImpersonation: (token, user) =>
        set((state) => ({
          adminBackup: state.token && state.user ? { token: state.token, user: state.user } : state.adminBackup,
          token,
          user,
        })),
      stopImpersonation: () =>
        set((state) =>
          state.adminBackup
            ? { token: state.adminBackup.token, user: state.adminBackup.user, adminBackup: null }
            : state,
        ),
    }),
    {
      name: 'rr-auth-v1',
      version: 1,
    },
  ),
);

export function authHeader(): Record<string, string> {
  const token = useAuth.getState().token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}
