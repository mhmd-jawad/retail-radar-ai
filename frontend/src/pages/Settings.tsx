import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { useSettings } from '@/store/settings';
import { modeLabel } from '@/lib/adapter';
import type { DataMode } from '@/types/domain';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';

const modes: DataMode[] = ['mock-report', 'ie2-live', 'eep-live', 'supabase-ready'];

export default function SettingsPage() {
  const s = useSettings();

  return (
    <>
      <TopBar title="Settings" subtitle="Data sources, API endpoints, and local preferences" />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in max-w-3xl">
        <Section title="Data Source Mode" subtitle="Switch between mock data, IE2 live, EEP live, or Supabase-ready">
          <div className="grid md:grid-cols-2 gap-3">
            {modes.map(m => (
              <button key={m} onClick={() => s.setMode(m)} className={cn('text-left p-4 rounded-lg border-2 transition', s.mode === m ? 'border-primary bg-accent' : 'border-border hover:border-primary/30')}>
                <div className="flex items-center justify-between">
                  <span className="font-display font-semibold text-[14px]">{modeLabel(m)}</span>
                  {s.mode === m && <span className="h-2 w-2 rounded-full bg-primary" />}
                </div>
                <p className="text-[12px] text-muted-foreground mt-1">
                  {m === 'mock-report' && 'Local seeded data — works offline. Default for demos.'}
                  {m === 'ie2-live' && 'Calls IE2 service at port 8002 with X-API-Key header.'}
                  {m === 'eep-live' && 'Calls EEP for live report, ops, recommendation, and tenant data.'}
                  {m === 'supabase-ready' && 'Supabase repository for scrape_runs and competitor snapshots.'}
                </p>
              </button>
            ))}
          </div>
        </Section>

        <Section title="API Endpoints">
          <div className="space-y-3">
            <Field label="IE2 Base URL" value={s.ie2BaseUrl} onChange={s.setIe2BaseUrl} placeholder="/ie2" />
            <Field label="IE3 Campaign Creative URL" value={s.ie3BaseUrl} onChange={s.setIe3BaseUrl} placeholder="/ie3" />
            <Field label="EEP / API Base URL" value={s.apiBaseUrl} onChange={s.setApiBaseUrl} placeholder="blank for Docker, http://localhost:8000 for Vite" />
            <Field label="API Key (X-API-Key)" value={s.apiKey} onChange={s.setApiKey} placeholder="ie2-local-postman-key" />
            <Field label="Store WhatsApp Number" value={s.whatsappNumber} onChange={s.setWhatsappNumber} placeholder="96170000000 (country code + number, no +)" />
          </div>
        </Section>

        <Section title="Local State">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[13.5px] font-semibold">Reset recommendation actions</div>
              <p className="text-[12px] text-muted-foreground mt-0.5">Clears all local approve/edit/reject/snooze actions.</p>
            </div>
            <button onClick={() => { s.resetRecs(); toast.success('Local actions reset'); }} className="h-9 px-4 rounded-md border border-decision-clear/30 text-decision-clear text-[12.5px] font-semibold">
              Reset
            </button>
          </div>
        </Section>

        <Section title="Environment Variables" subtitle="Override at build time">
          <pre className="text-[12px] font-mono p-4 rounded-md bg-panel text-panel-foreground overflow-x-auto">
{`VITE_DATA_MODE=eep-live
VITE_API_BASE_URL=
VITE_IE2_BASE_URL=/ie2
VITE_IE3_BASE_URL=/ie3
VITE_API_KEY=ie2-local-postman-key`}
          </pre>
        </Section>
      </main>
    </>
  );
}

function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div>
      <label className="text-[11px] uppercase tracking-wider font-mono text-muted-foreground">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="mt-1 w-full h-10 px-3 rounded-md border border-border bg-card font-mono text-[13px] outline-none focus:border-primary" />
    </div>
  );
}
