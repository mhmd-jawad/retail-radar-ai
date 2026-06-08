import { Link } from 'react-router-dom';
import { useRef } from 'react';
import {
  Radar, ArrowRight, Activity, ShieldCheck, Sparkles, Boxes, Megaphone, Wallet,
  ListChecks, ChevronLeft, ChevronRight, Database,
  CircleDot, Pause, TrendingUp, Tag, Flame,
} from 'lucide-react';
import { ShaderBackground } from '@/components/ui/animated-shader-hero';
import { cn } from '@/lib/utils';

const SHOPS = [
  { id: 'adidas_lb', name: 'Adidas LB', tone: 'official' },
  { id: 'mikesport', name: 'Mike Sport', tone: 'multi-brand' },
  { id: 'tchooz', name: 'Tchooz', tone: 'lifestyle' },
  { id: 'shoesworld', name: 'Shoes World', tone: 'footwear' },
  { id: 'citysport', name: 'City Sport', tone: 'multi-brand' },
  { id: 'kix', name: 'KIX', tone: 'sneaker' },
  { id: 'marka_store', name: 'Marka Store', tone: 'curated' },
];

const MODULES = [
  { to: '/queue', icon: ListChecks, title: 'Recommendations Queue', desc: 'Approve HOLD / MARKDOWN / PROMOTE / CLEAR per SKU.', status: 'live' },
  { to: '/inventory', icon: Boxes, title: 'Inventory & Stock', desc: 'Add SKUs, bulk import inventory, and track stock health.', status: 'live' },
  { to: '/competitive', icon: Radar, title: 'Competitive Intelligence', desc: 'Price gaps across 7 Lebanese sportswear shops.', status: 'live' },
  { to: '/promotions', icon: Megaphone, title: 'Promotions & Campaigns', desc: 'Markdown ladders, seasonal pushes, ad creatives.', status: 'partial' },
  { to: '/financial', icon: Wallet, title: 'Financial Health', desc: 'Runway, liquidity, working capital.', status: 'live' },
];

const SERVICES = [
  { name: 'Report Analytics Engine', status: 'live', desc: 'Inventory · Competitor · Financial · Promotions JSON' },
  { name: 'IE2 — Decision Intelligence', status: 'live', desc: 'FastAPI on :8002 · /recommend' },
  { name: 'IE1 — Forecasting', status: 'planned', desc: 'Demand & seasonality forecasts (in design)' },
  { name: 'IE3 — Creative Generation', status: 'planned', desc: 'Ad copy, IG/FB/WhatsApp variants' },
  { name: 'EEP — Orchestrator', status: 'partial', desc: 'Unified API on :8000 for report, ops, and recommendation delivery' },
  { name: 'Competitor Scraping Pipeline', status: 'live', desc: '7 shops · 37,102 records · Supabase-ready' },
];

const SHOP_SERVICES = [
  { name: 'Business Analytics', status: 'live', desc: 'Inventory, competitor, financial, and promotion signals in one workspace.' },
  { name: 'Decision Recommendations', status: 'live', desc: 'SKU-level hold, markdown, promote, and clearance guidance.' },
  { name: 'Demand Forecasting', status: 'planned', desc: 'Demand and seasonality forecasts for future planning.' },
  { name: 'Campaign Creative', status: 'planned', desc: 'Ad copy and WhatsApp campaign variants for approved promotions.' },
  { name: 'Tenant Data Sync', status: 'live', desc: 'Live shop data connected to the dashboard and recommendation queue.' },
  { name: 'Competitor Tracking', status: 'live', desc: 'Market snapshots across selected Lebanese sportswear competitors.' },
];

const ACTIONS = [
  { key: 'HOLD', icon: Pause, tone: 'hold', desc: 'Pricing is healthy. Maintain position and monitor.' },
  { key: 'MARKDOWN', icon: Tag, tone: 'markdown', desc: 'Tiered discounts to defend margin and move stock.' },
  { key: 'PROMOTE', icon: TrendingUp, tone: 'promote', desc: 'Push winning SKUs with creative & paid spend.' },
  { key: 'CLEAR', icon: Flame, tone: 'clear', desc: 'Aggressive clearance to free cash and shelf space.' },
];

const KPIS = [
  { label: 'Analyzed products', value: '350' },
  { label: 'Competitor records', value: '37,102' },
  { label: 'Hold', value: '86', tone: 'hold' },
  { label: 'Promote', value: '106', tone: 'promote' },
  { label: 'Markdown', value: '156', tone: 'markdown' },
  { label: 'Clearance', value: '2', tone: 'clear' },
  { label: 'Cash runway', value: '3.0 mo' },
  { label: 'Inventory % of assets', value: '82.6%' },
  { label: 'Overpriced SKUs', value: '52' },
  { label: 'Underpriced SKUs', value: '44' },
  { label: 'Critical stockouts', value: '0' },
];

function StatusDot({ status }: { status: string }) {
  const map: Record<string, string> = {
    live: 'bg-decision-promote shadow-[0_0_10px_hsl(var(--decision-promote)/0.7)]',
    partial: 'bg-decision-markdown shadow-[0_0_10px_hsl(var(--decision-markdown)/0.7)]',
    planned: 'bg-decision-hold',
  };
  return <span className={cn('h-2 w-2 rounded-full', map[status] || map.planned)} />;
}

function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = { live: 'Live', partial: 'Partial', planned: 'Planned' };
  const tones: Record<string, string> = {
    live: 'border-decision-promote/40 text-decision-promote bg-decision-promote-bg',
    partial: 'border-decision-markdown/40 text-decision-markdown bg-decision-markdown-bg',
    planned: 'border-border text-muted-foreground bg-muted/40',
  };
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10.5px] font-mono uppercase tracking-wider', tones[status])}>
      <StatusDot status={status} />
      {labels[status]}
    </span>
  );
}

function ToneBadge({ tone }: { tone: string }) {
  const map: Record<string, string> = {
    hold: 'bg-decision-hold-bg text-decision-hold border-decision-hold/30',
    promote: 'bg-decision-promote-bg text-decision-promote border-decision-promote/40',
    markdown: 'bg-decision-markdown-bg text-decision-markdown border-decision-markdown/40',
    clear: 'bg-decision-clear-bg text-decision-clear border-decision-clear/40',
  };
  return <span className={cn('px-2 py-0.5 rounded-full border text-[10px] font-mono uppercase tracking-wider', map[tone])}>{tone}</span>;
}

export default function Landing() {
  const railRef = useRef<HTMLDivElement>(null);
  const scrollRail = (dir: 1 | -1) => {
    railRef.current?.scrollBy({ left: dir * 380, behavior: 'smooth' });
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* ===== Top Nav (transparent over hero) ===== */}
      <header className="absolute top-0 inset-x-0 z-30">
        <div className="max-w-7xl mx-auto px-6 lg:px-10 h-20 flex items-center justify-between">
          <div className="flex items-center gap-3 animate-fade-in-down">
            <div className="relative h-12 w-12 rounded-xl overflow-hidden flex items-center justify-center shadow-glow-sm">
              <img src="/logo.png" alt="Retail Radar AI" className="h-12 w-12 object-contain drop-shadow-[0_0_16px_hsl(28_96%_56%/.5)]" />
              <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-decision-promote ring-2 ring-background animate-pulse" />
            </div>
            <div className="leading-tight">
              <div className="font-display font-bold text-[16px] tracking-tight">Retail Radar AI</div>
              <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">Powered by StylePulse</div>
            </div>
          </div>
          <nav className="hidden md:flex items-center gap-6 text-[13px] text-muted-foreground animate-fade-in-down animation-delay-200">
            <a href="#modules" className="hover:text-foreground transition-colors">Modules</a>
            <a href="#status" className="hover:text-foreground transition-colors">Status</a>
            <a href="#data" className="hover:text-foreground transition-colors">Data</a>
            <a href="#snapshot" className="hover:text-foreground transition-colors">Snapshot</a>
          </nav>
          <Link to="/overview" className="pill-cta text-[13px] py-2 px-4 animate-fade-in-down animation-delay-300">
            Enter Dashboard <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </header>

      {/* ===== HERO ===== */}
      <section className="relative min-h-[100vh] flex items-center justify-center overflow-hidden">
        <ShaderBackground />
        <div className="relative z-10 max-w-5xl mx-auto px-6 text-center pt-24">
          {/* Brand logo */}
          <img
            src="/logo.png"
            alt="Retail Radar AI"
            className="mx-auto mb-8 h-28 w-28 md:h-36 md:w-36 object-contain drop-shadow-[0_0_40px_hsl(28_96%_56%/.55)] animate-fade-in-down"
          />
          {/* Trust badge */}
          <div className="inline-flex items-center gap-2 rounded-full border border-amber-500/25 bg-amber-500/5 backdrop-blur-md px-4 py-1.5 text-[12px] text-amber-200/90 animate-fade-in-down">
            <ShieldCheck className="h-3.5 w-3.5 text-amber-300" />
            <span className="font-mono uppercase tracking-[0.18em] text-[10.5px]">Lebanon · Sports Retail · B2B Intelligence</span>
            <span className="h-1 w-1 rounded-full bg-amber-300/60" />
            <span className="text-amber-100/80">v0.9 preview</span>
          </div>

          <h1 className="font-display font-extrabold tracking-tight text-5xl md:text-7xl lg:text-[88px] leading-[0.95] mt-8 animate-fade-in-up animation-delay-200">
            <span className="block text-foreground/95">Pricing, stock & competitor</span>
            <span className="block text-gradient-warm">intelligence, in one signal.</span>
          </h1>

          <p className="mt-7 text-lg md:text-xl text-muted-foreground max-w-3xl mx-auto leading-relaxed animate-fade-in-up animation-delay-400">
            Retail Radar AI continuously analyzes inventory health, competitor moves, seasonality and cash position
            for Lebanese multi-brand sportswear retailers — and tells you exactly which SKUs to{' '}
            <span className="text-decision-hold font-semibold">hold</span>,{' '}
            <span className="text-decision-markdown font-semibold">mark down</span>,{' '}
            <span className="text-decision-promote font-semibold">promote</span> or{' '}
            <span className="text-decision-clear font-semibold">clear</span>.
          </p>

          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-3 animate-fade-in-up animation-delay-600">
            <Link to="/overview" className="pill-cta">
              Enter Dashboard <ArrowRight className="h-4 w-4" />
            </Link>
            <a href="#modules" className="pill-ghost">
              <Sparkles className="h-4 w-4" /> Explore Features
            </a>
          </div>

          <div className="mt-16 flex items-center justify-center gap-8 text-[12px] text-muted-foreground/70 font-mono uppercase tracking-[0.16em] animate-fade-in-up animation-delay-800">
            <span className="flex items-center gap-2"><CircleDot className="h-3 w-3 text-decision-promote" />IE2 live</span>
            <span className="hidden sm:flex items-center gap-2"><Database className="h-3 w-3" />7 shops</span>
            <span className="flex items-center gap-2"><Activity className="h-3 w-3 text-amber-400" />37,102 records</span>
          </div>
        </div>
      </section>

      {/* ===== MODULE RAIL (swipeable) ===== */}
      <section id="modules" className="relative py-24 px-6">
        <div className="max-w-7xl mx-auto">
          <div className="flex items-end justify-between mb-8 gap-4 flex-wrap">
            <div>
              <div className="text-[11px] font-mono uppercase tracking-[0.2em] text-amber-400/80 mb-3">// Module overview</div>
              <h2 className="font-display text-3xl md:text-5xl font-bold tracking-tight max-w-2xl">
                Five command surfaces.<br />
                <span className="text-gradient-warm">One retail brain.</span>
              </h2>
            </div>
            <div className="hidden md:flex gap-2">
              <button onClick={() => scrollRail(-1)} className="h-11 w-11 rounded-full glass hover-glow flex items-center justify-center" aria-label="Previous"><ChevronLeft className="h-5 w-5" /></button>
              <button onClick={() => scrollRail(1)} className="h-11 w-11 rounded-full glass hover-glow flex items-center justify-center" aria-label="Next"><ChevronRight className="h-5 w-5" /></button>
            </div>
          </div>

          <div
            ref={railRef}
            className="flex gap-5 overflow-x-auto scroll-snap-x scrollbar-thin pb-4 -mx-6 px-6 snap-mandatory"
          >
            {MODULES.map((m, i) => (
              <Link
                key={m.to}
                to={m.to}
                className="snap-card group min-w-[300px] md:min-w-[340px] glass rounded-2xl p-6 hover-glow flex flex-col animate-fade-in-up"
                style={{ animationDelay: `${i * 60}ms` }}
              >
                <div className="flex items-center justify-between mb-5">
                  <div className="h-11 w-11 rounded-xl bg-gradient-data/20 border border-amber-500/30 flex items-center justify-center group-hover:bg-gradient-data group-hover:border-transparent transition-all">
                    <m.icon className="h-5 w-5 text-amber-300 group-hover:text-primary-foreground transition-colors" />
                  </div>
                  <StatusBadge status={m.status} />
                </div>
                <h3 className="font-display text-lg font-semibold mb-2">{m.title}</h3>
                <p className="text-[13.5px] text-muted-foreground leading-relaxed flex-1">{m.desc}</p>
                <div className="mt-5 flex items-center text-[12.5px] text-amber-300/90 font-medium gap-1.5 group-hover:gap-3 transition-all">
                  Open module <ArrowRight className="h-3.5 w-3.5" />
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* ===== STATUS / IMPLEMENTED NOW ===== */}
      <section id="status" className="relative py-24 px-6 border-t border-border/50">
        <div className="max-w-7xl mx-auto">
          <div className="text-[11px] font-mono uppercase tracking-[0.2em] text-amber-400/80 mb-3">// What is implemented now</div>
          <h2 className="font-display text-3xl md:text-5xl font-bold tracking-tight mb-4 max-w-3xl">
            Real today. <span className="text-gradient-warm">Ready for tomorrow.</span>
          </h2>
          <p className="text-muted-foreground max-w-2xl mb-12">
            The core retail workspace runs today: inventory, competitor signals, recommendations, and financial context.
            Forecasting and campaign creative are prepared for controlled rollout.
          </p>

          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {SHOP_SERVICES.map((s, i) => (
              <div key={s.name} className="glass rounded-2xl p-6 animate-fade-in-up" style={{ animationDelay: `${i * 80}ms` }}>
                <div className="flex items-center justify-between mb-4">
                  <StatusDot status={s.status} />
                  <StatusBadge status={s.status} />
                </div>
                <div className="font-display text-[16px] font-semibold mb-1.5">{s.name}</div>
                <div className="text-[12.5px] text-muted-foreground leading-relaxed">{s.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ===== DATA SOURCES ===== */}
      <section id="data" className="relative py-24 px-6 border-t border-border/50">
        <div className="max-w-7xl mx-auto">
          <div className="text-[11px] font-mono uppercase tracking-[0.2em] text-amber-400/80 mb-3">// Data sources</div>
          <h2 className="font-display text-3xl md:text-5xl font-bold tracking-tight mb-4 max-w-3xl">
            Seven shops. <span className="text-gradient-warm">One market view.</span>
          </h2>
          <p className="text-muted-foreground max-w-2xl mb-12">
            Continuous scrape pipeline across the leading Lebanese sportswear destinations.
            Supabase-ready snapshots feed competitor positioning, gap detection and market overview.
          </p>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
            {SHOPS.map((shop, i) => (
              <div key={shop.id} className="glass-warm rounded-2xl p-5 hover-glow animate-fade-in-up" style={{ animationDelay: `${i * 60}ms` }}>
                <div className="flex items-center justify-between mb-3">
                  <div className="h-9 w-9 rounded-lg bg-gradient-data flex items-center justify-center text-primary-foreground font-display font-bold text-[13px]">
                    {shop.name.split(' ').map(w => w[0]).join('').slice(0, 2)}
                  </div>
                  <span className="h-2 w-2 rounded-full bg-decision-promote animate-pulse" />
                </div>
                <div className="font-display font-semibold text-[14px]">{shop.name}</div>
                <div className="text-[11px] text-muted-foreground/80 mt-0.5 font-mono">{shop.id}</div>
                <div className="text-[11px] text-amber-300/70 mt-2 uppercase tracking-wider">{shop.tone}</div>
              </div>
            ))}
            <div className="glass rounded-2xl p-5 flex flex-col justify-center items-start">
              <div className="text-3xl font-display font-bold text-gradient-warm">37,102</div>
              <div className="text-[12px] text-muted-foreground mt-1">competitor records ingested</div>
            </div>
          </div>
        </div>
      </section>

      {/* ===== ACTIONS THE SYSTEM GIVES ===== */}
      <section className="relative py-24 px-6 border-t border-border/50">
        <div className="max-w-7xl mx-auto">
          <div className="text-[11px] font-mono uppercase tracking-[0.2em] text-amber-400/80 mb-3">// What it tells you to do</div>
          <h2 className="font-display text-3xl md:text-5xl font-bold tracking-tight mb-4 max-w-3xl">
            Four decisions. <span className="text-gradient-warm">Always reviewed by you.</span>
          </h2>
          <p className="text-muted-foreground max-w-2xl mb-12">
            Every recommendation comes with confidence, top reasons, suggested price and projected margin.
            Human approval is required before any action is committed.
          </p>

          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {ACTIONS.map((a, i) => (
              <div
                key={a.key}
                className={cn(
                  'relative rounded-2xl p-6 overflow-hidden hover-glow animate-fade-in-up border',
                  a.tone === 'hold' && 'bg-decision-hold-bg border-decision-hold/30',
                  a.tone === 'markdown' && 'bg-decision-markdown-bg border-decision-markdown/40',
                  a.tone === 'promote' && 'bg-decision-promote-bg border-decision-promote/40',
                  a.tone === 'clear' && 'bg-decision-clear-bg border-decision-clear/40',
                )}
                style={{ animationDelay: `${i * 80}ms` }}
              >
                <div className={cn(
                  'absolute -top-10 -right-10 h-32 w-32 rounded-full blur-3xl opacity-40',
                  a.tone === 'markdown' && 'bg-decision-markdown',
                  a.tone === 'promote' && 'bg-decision-promote',
                  a.tone === 'clear' && 'bg-decision-clear',
                  a.tone === 'hold' && 'bg-decision-hold',
                )} />
                <div className="relative">
                  <a.icon className={cn(
                    'h-7 w-7 mb-4',
                    a.tone === 'hold' && 'text-decision-hold',
                    a.tone === 'markdown' && 'text-decision-markdown',
                    a.tone === 'promote' && 'text-decision-promote',
                    a.tone === 'clear' && 'text-decision-clear',
                  )} />
                  <ToneBadge tone={a.tone} />
                  <div className="font-display text-2xl font-bold mt-3">{a.key}</div>
                  <p className="text-[13px] text-muted-foreground mt-2 leading-relaxed">{a.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ===== KPI SNAPSHOT ===== */}
      <section id="snapshot" className="relative py-24 px-6 border-t border-border/50">
        <div className="max-w-7xl mx-auto">
          <div className="text-[11px] font-mono uppercase tracking-[0.2em] text-amber-400/80 mb-3">// Project snapshot</div>
          <h2 className="font-display text-3xl md:text-5xl font-bold tracking-tight mb-12 max-w-3xl">
            Where the business stands <span className="text-gradient-warm">right now.</span>
          </h2>

          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {KPIS.map((k, i) => (
              <div key={k.label} className="glass rounded-2xl p-6 animate-fade-in-up" style={{ animationDelay: `${i * 50}ms` }}>
                <div className={cn(
                  'text-data text-3xl md:text-4xl font-bold',
                  k.tone === 'hold' && 'text-decision-hold',
                  k.tone === 'promote' && 'text-decision-promote',
                  k.tone === 'markdown' && 'text-decision-markdown',
                  k.tone === 'clear' && 'text-decision-clear',
                  !k.tone && 'text-gradient-warm',
                )}>
                  {k.value}
                </div>
                <div className="text-[12px] text-muted-foreground mt-2 leading-snug">{k.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ===== GO DEEPER ===== */}
      <section className="relative py-24 px-6 border-t border-border/50">
        <div className="max-w-7xl mx-auto">
          <div className="text-[11px] font-mono uppercase tracking-[0.2em] text-amber-400/80 mb-3">// Go deeper</div>
          <h2 className="font-display text-3xl md:text-5xl font-bold tracking-tight mb-12">
            Step inside a <span className="text-gradient-warm">control room.</span>
          </h2>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {[
              { to: '/overview', icon: Radar, title: 'Executive Overview', desc: 'KPI snapshot, alerts and seasonal calendar.' },
              { to: '/queue', icon: ListChecks, title: 'Recommendations Queue', desc: 'Approve, edit or snooze 350 SKU decisions.' },
              { to: '/competitive', icon: Database, title: 'Competitive Intelligence', desc: 'Live price-gap analysis across 7 shops.' },
              { to: '/financial', icon: Wallet, title: 'Financial Health', desc: 'Cash runway, liquidity, OPEX coverage.' },
              { to: '/promotions', icon: Megaphone, title: 'Promotions & Campaigns', desc: 'Markdown ladders and creative previews.' },
            ].map((m, i) => (
              <Link key={m.to} to={m.to} className="group glass rounded-2xl p-7 hover-glow animate-fade-in-up flex items-start gap-5" style={{ animationDelay: `${i * 70}ms` }}>
                <div className="h-12 w-12 shrink-0 rounded-xl bg-gradient-data flex items-center justify-center shadow-glow-sm">
                  <m.icon className="h-6 w-6 text-primary-foreground" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-display font-semibold text-[16px] mb-1">{m.title}</div>
                  <div className="text-[13px] text-muted-foreground leading-relaxed">{m.desc}</div>
                  <div className="mt-3 flex items-center gap-1.5 text-[12px] text-amber-300/90 font-medium group-hover:gap-3 transition-all">
                    Enter <ArrowRight className="h-3.5 w-3.5" />
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* ===== FOOTER ===== */}
      <footer className="border-t border-border/50 py-10 px-6">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-[12px] text-muted-foreground">
          <div className="flex items-center gap-2">
            <Radar className="h-4 w-4 text-amber-400" />
            <span className="font-display font-semibold text-foreground">Retail Radar AI</span>
            <span>· Powered by StylePulse · Lebanon · Fresh USD</span>
          </div>
          <div className="font-mono uppercase tracking-[0.16em] text-[10.5px]">
            Build 0.9 · Mock + IE2 live · EEP & Supabase ready
          </div>
        </div>
      </footer>
    </div>
  );
}
