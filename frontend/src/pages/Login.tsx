import { FormEvent, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { loginAccount } from '@/lib/adapter';
import { redirectForLogin } from '@/lib/auth-routing';
import { useAuth } from '@/store/auth';
import { useSettings } from '@/store/settings';

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const setSession = useAuth((state) => state.setSession);
  const setMode = useSettings((state) => state.setMode);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const from = typeof location.state === 'object' && location.state && 'from' in location.state
    ? String(location.state.from || '/overview')
    : '/overview';

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      const session = await loginAccount(email, password);
      setSession(session.access_token, session.user);
      setMode('eep-live');
      navigate(redirectForLogin(session.user, from), { replace: true });
    } catch (error: any) {
      toast.error(error?.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-gradient-hero text-foreground px-6 py-10 grid place-items-center grain">
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/60 to-transparent" />
      <div className="relative z-10 grid w-full max-w-5xl overflow-hidden rounded-2xl border border-primary/20 bg-card/70 shadow-lg-soft backdrop-blur-xl lg:grid-cols-[1.05fr_0.95fr]">
        <section className="relative hidden min-h-[560px] overflow-hidden border-r border-primary/15 bg-gradient-sand p-8 lg:flex lg:flex-col lg:justify-center">
          <div className="absolute inset-0 bg-[radial-gradient(720px_380px_at_16%_12%,hsl(28_96%_56%/.34),transparent),radial-gradient(560px_320px_at_82%_78%,hsl(152_60%_48%/.22),transparent),radial-gradient(440px_240px_at_48%_98%,hsl(0_84%_60%/.13),transparent)]" />
          <div className="relative max-w-xl">
            <h1 className="mt-8 font-display text-5xl font-extrabold leading-[0.95] tracking-tight">
              Retail Radar
              <span className="block text-gradient-warm">Control Center</span>
            </h1>
            <p className="mt-5 max-w-md text-sm leading-6 text-muted-foreground">
              Live retail intelligence for inventory, competitors, finance, and promotions.
            </p>
            <div className="mt-12 grid grid-cols-3 gap-3">
              <Signal label="Inventory" tone="bg-primary" />
              <Signal label="Competitors" tone="bg-decision-promote" />
              <Signal label="Finance" tone="bg-decision-clear" />
            </div>
          </div>
        </section>

        <section className="relative flex items-center p-8 sm:p-12 lg:p-16">
          <div className="absolute inset-0 bg-[radial-gradient(520px_320px_at_70%_10%,hsl(28_96%_56%/.16),transparent),radial-gradient(420px_260px_at_100%_90%,hsl(0_84%_60%/.10),transparent)]" />
          <div className="relative w-full">
            <div className="mb-5 h-12 w-12 rounded-xl overflow-hidden flex items-center justify-center shadow-glow-sm">
              <img src="/logo.png" alt="Retail Radar AI" className="h-12 w-12 object-contain" />
            </div>
            <h2 className="font-display text-4xl font-bold tracking-tight">Log in</h2>
            <p className="mt-2 text-sm text-muted-foreground">Use your admin or shop owner account.</p>

            <form onSubmit={onSubmit} className="mt-7 space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required className="h-12 border-primary/25 bg-background/70" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required className="h-12 border-primary/25 bg-background/70" />
              </div>
              <Button type="submit" className="h-12 w-full bg-gradient-data text-primary-foreground shadow-glow-sm hover:opacity-95" disabled={loading}>
                {loading ? 'Logging in...' : 'Log in'}
                {!loading && <ArrowRight className="h-4 w-4" />}
              </Button>
            </form>
            <div className="mt-5 text-sm text-muted-foreground">
              New shop? <Link to="/signup" className="text-primary font-semibold hover:underline">Create shop account</Link>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

function Signal({ label, tone }: { label: string; tone: string }) {
  return (
    <div className="rounded-xl border border-primary/15 bg-background/30 p-3 backdrop-blur-sm">
      <div className={`h-1.5 rounded-full ${tone}`} />
      <div className="mt-3 text-[11px] font-mono uppercase tracking-wider text-muted-foreground">{label}</div>
    </div>
  );
}
