import { useReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { KpiCard } from '@/components/shared/KpiCard';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fmtNum, fmtPct, fmtUSD } from '@/lib/format';
import { Boxes, AlertTriangle, Skull, Activity } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid, Cell } from 'recharts';
import { cn } from '@/lib/utils';

export default function Inventory() {
  const { data: r, isLoading } = useReport();
  if (isLoading || !r) return (<><TopBar title="Inventory Health" /><PageSkeleton /></>);
  const m = r.inventory.metrics;

  const dosBands = [
    { band: '≤ 21 (Critical)', count: r.inventory.sku_analysis.filter(s => s.days_of_supply <= 21).length, color: 'hsl(var(--decision-clear))' },
    { band: '22–44', count: r.inventory.sku_analysis.filter(s => s.days_of_supply > 21 && s.days_of_supply < 45).length, color: 'hsl(var(--decision-markdown))' },
    { band: '45–90 (Healthy)', count: r.inventory.sku_analysis.filter(s => s.days_of_supply >= 45 && s.days_of_supply <= 90).length, color: 'hsl(var(--decision-promote))' },
    { band: '91–180 (Excess)', count: r.inventory.sku_analysis.filter(s => s.days_of_supply > 90 && s.days_of_supply <= 180).length, color: 'hsl(var(--decision-markdown))' },
    { band: '> 180 (Dead)', count: r.inventory.sku_analysis.filter(s => s.days_of_supply > 180).length, color: 'hsl(var(--decision-clear))' },
  ];
  const watchlist = r.inventory.sku_analysis.filter(s => s.days_of_supply <= 30).slice(0, 12);

  return (
    <>
      <TopBar title="Inventory Health" subtitle="Days of supply, dead stock and replenishment posture" />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="Total SKUs" icon={Boxes} value={fmtNum(m.total_skus)} hint={`${fmtNum(m.total_units)} units`} />
          <KpiCard label="Healthy" icon={Activity} variant="success" value={fmtNum(m.healthy_skus)} hint="DOS 45–90" />
          <KpiCard label="Excess Stock" icon={AlertTriangle} variant="warning" value={fmtNum(m.excess_stock_skus)} hint="DOS > 90" />
          <KpiCard label="Dead Stock" icon={Skull} variant="danger" value={fmtNum(m.dead_stock_skus)} hint="DOS > 180" />
        </div>

        <div className="grid lg:grid-cols-[1.3fr_1fr] gap-6">
          <Section title="Days of Supply Distribution" subtitle="Across 350 active SKUs">
            <div className="h-72 -mx-2">
              <ResponsiveContainer>
                <BarChart data={dosBands} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="band" stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} />
                  <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ background: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }} />
                  <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                    {dosBands.map((d, i) => <Cell key={i} fill={d.color} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Section>
          <Section title="Inventory Value" subtitle="Cost vs retail">
            <div className="space-y-4">
              <Bar2 label="At cost" value={m.inventory_value_at_cost_usd} max={m.inventory_value_at_retail_usd} color="bg-decision-hold" />
              <Bar2 label="At retail" value={m.inventory_value_at_retail_usd} max={m.inventory_value_at_retail_usd} color="bg-gradient-data" />
              <div className="rounded-lg bg-decision-promote-bg p-3 mt-4">
                <div className="text-[11px] uppercase font-mono tracking-wider text-decision-promote">Implied gross profit</div>
                <div className="text-data text-[24px] text-decision-promote mt-1">
                  {fmtUSD(m.inventory_value_at_retail_usd - m.inventory_value_at_cost_usd, { compact: true })}
                </div>
                <div className="text-[12px] text-muted-foreground mt-1">at {fmtPct(m.blended_margin_pct)} blended margin</div>
              </div>
            </div>
          </Section>
        </div>

        <Section title="Category Comparison" bodyClassName="p-0">
          <div className="overflow-x-auto scrollbar-thin">
            <table className="w-full text-[13px]">
              <thead className="bg-surface-sunken text-[10.5px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 text-left">Category</th>
                  <th className="px-4 py-3 text-right">SKUs</th>
                  <th className="px-4 py-3 text-right">Units</th>
                  <th className="px-4 py-3 text-right">Value</th>
                  <th className="px-4 py-3 text-right">Margin</th>
                  <th className="px-4 py-3 text-right">Median DOS</th>
                  <th className="px-4 py-3 text-right">Health</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(r.inventory.category_summary).sort((a, b) => b[1].value_usd - a[1].value_usd).map(([k, v]) => (
                  <tr key={k} className="border-t border-border hover:bg-accent/40">
                    <td className="px-4 py-2.5 font-semibold">{k}</td>
                    <td className="px-4 py-2.5 text-right font-mono">{v.skus}</td>
                    <td className="px-4 py-2.5 text-right font-mono">{fmtNum(v.units)}</td>
                    <td className="px-4 py-2.5 text-right font-mono">{fmtUSD(v.value_usd, { compact: true })}</td>
                    <td className={cn('px-4 py-2.5 text-right font-mono', v.avg_margin_pct >= 45 ? 'text-decision-promote' : v.avg_margin_pct < 35 ? 'text-decision-clear' : '')}>{fmtPct(v.avg_margin_pct, 0)}</td>
                    <td className="px-4 py-2.5 text-right font-mono">{v.median_dos}d</td>
                    <td className="px-4 py-2.5 text-right">
                      <div className="inline-flex items-center gap-2">
                        <div className="h-1.5 w-16 rounded-full bg-muted overflow-hidden">
                          <div className={cn('h-full', v.health_score >= 70 ? 'bg-decision-promote' : v.health_score >= 50 ? 'bg-decision-markdown' : 'bg-decision-clear')} style={{ width: `${v.health_score}%` }} />
                        </div>
                        <span className="font-mono text-[12px]">{v.health_score}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        <div className="grid lg:grid-cols-[1.4fr_1fr] gap-6">
          <Section title="Stockout Watchlist" subtitle="DOS ≤ 30 days">
            <ul className="space-y-1.5">
              {watchlist.map(s => (
                <li key={s.sku_id} className="flex items-center gap-3 p-2.5 rounded-md hover:bg-accent/40">
                  <div className="font-mono text-[10.5px] text-muted-foreground w-20">{s.sku_id}</div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-medium truncate">{s.product_name}</div>
                    <div className="text-[11px] text-muted-foreground">{s.brand} · {s.category}</div>
                  </div>
                  <div className={cn('text-[12px] font-mono font-semibold', s.days_of_supply <= 21 ? 'text-decision-clear' : 'text-decision-markdown')}>{s.days_of_supply}d</div>
                  <div className="text-[11px] text-muted-foreground font-mono w-12 text-right">{s.current_stock} u</div>
                </li>
              ))}
            </ul>
          </Section>
          <Section title="Inventory Alerts">
            <ul className="space-y-2">
              {r.inventory.alerts.map(a => (
                <li key={a.id} className="flex items-start gap-3 p-3 rounded-lg border border-border">
                  <AlertTriangle className={cn('h-4 w-4 shrink-0 mt-0.5', a.severity === 'critical' ? 'text-decision-clear' : a.severity === 'high' ? 'text-decision-markdown' : 'text-amber-600')} />
                  <div>
                    <div className="text-[13px] font-semibold">{a.title}</div>
                    <p className="text-[12px] text-muted-foreground mt-0.5">{a.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          </Section>
        </div>
      </main>
    </>
  );
}

function Bar2({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-[12.5px] font-medium">{label}</span>
        <span className="text-data text-[16px] font-semibold">{fmtUSD(value, { compact: true })}</span>
      </div>
      <div className="h-3 rounded-full bg-muted overflow-hidden">
        <div className={cn('h-full', color)} style={{ width: `${(value / max) * 100}%` }} />
      </div>
    </div>
  );
}
