import { useState, useMemo } from 'react';
import { useReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { KpiCard } from '@/components/shared/KpiCard';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fmtPct, fmtNum, fmtUSD, positionLabel, positionStyles } from '@/lib/format';
import { Radar, ShoppingBag, TrendingDown, TrendingUp } from 'lucide-react';
import type { PricePosition } from '@/types/domain';
import { cn } from '@/lib/utils';
import { SHOPS } from '@/data/mockReport';

export default function Competitive() {
  const { data: r, isLoading } = useReport();
  const [search, setSearch] = useState('');
  if (isLoading || !r) return (<><TopBar title="Competitive Intelligence" /><PageSkeleton /></>);
  const m = r.competitor.market_overview;

  const positions = (['premium', 'above_market', 'at_market', 'below_market', 'deep_value'] as PricePosition[]).map(p => ({
    p, count: r.competitor.sku_positioning.filter(x => x.position === p).length,
  }));
  const total = positions.reduce((s, x) => s + x.count, 0);
  const filtered = useMemo(() => r.competitor.sku_positioning.filter(p =>
    !search || `${p.sku_id} ${p.product_name} ${p.brand}`.toLowerCase().includes(search.toLowerCase())
  ).slice(0, 60), [r, search]);

  return (
    <>
      <TopBar title="Competitive Intelligence" subtitle={`${m.shops_covered} Lebanese sports retailers tracked · ${m.data_freshness_hours}h freshness`} />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="SKUs Tracked" icon={ShoppingBag} value={fmtNum(m.skus_tracked)} hint={`${fmtNum(m.competitor_records)} records`} />
          <KpiCard label="Avg Price Gap" icon={Radar} variant="data" value={fmtPct(m.avg_price_gap_pct)} hint="vs market avg" />
          <KpiCard label="Overpriced" icon={TrendingUp} variant="warning" value={fmtNum(m.overpriced_skus)} hint="> 15% premium" />
          <KpiCard label="Underpriced" icon={TrendingDown} variant="success" value={fmtNum(m.underpriced_skus)} hint="margin uplift available" />
        </div>

        <div className="grid lg:grid-cols-[1.1fr_1fr] gap-6">
          <Section title="Price Position Distribution">
            <div className="space-y-3">
              {positions.map(({ p, count }) => (
                <div key={p}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className={cn('text-[11px] uppercase font-mono px-2 py-0.5 rounded', positionStyles[p])}>{positionLabel[p]}</span>
                    <span className="text-data text-[14px] font-semibold">{count} <span className="text-muted-foreground text-[11px] font-mono">({Math.round(count/total*100)}%)</span></span>
                  </div>
                  <div className="h-2 rounded-full bg-muted overflow-hidden">
                    <div className={cn('h-full', positionStyles[p].replace('text-', 'bg-').split(' ')[1] || 'bg-primary')} style={{ width: `${(count/total)*100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </Section>
          <Section title="Brand Positioning">
            <div className="space-y-2">
              {Object.entries(r.competitor.brand_summary).map(([b, v]) => (
                <div key={b} className="flex items-center justify-between p-2.5 rounded-md hover:bg-accent/40">
                  <div>
                    <div className="text-[13px] font-semibold">{b}</div>
                    <div className="text-[11px] text-muted-foreground font-mono">{v.skus} SKUs · coverage {fmtPct(v.coverage * 100, 0)}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={cn('text-[10.5px] font-mono uppercase px-2 py-0.5 rounded', positionStyles[v.position])}>{positionLabel[v.position]}</span>
                    <span className={cn('text-[13px] font-mono font-semibold w-16 text-right', v.avg_gap_pct > 0 ? 'text-decision-markdown' : 'text-decision-promote')}>
                      {v.avg_gap_pct > 0 ? '+' : ''}{v.avg_gap_pct}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </Section>
        </div>

        <Section title="Pricing Opportunities" subtitle="Top moves ranked by estimated uplift">
          <div className="grid md:grid-cols-2 gap-3">
            {r.competitor.opportunities.map(o => (
              <div key={o.sku_id} className="rounded-lg border border-border p-4 hover:border-primary/30 hover:shadow-md-soft transition">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-mono text-[10.5px] text-muted-foreground">{o.sku_id}</div>
                    <div className="text-[14px] font-semibold mt-0.5">{o.product_name}</div>
                    <div className="text-[11.5px] text-muted-foreground">{o.brand}</div>
                  </div>
                  <div className={cn('text-[10.5px] font-mono uppercase px-2 py-1 rounded', o.type === 'undercut' ? 'bg-decision-markdown-bg text-decision-markdown' : 'bg-decision-promote-bg text-decision-promote')}>
                    {o.type}
                  </div>
                </div>
                <p className="text-[12.5px] text-muted-foreground mt-2 leading-snug">{o.rationale}</p>
                <div className="grid grid-cols-3 gap-2 mt-3 pt-3 border-t border-border text-[12px] font-mono">
                  <div><div className="text-[10px] uppercase text-muted-foreground">Now</div><div>{fmtUSD(o.current_price_usd)}</div></div>
                  <div><div className="text-[10px] uppercase text-muted-foreground">Target</div><div>{fmtUSD(o.suggested_price_usd)}</div></div>
                  <div><div className="text-[10px] uppercase text-muted-foreground">Uplift</div><div className="text-decision-promote">+{fmtUSD(o.est_uplift_usd, { compact: true })}</div></div>
                </div>
              </div>
            ))}
          </div>
        </Section>

        <div className="grid lg:grid-cols-[1.6fr_1fr] gap-6">
          <Section title="SKU Positioning" subtitle="Detailed per-SKU competitive view"
            action={<input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search…" className="h-8 px-3 rounded-md border border-border bg-card text-[12px] outline-none w-44" />}
            bodyClassName="p-0">
            <div className="overflow-x-auto scrollbar-thin max-h-[520px]">
              <table className="w-full text-[12.5px]">
                <thead className="bg-surface-sunken text-[10.5px] uppercase tracking-wider text-muted-foreground sticky top-0">
                  <tr>
                    <th className="px-4 py-3 text-left">SKU</th>
                    <th className="px-4 py-3 text-left">Product</th>
                    <th className="px-4 py-3 text-right">Our</th>
                    <th className="px-4 py-3 text-right">Market</th>
                    <th className="px-4 py-3 text-right">Gap</th>
                    <th className="px-4 py-3 text-left">Position</th>
                    <th className="px-4 py-3 text-center">Comp</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(p => (
                    <tr key={p.sku_id} className="border-t border-border hover:bg-accent/40">
                      <td className="px-4 py-2 font-mono text-[11px] text-muted-foreground">{p.sku_id}</td>
                      <td className="px-4 py-2 truncate max-w-[200px]">{p.product_name}</td>
                      <td className="px-4 py-2 text-right font-mono">{fmtUSD(p.our_price_usd)}</td>
                      <td className="px-4 py-2 text-right font-mono text-muted-foreground">{fmtUSD(p.market_avg_usd)}</td>
                      <td className={cn('px-4 py-2 text-right font-mono', p.price_gap_pct > 0 ? 'text-decision-markdown' : 'text-decision-promote')}>{p.price_gap_pct > 0 ? '+' : ''}{p.price_gap_pct}%</td>
                      <td className="px-4 py-2"><span className={cn('text-[10px] font-mono uppercase px-1.5 py-0.5 rounded', positionStyles[p.position])}>{positionLabel[p.position]}</span></td>
                      <td className="px-4 py-2 text-center font-mono text-muted-foreground">{p.competitors_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
          <Section title="Shop Coverage">
            <ul className="space-y-2">
              {SHOPS.map(s => {
                const pct = 60 + Math.floor(Math.random() * 35);
                return (
                  <li key={s} className="flex items-center gap-3">
                    <div className="font-mono text-[12px] w-28">{s}</div>
                    <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                      <div className="h-full bg-gradient-data" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-[11px] font-mono text-muted-foreground w-10 text-right">{pct}%</span>
                  </li>
                );
              })}
            </ul>
          </Section>
        </div>
      </main>
    </>
  );
}
