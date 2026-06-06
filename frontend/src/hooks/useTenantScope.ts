import { tenantScopeKey } from '@/lib/tenantScope';
import { useAuth } from '@/store/auth';

export function useTenantScopeKey(): string {
  return useAuth((state) => tenantScopeKey(state.user));
}
