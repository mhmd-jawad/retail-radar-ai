import { useEffect, useState } from 'react';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { pingEEP, pingIE1, pingIE2, pingIE3, fetchScrapeRuns, fetchCompetitorLatest } from '@/lib/adapter';
import { useQuery } from '@tanstack/react-query';
import { cn } from '@/lib/utils';
import { Radio } from 'lucide-react';
import { relativeTime, fmtNum, fmtUSD } from '@/lib/format';

const services = [
  { key: 'ie1', name: 'IE1 Market Intelligence', desc: 'Active · port 8001' },
  { key: 'ie2', name: 'IE2 Decision Intelligence', desc: 'Active · port 8002' },
  { key: 'ie3', name: 'IE3 Creative Intelligence', desc: 'Active · port 8003' },
  { key: 'eep', name: 'EEP Orchestrator', desc: 'Active dashboard API · port 8000' },
];

export default function Ops() {
  const [eepHealth, setEepHealth] = useState<{ ok: boolean; latency_ms: number; detail?: string } | null>(null);
  const [ie1Health, setIe1Health] = useState<{ ok: boolean; latency_ms: number; detail?: string } | null>(null);
  const [ie2Health, setIe2Health] = useState<{ ok: boolean; latency_ms: number; detail?: string } | null>(null);
  const [ie3Health, setIe3Health] = useState<{ ok: boolean; latency_ms: number; detail?: string } | null>(null);
  const { data: runs } = useQuery({ queryKey: ['runs'], queryFn: fetchScrapeRuns });
  const { data: latest } = useQuery({ queryKey: ['latest'], queryFn: fetchCompetitorLatest });

  useEffect(() => {
    pingEEP().then(setEepHealth);
    pingIE1().then(setIe1Health);
    pingIE2().then(setIe2Health);
    pingIE3().then(setIe3Health);
  }, []);

  return (
    <>
      <TopBar title="Ops & Data Pipeline" subtitle="Service health, scraper runs, and competitor sync state" />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
          {services.map(s => {
            const isIe1 = s.key === 'ie1';
            const isIe2 = s.key === 'ie2';
            const isIe3 = s.key === 'ie3';
            const isEep = s.key === 'eep';
            const health = isEep ? eepHealth : isIe1 ? ie1Health : isIe2 ? ie2Health : isIe3 ? ie3Health : null;
            const live = health?.ok === true;
            const checking = !health;
            return (
              <div key={s.key} className="rounded-xl border p-5 shadow-sm-soft bg-card border-border">
                <div className="flex items-center justify-between">
                  <Radio className={cn('h-5 w-5', live ? 'text-decision-promote' : 'text-muted-foreground')} />
                  <span className={cn('text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded',
                    live ? 'bg-decision-promote-bg text-decision-promote' :
                    checking ? 'bg-secondary text-secondary-foreground' :
                    'bg-decision-clear-bg text-decision-clear')}>
                    {checking ? 'checking' : live ? 'live' : 'down'}
                  </span>
                </div>
                <div className="mt-3 text-[14px] font-semibold">{s.name}</div>
                <div className="text-[11.5px] text-muted-foreground mt-1">{s.desc}</div>
                {health && (
                  <div className="text-[11px] font-mono text-muted-foreground mt-2">{health.latency_ms}ms · {health.detail}</div>
                )}
              </div>
            );
          })}
        </div>

        <Section title="Scrape Runs" subtitle="Latest competitor scraper executions across 7 Lebanese shops" bodyClassName="p-0">
          <table className="w-full text-[13px]">
            <thead className="bg-surface-sunken text-[10.5px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-4 py-3 text-left">Shop</th>
                <th className="px-4 py-3 text-left">Started</th>
                <th className="px-4 py-3 text-right">Items</th>
                <th className="px-4 py-3 text-right">Valid</th>
                <th className="px-4 py-3 text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {runs?.map(r => (
                <tr key={r.id} className="border-t border-border">
                  <td className="px-4 py-2.5 font-mono">{r.shop}</td>
                  <td className="px-4 py-2.5 font-mono text-[11.5px] text-muted-foreground">{relativeTime(r.started_at)}</td>
                  <td className="px-4 py-2.5 text-right font-mono">{fmtNum(r.items_scraped)}</td>
                  <td className="px-4 py-2.5 text-right font-mono">{fmtNum(r.valid_rows)}</td>
                  <td className="px-4 py-2.5">
                    <span className={cn('text-[10.5px] font-mono uppercase px-2 py-0.5 rounded',
                      r.status === 'success' ? 'bg-decision-promote-bg text-decision-promote' :
                      r.status === 'partial' ? 'bg-decision-markdown-bg text-decision-markdown' :
                      r.status === 'failed' ? 'bg-decision-clear-bg text-decision-clear' : 'bg-secondary')}>
                      {r.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>

        <Section title="competitor_products_latest" subtitle="Most recent snapshot per shop · supabase-ready" bodyClassName="p-0">
          <table className="w-full text-[13px]">
            <thead className="bg-surface-sunken text-[10.5px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-4 py-3 text-left">Shop</th>
                <th className="px-4 py-3 text-left">Product</th>
                <th className="px-4 py-3 text-left">Brand</th>
                <th className="px-4 py-3 text-right">Price</th>
                <th className="px-4 py-3 text-center">Sale</th>
                <th className="px-4 py-3 text-center">Stock</th>
                <th className="px-4 py-3 text-left">Last Seen</th>
              </tr>
            </thead>
            <tbody>
              {latest?.slice(0, 24).map(p => (
                <tr key={`${p.shop}-${p.external_id}`} className="border-t border-border">
                  <td className="px-4 py-2 font-mono">{p.shop}</td>
                  <td className="px-4 py-2">{p.product_name}</td>
                  <td className="px-4 py-2 text-muted-foreground">{p.brand}</td>
                  <td className="px-4 py-2 text-right font-mono">{fmtUSD(p.price_usd)}</td>
                  <td className="px-4 py-2 text-center">{p.on_sale ? '🟢' : '—'}</td>
                  <td className="px-4 py-2 text-center">{p.in_stock ? '✓' : '✕'}</td>
                  <td className="px-4 py-2 font-mono text-[11px] text-muted-foreground">{relativeTime(p.last_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      </main>
    </>
  );
}
