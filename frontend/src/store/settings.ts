import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { DataMode, RecommendationStatus, Decision } from '@/types/domain';

interface RecState {
  status: RecommendationStatus;
  notes?: string;
  editedPriceUsd?: number;
  editedDiscountPct?: number;
  updatedAt: string;
}

interface SettingsState {
  mode: DataMode;
  apiBaseUrl: string;
  ie2BaseUrl: string;
  apiKey: string;
  recState: Record<string, RecState>; // by sku_id
  setMode: (m: DataMode) => void;
  setApiBaseUrl: (u: string) => void;
  setIe2BaseUrl: (u: string) => void;
  setApiKey: (k: string) => void;
  setRecStatus: (sku: string, status: RecommendationStatus, patch?: Partial<RecState>) => void;
  resetRecs: () => void;
}

const env = import.meta.env;
const defaultApiBaseUrl = env.PROD ? '' : 'http://localhost:8000';
const defaultIe2BaseUrl = env.PROD ? '/ie2' : 'http://localhost:8002';

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      mode: (env.VITE_DATA_MODE as DataMode) || 'mock-report',
      apiBaseUrl: env.VITE_API_BASE_URL ?? defaultApiBaseUrl,
      ie2BaseUrl: env.VITE_IE2_BASE_URL ?? defaultIe2BaseUrl,
      apiKey: env.VITE_API_KEY || 'ie2-local-postman-key',
      recState: {},
      setMode: (mode) => set({ mode }),
      setApiBaseUrl: (apiBaseUrl) => set({ apiBaseUrl }),
      setIe2BaseUrl: (ie2BaseUrl) => set({ ie2BaseUrl }),
      setApiKey: (apiKey) => set({ apiKey }),
      setRecStatus: (sku, status, patch) =>
        set((s) => ({
          recState: {
            ...s.recState,
            [sku]: { ...(s.recState[sku] || ({} as RecState)), ...patch, status, updatedAt: new Date().toISOString() },
          },
        })),
      resetRecs: () => set({ recState: {} }),
    }),
    { name: 'rr-settings-v1' }
  )
);

export const decisionOrder: Decision[] = ['CLEAR', 'MARKDOWN', 'PROMOTE', 'HOLD'];
