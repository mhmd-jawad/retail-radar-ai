import { useEffect } from 'react';
import { useAuth } from '@/store/auth';
import { useSettings } from '@/store/settings';

export function AuthModeSync() {
  const token = useAuth((state) => state.token);
  const mode = useSettings((state) => state.mode);
  const setMode = useSettings((state) => state.setMode);

  useEffect(() => {
    if (token && mode !== 'eep-live') {
      setMode('eep-live');
    }
  }, [mode, setMode, token]);

  return null;
}
