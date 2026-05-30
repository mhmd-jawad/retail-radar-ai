import { useQuery } from '@tanstack/react-query';
import { fetchReport, fetchLiveReport } from '@/lib/adapter';
import { useSettings } from '@/store/settings';

export function useReport() {
  const mode = useSettings((s) => s.mode);
  const apiBaseUrl = useSettings((s) => s.apiBaseUrl);
  return useQuery({
    queryKey: ['report', mode, apiBaseUrl],
    queryFn: fetchReport,
    staleTime: 60_000,
  });
}

export function useLiveReport() {
  const mode = useSettings((s) => s.mode);
  const apiBaseUrl = useSettings((s) => s.apiBaseUrl);
  return useQuery({
    queryKey: ['report-live', mode, apiBaseUrl],
    queryFn: fetchLiveReport,
    staleTime: 60_000,
  });
}
