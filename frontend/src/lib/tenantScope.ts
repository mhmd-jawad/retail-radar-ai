import type { AuthUser } from '@/types/domain';

export const ANONYMOUS_TENANT_SCOPE = 'anonymous';

export function tenantScopeKey(user?: AuthUser | null): string {
  return user?.tenant_id || user?.tenant_slug || user?.email || ANONYMOUS_TENANT_SCOPE;
}

export function scopedSkuKey(skuId: string, tenantScope: string): string {
  return `${tenantScope}::${skuId}`;
}
