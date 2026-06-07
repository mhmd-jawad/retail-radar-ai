import { useQuery } from '@tanstack/react-query';
import { fetchReport, fetchLiveReport } from '@/lib/adapter';
import { useSettings } from '@/store/settings';
import { useAuth } from '@/store/auth';

export function useReport() {
  const mode = useSettings((s) => s.mode);
  const apiBaseUrl = useSettings((s) => s.apiBaseUrl);
  const token = useAuth((s) => s.token);
  const tenantId = useAuth((s) => s.user?.tenant_id);
  return useQuery({
    queryKey: ['report', mode, apiBaseUrl, tenantId],
    queryFn: token || mode === 'eep-live' ? fetchLiveReport : fetchReport,
    staleTime: 60_000,
  });
}

export function useLiveReport() {
  const mode = useSettings((s) => s.mode);
  const apiBaseUrl = useSettings((s) => s.apiBaseUrl);
  const tenantId = useAuth((s) => s.user?.tenant_id);
  return useQuery({
    queryKey: ['report-live', mode, apiBaseUrl, tenantId],
    queryFn: fetchLiveReport,
    staleTime: 60_000,
  });
}
