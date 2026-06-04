import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, ListChecks, Radar, ShieldCheck, Store } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { fetchAvailableCompetitors, signupShop } from '@/lib/adapter';
import { cn } from '@/lib/utils';
import { useAuth } from '@/store/auth';
import { useSettings } from '@/store/settings';
import type { CompetitorOption } from '@/types/domain';

export default function Signup() {
  const navigate = useNavigate();
  const setSession = useAuth((state) => state.setSession);
  const setMode = useSettings((state) => state.setMode);
  const [competitors, setCompetitors] = useState<CompetitorOption[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [customCompetitors, setCustomCompetitors] = useState('');
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    owner_name: '',
    email: '',
    password: '',
    shop_name: '',
    phone: '',
    website_url: '',
    address: '',
  });

  useEffect(() => {
    fetchAvailableCompetitors()
      .then(setCompetitors)
      .catch((error) => toast.error(error?.message || 'Could not load competitors'));
  }, []);

  function updateField(key: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function toggleCompetitor(code: string, checked: boolean) {
    setSelected((current) => (
      checked ? Array.from(new Set([...current, code])) : current.filter((item) => item !== code)
    ));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      const session = await signupShop({
        ...form,
        country: 'Lebanon',
        timezone: 'Asia/Beirut',
        selected_competitor_codes: selected,
        requested_competitor_names: splitNames(customCompetitors),
      });
      setSession(session.access_token, session.user);
      setMode('eep-live');
      navigate('/overview', { replace: true });
    } catch (error: any) {
      toast.error(error?.message || 'Signup failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-gradient-hero text-foreground px-6 py-10 grain">
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/60 to-transparent" />
      <div className="relative z-10 mx-auto grid w-full max-w-6xl overflow-hidden rounded-2xl border border-primary/20 bg-card/70 shadow-lg-soft backdrop-blur-xl lg:grid-cols-[0.82fr_1.18fr]">
        <aside className="relative hidden overflow-hidden border-r border-primary/15 bg-gradient-sand p-8 lg:block">
          <div className="absolute inset-0 bg-[radial-gradient(620px_320px_at_20%_15%,hsl(28_96%_56%/.30),transparent),radial-gradient(520px_340px_at_100%_80%,hsl(152_60%_48%/.20),transparent),radial-gradient(420px_220px_at_40%_100%,hsl(0_84%_60%/.12),transparent)]" />
          <div className="relative">
            <div className="h-12 w-12 rounded-xl bg-gradient-data flex items-center justify-center shadow-glow-sm">
              <Radar className="h-6 w-6 text-primary-foreground" />
            </div>
            <h1 className="mt-8 font-display text-4xl font-extrabold leading-tight">
              Launch your
              <span className="block text-gradient-warm">shop workspace</span>
            </h1>
            <p className="mt-4 text-sm leading-6 text-muted-foreground">
              Set up the business profile, choose competitors, and start from a clean retail dashboard.
            </p>
          </div>
          <div className="relative mt-10 space-y-3">
            <OnboardingPoint icon={Store} title="Profile" tone="text-primary" />
            <OnboardingPoint icon={ListChecks} title="Competitors" tone="text-decision-promote" />
            <OnboardingPoint icon={ShieldCheck} title="Requests" tone="text-decision-markdown" />
          </div>
        </aside>

        <section className="relative p-6 sm:p-10">
          <div className="absolute inset-0 bg-[radial-gradient(580px_320px_at_70%_0%,hsl(28_96%_56%/.12),transparent),radial-gradient(420px_260px_at_100%_100%,hsl(152_60%_48%/.10),transparent)]" />
          <div className="relative">
            <div className="mb-4 h-11 w-11 rounded-lg bg-gradient-data flex items-center justify-center shadow-glow-sm lg:hidden">
              <Radar className="h-6 w-6 text-primary-foreground" />
            </div>
            <h2 className="font-display text-3xl font-bold tracking-tight">Create shop account</h2>
            <p className="mt-2 text-sm text-muted-foreground">Create the owner login and choose the competitors this shop tracks.</p>
            <form onSubmit={onSubmit} className="space-y-6">
              <div className="grid md:grid-cols-2 gap-4">
                <Field label="Owner name" value={form.owner_name} onChange={(value) => updateField('owner_name', value)} required />
                <Field label="Email" type="email" value={form.email} onChange={(value) => updateField('email', value)} required />
                <Field label="Password" type="password" value={form.password} onChange={(value) => updateField('password', value)} required />
                <Field label="Shop name" value={form.shop_name} onChange={(value) => updateField('shop_name', value)} required />
                <Field label="Phone" value={form.phone} onChange={(value) => updateField('phone', value)} />
                <Field label="Website" value={form.website_url} onChange={(value) => updateField('website_url', value)} />
              </div>

              <div className="space-y-2">
                <Label htmlFor="address">Address</Label>
                <Textarea id="address" value={form.address} onChange={(event) => updateField('address', event.target.value)} rows={3} />
              </div>

              <div className="space-y-3">
                <div>
                  <Label>Competitors to track</Label>
                  <p className="text-sm text-muted-foreground mt-1">Choose from existing competitor shops. You can request missing competitors below.</p>
                </div>
                <div className="grid sm:grid-cols-2 gap-3">
                  {competitors.map((competitor) => (
                    <label
                      key={competitor.shop_code}
                      className={cn(
                        'flex items-center gap-3 rounded-md border px-3 py-2 text-sm transition-colors',
                        selected.includes(competitor.shop_code)
                          ? 'border-primary/50 bg-primary/10 text-foreground'
                          : 'border-border bg-background/45 hover:border-primary/30',
                      )}
                    >
                      <Checkbox
                        checked={selected.includes(competitor.shop_code)}
                        onCheckedChange={(checked) => toggleCompetitor(competitor.shop_code, checked === true)}
                      />
                      <span>{competitor.shop_name}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="customCompetitors">Missing competitors</Label>
                <Textarea
                  id="customCompetitors"
                  value={customCompetitors}
                  onChange={(event) => setCustomCompetitors(event.target.value)}
                  placeholder="One competitor name per line"
                  rows={4}
                />
              </div>

              <div className="flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
                <Button type="submit" disabled={loading} className="bg-gradient-data text-primary-foreground shadow-glow-sm hover:opacity-95">
                  {loading ? 'Creating account...' : 'Create account'}
                  {!loading && <ArrowRight className="h-4 w-4" />}
                </Button>
                <Link to="/login" className="text-sm text-muted-foreground hover:text-foreground">
                  Already have an account?
                </Link>
              </div>
            </form>
          </div>
        </section>
      </div>
    </main>
  );
}

function OnboardingPoint({ icon: Icon, title, tone }: { icon: any; title: string; tone: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-primary/15 bg-background/35 p-3 text-sm backdrop-blur-sm">
      <div className={`rounded-lg bg-background/50 p-2 ${tone}`}>
        <Icon className="h-4 w-4" />
      </div>
      <span className="font-medium">{title}</span>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
}) {
  const id = label.toLowerCase().replace(/\s+/g, '-');
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type={type} value={value} onChange={(event) => onChange(event.target.value)} required={required} className="border-primary/20 bg-background/70" />
    </div>
  );
}

function splitNames(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}
