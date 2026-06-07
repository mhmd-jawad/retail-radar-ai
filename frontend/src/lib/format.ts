import type { Decision, RecommendationStatus, PricePosition } from '@/types/domain';

function safeNumber(n: number | null | undefined): number {
  return Number.isFinite(n) ? Number(n) : 0;
}

export const fmtUSD = (n: number | null | undefined, opts: { decimals?: number; compact?: boolean } = {}) => {
  const value = safeNumber(n);
  const { decimals = 0, compact } = opts;
  if (compact && Math.abs(value) >= 1000) {
    return `$${(value / 1000).toFixed(value >= 100000 ? 0 : 1)}k`;
  }
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: decimals, maximumFractionDigits: decimals });
};

export const fmtPct = (n: number | null | undefined, decimals = 1) => `${safeNumber(n).toFixed(decimals)}%`;
export const fmtNum = (n: number | null | undefined) => safeNumber(n).toLocaleString('en-US');

export const UNKNOWN_DOS_VALUE = 999;

export function isUnknownDos(n: number | null | undefined): boolean {
  return Number.isFinite(n) && Number(n) >= UNKNOWN_DOS_VALUE;
}

export function fmtDos(n: number | null | undefined, opts: { suffix?: boolean; unknown?: string } = {}): string {
  const { suffix = true, unknown = 'No sales' } = opts;
  if (!Number.isFinite(n)) return 'N/A';
  if (isUnknownDos(n)) return unknown;
  const value = safeNumber(n);
  const rounded = Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1);
  return suffix ? `${rounded}d` : rounded;
}

export function dosTextClass(n: number | null | undefined): string {
  if (isUnknownDos(n)) return 'text-muted-foreground';
  const value = safeNumber(n);
  if (value <= 21) return 'text-decision-clear';
  if (value > 90) return 'text-decision-markdown';
  return 'text-foreground';
}

export const decisionStyles: Record<Decision, { label: string; chip: string; ring: string; dot: string; gradient: string; text: string }> = {
  HOLD: {
    label: 'HOLD',
    chip: 'bg-decision-hold-bg text-decision-hold border-decision-hold/20',
    ring: 'ring-decision-hold/30',
    dot: 'bg-decision-hold',
    gradient: 'from-decision-hold/15 to-decision-hold/5',
    text: 'text-decision-hold',
  },
  PROMOTE: {
    label: 'PROMOTE',
    chip: 'bg-decision-promote-bg text-decision-promote border-decision-promote/20',
    ring: 'ring-decision-promote/30',
    dot: 'bg-decision-promote',
    gradient: 'from-decision-promote/15 to-decision-promote/5',
    text: 'text-decision-promote',
  },
  MARKDOWN: {
    label: 'MARKDOWN',
    chip: 'bg-decision-markdown-bg text-decision-markdown border-decision-markdown/20',
    ring: 'ring-decision-markdown/30',
    dot: 'bg-decision-markdown',
    gradient: 'from-decision-markdown/15 to-decision-markdown/5',
    text: 'text-decision-markdown',
  },
  CLEAR: {
    label: 'CLEAR',
    chip: 'bg-decision-clear-bg text-decision-clear border-decision-clear/20',
    ring: 'ring-decision-clear/30',
    dot: 'bg-decision-clear',
    gradient: 'from-decision-clear/15 to-decision-clear/5',
    text: 'text-decision-clear',
  },
};

export const statusStyles: Record<RecommendationStatus, string> = {
  pending: 'bg-muted text-muted-foreground',
  approved: 'bg-decision-promote-bg text-decision-promote',
  edited: 'bg-amber-100 text-amber-700',
  rejected: 'bg-decision-clear-bg text-decision-clear',
  snoozed: 'bg-secondary text-secondary-foreground',
};

export const positionLabel: Record<PricePosition, string> = {
  premium: 'Premium', above_market: 'Above Market', at_market: 'At Market',
  below_market: 'Below Market', deep_value: 'Deep Value',
};

export const positionStyles: Record<PricePosition, string> = {
  premium: 'bg-decision-clear-bg text-decision-clear',
  above_market: 'bg-decision-markdown-bg text-decision-markdown',
  at_market: 'bg-decision-hold-bg text-decision-hold',
  below_market: 'bg-decision-promote-bg text-decision-promote',
  deep_value: 'bg-accent text-accent-foreground',
};

export function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}
