import { useReport } from '@/hooks/useReport';
import { TopBar } from '@/components/layout/TopBar';
import { KpiCard } from '@/components/shared/KpiCard';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { DecisionBadge } from '@/components/shared/DecisionBadge';
import { fmtDos, fmtUSD, fmtPct, fmtNum, isUnknownDos, relativeTime } from '@/lib/format';
import {
  Boxes, Radar, DollarSign, Wallet, AlertTriangle, TrendingUp, Calendar, ArrowRight, Database,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';
import type { Decision } from '@/types/domain';
import { decisionStyles } from '@/lib/format';

const decisionGradients: Record<Decision, string> = {
  HOLD: 'bg-decision-hold',
  PROMOTE: 'bg-gradient-promote',
  MARKDOWN: 'bg-gradient-markdown',
  CLEAR: 'bg-gradient-clear',
};

export default function Overview() {
  const { data: report, isLoading } = useReport();
  if (isLoading || !report) {
    return (
      <>
        <TopBar title="Executive Overview" subtitle="Loading…" />
        <PageSkeleton />
      </>
    );
  }

  const { inventory, competitor, financial, promotions, metadata } = report;
  const skuCount = inventory.sku_analysis.length;
  const distribution: { name: Decision; value: number; color: string }[] = [
    { name: 'HOLD', value: promotions.summary.hold_count, color: 'hsl(var(--decision-hold))' },
    { name: 'PROMOTE', value: promotions.summary.promote_count, color: 'hsl(var(--decision-promote))' },
    { name: 'MARKDOWN', value: promotions.summary.markdown_count, color: 'hsl(var(--decision-markdown))' },
    { name: 'CLEAR', value: promotions.summary.clearance_count, color: 'hsl(var(--decision-clear))' },
  ];
  const total = Math.max(distribution.reduce((s, x) => s + x.value, 0), 1);
  const actionableCount = promotions.summary.promote_count + promotions.summary.markdown_count + promotions.summary.clearance_count;
  const cashRunwayMonths = financial.cashflow_health.cash_runway_months ?? 0;
  const inventoryPctOfAssets = financial.balance_sheet_health.inventory_pct_of_assets ?? 0;

  const categoryRows = Object.entries(inventory.category_summary)
    .map(([k, v]) => ({ name: k, ...v }))
    .sort((a, b) => b.value_usd - a.value_usd);
  const knownDosCount = inventory.sku_analysis.filter((s) => !isUnknownDos(s.days_of_supply)).length;
  const medianDosHint = knownDosCount > 0 ? `${fmtDos(inventory.metrics.median_days_of_supply)} median DOS` : 'No sales history yet';

  return (
    <>
      <TopBar
        title="Executive Overview"
        subtitle={`Lebanon · fresh USD · synced ${relativeTime(metadata.generated_at)}`}
        actions={
          <Link
            to="/queue"
            className="hidden md:inline-flex items-center gap-2 h-9 px-4 rounded-md bg-foreground text-background text-[12.5px] font-semibold hover:bg-foreground/90 transition"
          >
            Review queue <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        }
      />

      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        {/* Hero panel */}
        <div className="relative panel-dark rounded-2xl overflow-hidden shadow-lg-soft">
          <div className="absolute inset-0 opacity-30" style={{
            background: 'radial-gradient(800px 300px at 80% -20%, hsl(218 92% 60% / 0.4), transparent), radial-gradient(600px 280px at 10% 110%, hsl(158 65% 36% / 0.35), transparent)',
          }} />
          <div className="relative p-6 lg:p-8 grid lg:grid-cols-[1.4fr_1fr] gap-8 items-center">
            <div>
              <div className="inline-flex items-center gap-2 text-[10.5px] font-mono uppercase tracking-[0.2em] text-panel-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-decision-promote animate-pulse" /> Live Intelligence Brief
              </div>
              <h2 className="font-display text-[28px] lg:text-[34px] leading-[1.05] font-semibold text-panel-foreground mt-3 tracking-tight">
                {skuCount} SKUs analyzed.<br/>
                <span className="bg-gradient-to-r from-primary-glow to-decision-promote bg-clip-text text-transparent">
                  {actionableCount} actionable signals waiting.
                </span>
              </h2>
              <p className="text-panel-muted text-[14px] mt-3 max-w-2xl">
                {skuCount === 0 ? (
                  <>Add or import inventory to generate recommendations, pricing signals, and financial diagnostics for this shop.</>
                ) : (
                  <>
                    Cash runway at <span className="text-panel-foreground font-semibold">{cashRunwayMonths.toFixed(1)} months</span> with inventory absorbing
                    {' '}<span className="text-panel-foreground font-semibold">{inventoryPctOfAssets.toFixed(1)}%</span> of assets.
                    Review {actionableCount} inventory actions generated from this shop&apos;s live data.
                  </>
                )}
              </p>
              <div className="flex flex-wrap gap-3 mt-5">
                <Link to="/queue" className="inline-flex items-center gap-2 h-10 px-4 rounded-md bg-primary-glow text-primary-foreground text-[13px] font-semibold hover:opacity-90 transition shadow-glow">
                  Open recommendations queue
                </Link>
                <Link to="/financial" className="inline-flex items-center gap-2 h-10 px-4 rounded-md border border-panel-border text-panel-foreground text-[13px] font-medium hover:bg-white/5 transition">
                  View cashflow detail
                </Link>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {distribution.map((d) => (
                <div key={d.name} className="rounded-lg border border-panel-border bg-white/5 p-4">
                  <div className="flex items-center gap-1.5 text-[10.5px] font-mono uppercase tracking-wider text-panel-muted">
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: d.color }} />
                    {d.name}
                  </div>
                  <div className="text-data text-[26px] text-panel-foreground mt-1.5">{d.value}</div>
                  <div className="h-1 mt-2 rounded-full bg-white/5 overflow-hidden">
                    <div className={`h-full ${decisionGradients[d.name]}`} style={{ width: `${(d.value / total) * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* KPI cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="Inventory @ Cost" icon={Boxes} value={fmtUSD(inventory.metrics.inventory_value_at_cost_usd, { compact: true })}
            hint={`${fmtNum(inventory.metrics.total_units)} units · ${medianDosHint}`} />
          <KpiCard label="Cash Runway" icon={Wallet} variant="warning" value={`${cashRunwayMonths.toFixed(1)} mo`}
            hint={`Burn ${fmtUSD(financial.cashflow_health.monthly_burn_usd, { compact: true })}/mo`} trend={{ value: '-0.4 mo', direction: 'down', positive: false }} />
          <KpiCard label="Competitor Records" icon={Radar} variant="data" value={fmtNum(competitor.market_overview.competitor_records)}
            hint={`${competitor.market_overview.shops_covered} shops · ${competitor.market_overview.data_freshness_hours}h freshness`} />
          <KpiCard label="Blended Margin" icon={TrendingUp} variant="success" value={fmtPct(inventory.metrics.blended_margin_pct)}
            hint="Healthy band ≥ 45%" trend={{ value: '+0.6pp', direction: 'up' }} />
        </div>

        {/* Decision distribution + Directives */}
        <div className="grid lg:grid-cols-[1.1fr_1.4fr] gap-6">
          <Section title="Decision Distribution" subtitle={`${skuCount} SKUs across HOLD / PROMOTE / MARKDOWN / CLEAR`}>
            <div className="grid grid-cols-[1fr_1fr] gap-4 items-center">
              <div className="h-44">
                <ResponsiveContainer>
                  <PieChart>
                    <Pie data={distribution} dataKey="value" innerRadius={48} outerRadius={78} paddingAngle={2} stroke="none">
                      {distribution.map((d) => <Cell key={d.name} fill={d.color} />)}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="space-y-2">
                {distribution.map((d) => (
                  <div key={d.name} className="flex items-center justify-between gap-3 py-1.5 border-b border-border last:border-0">
                    <DecisionBadge decision={d.name} size="sm" />
                    <div className="flex items-baseline gap-2">
                      <span className="text-data text-[16px] font-semibold">{d.value}</span>
                      <span className="text-[11px] text-muted-foreground font-mono">{Math.round((d.value / total) * 100)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </Section>

          <Section title="Priority Owner Directives" subtitle="Resolved by the analytics engine — human approval required"
            action={<Link to="/promotions" className="text-[12px] text-primary font-semibold hover:underline">View all</Link>}>
            <ul className="space-y-3">
              {promotions.directives.slice(0, 5).map((d, i) => (
                <li key={i} className="flex items-start gap-3 p-3 rounded-lg border border-border hover:border-primary/30 hover:bg-accent/40 transition">
                  <div className={`h-9 w-9 shrink-0 rounded-md flex items-center justify-center text-[10px] font-mono font-semibold uppercase ${
                    d.priority === 'high' ? 'bg-decision-clear-bg text-decision-clear' :
                    d.priority === 'medium' ? 'bg-decision-markdown-bg text-decision-markdown' : 'bg-secondary text-secondary-foreground'
                  }`}>
                    {d.owner.slice(0, 3)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-[13.5px] font-semibold text-foreground">
                      {d.title}
                      <span className="text-[10px] uppercase font-mono text-muted-foreground tracking-wider">{d.owner}</span>
                    </div>
                    <p className="text-[12.5px] text-muted-foreground mt-0.5 leading-snug">{d.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          </Section>
        </div>

        {/* Alerts + Seasonal */}
        <div className="grid lg:grid-cols-[1.4fr_1fr] gap-6">
          <Section title="Alerts" subtitle="Inventory & financial signals from the analytics engine"
            action={<span className="text-[11px] font-mono text-muted-foreground">{[...inventory.alerts, ...financial.alerts].length} active</span>}>
            <ul className="divide-y divide-border -my-2">
              {[...inventory.alerts, ...financial.alerts].slice(0, 6).map((a) => (
                <li key={a.id} className="flex items-start gap-3 py-3">
                  <div className={`h-7 w-7 rounded-md flex items-center justify-center shrink-0 ${
                    a.severity === 'critical' ? 'bg-decision-clear-bg text-decision-clear' :
                    a.severity === 'high' ? 'bg-decision-markdown-bg text-decision-markdown' :
                    a.severity === 'medium' ? 'bg-amber-100 text-amber-700' : 'bg-secondary text-secondary-foreground'
                  }`}>
                    <AlertTriangle className="h-3.5 w-3.5" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-semibold text-foreground">{a.title}</div>
                    <p className="text-[12px] text-muted-foreground mt-0.5">{a.detail}</p>
                  </div>
                  <div className="text-[10.5px] font-mono text-muted-foreground shrink-0">{relativeTime(a.created_at)}</div>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Seasonal Calendar" subtitle="Lebanese retail rhythm">
            <ul className="space-y-2">
              {promotions.seasonal_actions.slice(0, 6).map((s, i) => (
                <li key={i} className="flex items-center gap-3 py-1.5">
                  <div className="h-9 w-9 rounded-md bg-accent text-accent-foreground flex flex-col items-center justify-center shrink-0">
                    <Calendar className="h-3 w-3" />
                    <span className="text-[9px] font-mono mt-0.5">{s.month}</span>
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[12.5px] font-semibold">{s.category}</span>
                      <DecisionBadge decision={s.action as Decision} size="sm" />
                    </div>
                    <p className="text-[11.5px] text-muted-foreground truncate">{s.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          </Section>
        </div>

        {/* Category health + opportunities */}
        <div className="grid lg:grid-cols-[1.4fr_1fr] gap-6">
          <Section title="Category Health Snapshot" subtitle="Inventory value, margin, and DOS by category">
            <div className="h-64 -mx-2">
              <ResponsiveContainer>
                <BarChart data={categoryRows} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false} />
                  <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} tickLine={false} axisLine={false}
                    tickFormatter={(v) => `$${Math.round(v / 1000)}k`} />
                  <Tooltip contentStyle={{ background: 'hsl(var(--popover))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                    formatter={(v: number) => fmtUSD(v, { compact: true })} />
                  <Bar dataKey="value_usd" fill="hsl(var(--chart-1))" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Section>

          <Section title="Top Pricing Opportunities" subtitle="Estimated uplift when accepted"
            action={<Link to="/competitive" className="text-[12px] text-primary font-semibold hover:underline">All</Link>}>
            <ul className="space-y-2">
              {competitor.opportunities.slice(0, 5).map((o) => (
                <li key={o.sku_id} className="flex items-center gap-3 p-2.5 rounded-lg hover:bg-accent/40 transition">
                  <div className={`h-9 w-9 rounded-md flex items-center justify-center text-[10px] font-mono font-bold uppercase ${
                    o.type === 'undercut' ? 'bg-decision-markdown-bg text-decision-markdown' : 'bg-decision-promote-bg text-decision-promote'
                  }`}>
                    {o.type === 'undercut' ? '↓' : '↑'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-semibold truncate">{o.product_name}</div>
                    <div className="text-[11px] text-muted-foreground font-mono">{o.sku_id} · {o.brand}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-[13px] font-semibold text-data text-decision-promote">+{fmtUSD(o.est_uplift_usd, { compact: true })}</div>
                    <div className="text-[10.5px] font-mono text-muted-foreground">→ {fmtUSD(o.suggested_price_usd)}</div>
                  </div>
                </li>
              ))}
            </ul>
          </Section>
        </div>

        {/* Quick links */}
        <Section title="Jump In" subtitle="Deep-dive into a specific intelligence layer">
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {[
              { to: '/queue', icon: Database, label: 'Recommendations', count: String(skuCount) },
              { to: '/inventory', icon: Boxes, label: 'Inventory & Stock', count: `${inventory.metrics.dead_stock_skus} dead` },
              { to: '/competitive', icon: Radar, label: 'Competitive', count: `${competitor.market_overview.shops_covered} shops` },
              { to: '/promotions', icon: DollarSign, label: 'Promotions', count: `${promotions.promote.length} ready` },
              { to: '/financial', icon: Wallet, label: 'Financial', count: `${financial.cashflow_health.cash_runway_months}mo runway` },
            ].map((q) => (
              <Link key={q.to} to={q.to} className="group p-4 rounded-lg border border-border hover:border-primary/40 hover:shadow-md-soft transition-all">
                <q.icon className="h-5 w-5 text-primary mb-2" />
                <div className="text-[13px] font-semibold">{q.label}</div>
                <div className="text-[11px] text-muted-foreground font-mono mt-0.5">{q.count}</div>
                <div className="mt-2 text-[11px] text-primary opacity-0 group-hover:opacity-100 transition flex items-center gap-1">
                  Open <ArrowRight className="h-3 w-3" />
                </div>
              </Link>
            ))}
          </div>
        </Section>
      </main>
    </>
  );
}
