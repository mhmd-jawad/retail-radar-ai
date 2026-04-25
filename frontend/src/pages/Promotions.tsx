import { useState } from 'react';
import { useReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { DecisionBadge } from '@/components/shared/DecisionBadge';
import { fmtPct, fmtUSD } from '@/lib/format';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Copy, Megaphone } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import type { Decision } from '@/types/domain';

export default function Promotions() {
  const { data: r, isLoading } = useReport();
  if (isLoading || !r) return (<><TopBar title="Promotions & Campaigns" /><PageSkeleton /></>);
  const p = r.promotions;
  const copy = (t: string, l: string) => { navigator.clipboard.writeText(t); toast.success(`${l} copied`); };

  return (
    <>
      <TopBar title="Promotions & Campaigns" subtitle={`${p.summary.promote_count} promote · ${p.summary.markdown_count} markdown · ${p.summary.clearance_count} clearance · ${p.summary.hold_count} hold`} />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <Tabs defaultValue="promote">
          <TabsList className="bg-surface-raised border border-border">
            <TabsTrigger value="promote">Promote ({p.promote.length})</TabsTrigger>
            <TabsTrigger value="markdown">Markdown ({p.markdown.length})</TabsTrigger>
            <TabsTrigger value="clearance">Clearance ({p.clearance.length})</TabsTrigger>
            <TabsTrigger value="hold">Hold Pricing ({p.hold_pricing.length})</TabsTrigger>
            <TabsTrigger value="seasonal">Seasonal</TabsTrigger>
          </TabsList>

          <TabsContent value="promote" className="mt-5">
            <div className="grid md:grid-cols-2 gap-4">
              {p.promote.map(item => (
                <div key={item.sku_id} className="rounded-xl border border-decision-promote/20 bg-card overflow-hidden shadow-sm-soft">
                  <div className="bg-gradient-promote text-white p-4">
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="text-[10.5px] font-mono uppercase tracking-wider text-white/70">{item.sku_id} · {item.brand}</div>
                        <div className="font-display text-[15px] font-semibold mt-1">{item.product_name}</div>
                      </div>
                      <DecisionBadge decision="PROMOTE" size="sm" />
                    </div>
                    <div className="text-[12px] text-white/85 mt-2">Expected lift: <span className="font-bold">+{item.expected_lift_pct}%</span> · {item.channels.join(' · ')}</div>
                  </div>
                  <div className="p-4 space-y-3">
                    <p className="text-[12.5px] text-muted-foreground">{item.reason}</p>
                    {item.creative ? (
                      <>
                        <div className="font-display text-[15px] font-semibold leading-tight">{item.creative.headline}</div>
                        <div className="text-[12px] text-muted-foreground">{item.creative.subheadline}</div>
                        {[
                          { l: 'Instagram', v: item.creative.instagram_post },
                          { l: 'WhatsApp (AR/EN)', v: item.creative.whatsapp_broadcast },
                        ].map(c => (
                          <div key={c.l} className="rounded-md bg-muted/40 p-2.5">
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-[10.5px] font-mono uppercase text-muted-foreground">{c.l}</span>
                              <button onClick={() => copy(c.v, c.l)} className="text-[10.5px] inline-flex items-center gap-1 text-primary"><Copy className="h-3 w-3" />Copy</button>
                            </div>
                            <p className="text-[12px] whitespace-pre-line">{c.v}</p>
                          </div>
                        ))}
                        <div className="flex gap-2 pt-2">
                          <button className="flex-1 h-9 rounded-md bg-decision-promote text-white text-[12.5px] font-semibold">{item.creative.cta_primary}</button>
                          <button className="flex-1 h-9 rounded-md border border-border text-[12.5px] font-semibold">{item.creative.cta_secondary}</button>
                        </div>
                      </>
                    ) : (
                      <div className="text-[12px] text-muted-foreground italic">Campaign creative pending — generate via EEP service.</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="markdown" className="mt-5">
            <Section bodyClassName="p-0">
              <table className="w-full text-[13px]">
                <thead className="bg-surface-sunken text-[10.5px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-left">SKU</th><th className="px-4 py-3 text-left">Product</th>
                    <th className="px-4 py-3 text-right">Now</th><th className="px-4 py-3 text-right">Discount</th>
                    <th className="px-4 py-3 text-right">New</th><th className="px-4 py-3 text-right">Margin</th>
                    <th className="px-4 py-3 text-left">Reason</th><th className="px-4 py-3 text-center">Urgency</th>
                  </tr>
                </thead>
                <tbody>
                  {p.markdown.map(m => (
                    <tr key={m.sku_id} className="border-t border-border hover:bg-accent/40">
                      <td className="px-4 py-2 font-mono text-[11px] text-muted-foreground">{m.sku_id}</td>
                      <td className="px-4 py-2 font-medium">{m.product_name}</td>
                      <td className="px-4 py-2 text-right font-mono">{fmtUSD(m.current_price_usd)}</td>
                      <td className="px-4 py-2 text-right font-mono text-decision-markdown font-semibold">-{m.suggested_discount_pct}%</td>
                      <td className="px-4 py-2 text-right font-mono">{fmtUSD(m.suggested_price_usd)}</td>
                      <td className={cn('px-4 py-2 text-right font-mono', m.margin_after_pct < 35 ? 'text-decision-clear' : '')}>{fmtPct(m.margin_after_pct, 0)}</td>
                      <td className="px-4 py-2 text-muted-foreground text-[12px]">{m.reason}</td>
                      <td className="px-4 py-2 text-center"><span className={cn('text-[10px] font-mono uppercase px-2 py-0.5 rounded', m.urgency === 'high' ? 'bg-decision-clear-bg text-decision-clear' : m.urgency === 'medium' ? 'bg-decision-markdown-bg text-decision-markdown' : 'bg-secondary')}>{m.urgency}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Section>
          </TabsContent>

          <TabsContent value="clearance" className="mt-5">
            <div className="grid md:grid-cols-2 gap-4">
              {p.clearance.map(c => (
                <div key={c.sku_id} className="rounded-xl border border-decision-clear/30 bg-card p-5">
                  <div className="flex items-center justify-between">
                    <DecisionBadge decision="CLEAR" size="lg" />
                    <span className="text-[10.5px] font-mono uppercase px-2 py-0.5 rounded bg-decision-clear text-white">{c.urgency}</span>
                  </div>
                  <div className="mt-3 text-[15px] font-semibold">{c.product_name}</div>
                  <div className="text-[11.5px] text-muted-foreground font-mono">{c.sku_id} · {c.brand}</div>
                  <div className="grid grid-cols-3 gap-2 mt-4">
                    <div><div className="text-[10px] uppercase font-mono text-muted-foreground">Stock</div><div className="text-data text-[18px]">{c.current_stock}</div></div>
                    <div><div className="text-[10px] uppercase font-mono text-muted-foreground">Age</div><div className="text-data text-[18px]">{c.age_days}d</div></div>
                    <div><div className="text-[10px] uppercase font-mono text-muted-foreground">Recover</div><div className="text-data text-[18px] text-decision-promote">{fmtUSD(c.recovered_cash_usd, { compact: true })}</div></div>
                  </div>
                </div>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="hold" className="mt-5">
            <Section bodyClassName="p-0">
              <table className="w-full text-[13px]">
                <thead className="bg-surface-sunken text-[10.5px] uppercase tracking-wider text-muted-foreground">
                  <tr><th className="px-4 py-3 text-left">SKU</th><th className="px-4 py-3 text-left">Product</th><th className="px-4 py-3 text-left">Reason</th><th className="px-4 py-3 text-right">Margin</th><th className="px-4 py-3 text-right">Velocity</th></tr>
                </thead>
                <tbody>
                  {p.hold_pricing.map(h => (
                    <tr key={h.sku_id} className="border-t border-border">
                      <td className="px-4 py-2 font-mono text-[11px] text-muted-foreground">{h.sku_id}</td>
                      <td className="px-4 py-2 font-medium">{h.product_name}</td>
                      <td className="px-4 py-2 text-muted-foreground text-[12px]">{h.reason}</td>
                      <td className="px-4 py-2 text-right font-mono text-decision-promote">{fmtPct(h.margin_pct, 0)}</td>
                      <td className="px-4 py-2 text-right font-mono">{h.velocity}/d</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Section>
          </TabsContent>

          <TabsContent value="seasonal" className="mt-5">
            <Section title="Seasonal Action Timeline">
              <div className="relative pl-6 space-y-4 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-px before:bg-border">
                {p.seasonal_actions.map((s, i) => (
                  <div key={i} className="relative">
                    <div className="absolute -left-6 top-1 h-3 w-3 rounded-full bg-primary ring-4 ring-background" />
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{s.month}</span>
                      <DecisionBadge decision={s.action as Decision} size="sm" />
                      <span className="text-[13px] font-semibold">{s.category}</span>
                    </div>
                    <p className="text-[12.5px] text-muted-foreground mt-1">{s.detail}</p>
                  </div>
                ))}
              </div>
            </Section>
          </TabsContent>
        </Tabs>
      </main>
    </>
  );
}
