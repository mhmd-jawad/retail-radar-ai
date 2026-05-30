import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { DataMode, RecommendationStatus, Decision, CampaignCreative } from '@/types/domain';

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
  ie3BaseUrl: string;
  apiKey: string;
  recState: Record<string, RecState>; // by sku_id
  campaignCache: Record<string, CampaignCreative>; // by sku_id, persists across navigation
  whatsappNumber: string; // store WhatsApp number (e.g. 96170123456)
  setMode: (m: DataMode) => void;
  setApiBaseUrl: (u: string) => void;
  setIe2BaseUrl: (u: string) => void;
  setIe3BaseUrl: (u: string) => void;
  setApiKey: (k: string) => void;
  setWhatsappNumber: (n: string) => void;
  setRecStatus: (sku: string, status: RecommendationStatus, patch?: Partial<RecState>) => void;
  resetRecs: () => void;
  setCampaign: (skuId: string, creative: CampaignCreative) => void;
}

const env = import.meta.env;
const defaultApiBaseUrl = env.PROD ? '' : 'http://localhost:8004';
const defaultIe2BaseUrl = env.PROD ? '/ie2' : 'http://localhost:8002';
const defaultIe3BaseUrl = env.PROD ? '/ie3' : 'http://localhost:8003';

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      mode: (env.VITE_DATA_MODE as DataMode) || 'mock-report',
      apiBaseUrl: env.VITE_API_BASE_URL ?? defaultApiBaseUrl,
      ie2BaseUrl: env.VITE_IE2_BASE_URL ?? defaultIe2BaseUrl,
      ie3BaseUrl: env.VITE_IE3_BASE_URL ?? defaultIe3BaseUrl,
      apiKey: env.VITE_API_KEY || 'ie2-local-postman-key',
      recState: {},
      campaignCache: {},
      whatsappNumber: env.VITE_WHATSAPP_NUMBER ?? '',
      setMode: (mode) => set({ mode }),
      setWhatsappNumber: (whatsappNumber) => set({ whatsappNumber }),
      setApiBaseUrl: (apiBaseUrl) => set({ apiBaseUrl }),
      setIe2BaseUrl: (ie2BaseUrl) => set({ ie2BaseUrl }),
      setIe3BaseUrl: (ie3BaseUrl) => set({ ie3BaseUrl }),
      setApiKey: (apiKey) => set({ apiKey }),
      setRecStatus: (sku, status, patch) =>
        set((s) => ({
          recState: {
            ...s.recState,
            [sku]: { ...(s.recState[sku] || ({} as RecState)), ...patch, status, updatedAt: new Date().toISOString() },
          },
        })),
      resetRecs: () => set({ recState: {} }),
      setCampaign: (skuId, creative) =>
        set((s) => ({ campaignCache: { ...s.campaignCache, [skuId]: creative } })),
    }),
    {
      name: 'rr-settings-v1',
      version: 2,
      migrate: (persistedState: unknown, version: number) => {
        const s = (persistedState ?? {}) as Record<string, unknown>;
        if (version < 2) {
          // Port was changed from 8000 → 8004; fix any stale stored URLs
          if (s.apiBaseUrl === 'http://localhost:8000') {
            s.apiBaseUrl = 'http://localhost:8004';
          }
        }
        return s;
      },
    }
  )
);

export const decisionOrder: Decision[] = ['CLEAR', 'MARKDOWN', 'PROMOTE', 'HOLD'];
