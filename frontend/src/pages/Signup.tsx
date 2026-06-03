import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Radar } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { fetchAvailableCompetitors, signupShop } from '@/lib/adapter';
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
    <main className="min-h-screen bg-background text-foreground px-6 py-10">
      <div className="mx-auto w-full max-w-3xl">
        <Card>
          <CardHeader>
            <div className="mb-4 h-11 w-11 rounded-lg bg-gradient-data flex items-center justify-center">
              <Radar className="h-6 w-6 text-primary-foreground" />
            </div>
            <CardTitle>Create shop account</CardTitle>
            <CardDescription>Your shop gets its own tenant workspace, inventory, selected competitors, and owner login.</CardDescription>
          </CardHeader>
          <CardContent>
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
                    <label key={competitor.shop_code} className="flex items-center gap-3 rounded-md border border-border bg-card px-3 py-2 text-sm">
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
                <Button type="submit" disabled={loading}>
                  {loading ? 'Creating account...' : 'Create account'}
                </Button>
                <Link to="/login" className="text-sm text-muted-foreground hover:text-foreground">
                  Already have an account?
                </Link>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    </main>
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
      <Input id={id} type={type} value={value} onChange={(event) => onChange(event.target.value)} required={required} />
    </div>
  );
}

function splitNames(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}
