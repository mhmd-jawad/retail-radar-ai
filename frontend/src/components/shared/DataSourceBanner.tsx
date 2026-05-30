import { cn } from '@/lib/utils';
import { Info } from 'lucide-react';
import { useSettings } from '@/store/settings';

/**
 * Shown on the Financial page when the user is NOT in eep-live mode.
 * Prompts them to switch to EEP Live in Settings to see real inventory data.
 */
export function DataSourceBanner() {
  const mode = useSettings(s => s.mode);
  if (mode === 'eep-live') return null;

  return (
    <div className={cn(
      'flex items-start gap-3 px-4 py-3 rounded-xl border',
      'border-primary/20 bg-primary/5 text-[12.5px]',
    )}>
      <Info className="h-4 w-4 mt-0.5 text-primary shrink-0" />
      <span>
        <span className="font-semibold text-primary">Demo data</span>
        {' '}— Switch to{' '}
        <span className="font-semibold">EEP Live</span> mode in{' '}
        <span className="font-semibold">Settings</span> to load live financial data directly from your inventory database.
      </span>
    </div>
  );
}
