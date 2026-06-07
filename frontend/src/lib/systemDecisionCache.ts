import type { IE2Result } from '@/types/domain';

export const SYSTEM_DECISION_CACHE_EVENT = 'rr-system-decision-cache-updated';
const CACHE_PREFIX = 'rr-system-decisions-v2';
const DAILY_PREFIX = 'rr-system-decisions-daily-v2';

export type SystemDecisionTrigger = 'manual' | 'daily_9am' | 'new_sku';
export type SystemDecisionStatus = 'report' | 'queued' | 'checking' | 'live' | 'error';

export type SystemDecisionCacheEntry = {
  status: Extract<SystemDecisionStatus, 'live' | 'error'>;
  result?: IE2Result;
  error?: string;
  checkedAt: number;
  trigger: SystemDecisionTrigger;
};

function cacheKey(scopeKey: string) {
  return `${CACHE_PREFIX}:${scopeKey}`;
}

function dailyKey(scopeKey: string) {
  return `${DAILY_PREFIX}:${scopeKey}`;
}

export function todayKey(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function readSystemDecisionCache(scopeKey: string): Record<string, SystemDecisionCacheEntry> {
  try {
    const raw = window.localStorage.getItem(cacheKey(scopeKey));
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export function writeSystemDecisionCache(scopeKey: string, entries: Record<string, SystemDecisionCacheEntry>) {
  window.localStorage.setItem(cacheKey(scopeKey), JSON.stringify(entries));
  window.dispatchEvent(new CustomEvent(SYSTEM_DECISION_CACHE_EVENT, { detail: { scopeKey } }));
}

export function writeSystemDecisionEntry(scopeKey: string, skuId: string, entry: SystemDecisionCacheEntry) {
  const entries = readSystemDecisionCache(scopeKey);
  writeSystemDecisionCache(scopeKey, { ...entries, [skuId]: entry });
}

export function getLastDailySystemDecisionDate(scopeKey: string) {
  return window.localStorage.getItem(dailyKey(scopeKey));
}

export function markDailySystemDecisionRun(scopeKey: string, dateKey = todayKey()) {
  window.localStorage.setItem(dailyKey(scopeKey), dateKey);
}

export function isDailySystemDecisionDue(scopeKey: string, now = new Date()) {
  return now.getHours() >= 9 && getLastDailySystemDecisionDate(scopeKey) !== todayKey(now);
}
