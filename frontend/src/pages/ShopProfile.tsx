import { FormEvent, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Info } from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  fetchAvailableCompetitors,
  fetchShopProfile,
  updateShopProfile,
  fetchSocialAccounts,
  updateSocialDisplayName,
  type RetailerSocialAccount,
} from '@/lib/adapter';
import { useTenantScopeKey } from '@/hooks/useTenantScope';
import type { CompetitorOption, ShopProfile } from '@/types/domain';

type SocialPlatform = 'facebook' | 'instagram' | 'telegram';

const SOCIAL_HINTS: Record<SocialPlatform, { label: string; placeholder: string; hint: string }> = {
  facebook: {
    label: 'Facebook',
    placeholder: "e.g. Fouani's Electronics",
    hint: 'Enter your Facebook Page name exactly as it appears to customers.',
  },
  instagram: {
    label: 'Instagram',
    placeholder: 'e.g. fouanis_store',
    hint: 'Enter your Instagram handle without the @ symbol.',
  },
  telegram: {
    label: 'Telegram',
    placeholder: 'e.g. @FouanisStoreBot',
    hint: 'Enter your Telegram bot @username — found in BotFather after creating your bot.',
  },
};

export default function ShopProfilePage() {
  const tenantScope = useTenantScopeKey();
  const [profile, setProfile] = useState<ShopProfile | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorOption[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [customCompetitors, setCustomCompetitors] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [socialAccounts, setSocialAccounts] = useState<RetailerSocialAccount[]>([]);
  const [socialNames, setSocialNames] = useState<Record<SocialPlatform, string>>({ facebook: '', instagram: '', telegram: '' });
  const [socialSaving, setSocialSaving] = useState<Record<SocialPlatform, boolean>>({ facebook: false, instagram: false, telegram: false });

  const [form, setForm] = useState({
    business_name: '',
    legal_name: '',
    phone: '',
    website_url: '',
    address: '',
    country: 'Lebanon',
    timezone: 'Asia/Beirut',
  });

  useEffect(() => {
    setLoading(true);
    setProfile(null);
    Promise.all([fetchShopProfile(), fetchAvailableCompetitors(), fetchSocialAccounts().catch(() => [])])
      .then(([nextProfile, nextCompetitors, nextSocial]) => {
        setProfile(nextProfile);
        setCompetitors(nextCompetitors);
        setSelected(nextProfile.selected_competitors.map((item) => item.shop_code));
        setForm({
          business_name: nextProfile.business_name || '',
          legal_name: nextProfile.legal_name || '',
          phone: nextProfile.phone || '',
          website_url: nextProfile.website_url || '',
          address: nextProfile.address || '',
          country: nextProfile.country || 'Lebanon',
          timezone: nextProfile.timezone || 'Asia/Beirut',
        });
        setSocialAccounts(nextSocial as RetailerSocialAccount[]);
        const names: Record<SocialPlatform, string> = { facebook: '', instagram: '', telegram: '' };
        for (const acc of nextSocial as RetailerSocialAccount[]) {
          if (acc.platform in names) names[acc.platform as SocialPlatform] = acc.account_name ?? '';
        }
        setSocialNames(names);
      })
      .catch((error) => toast.error(error?.message || 'Could not load shop profile'))
      .finally(() => setLoading(false));
  }, [tenantScope]);

  const pendingRequests = useMemo(
    () => profile?.competitor_requests.filter((request) => request.status === 'pending') ?? [],
    [profile],
  );

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
    await saveProfile();
  }

  async function saveSocialName(platform: SocialPlatform) {
    const name = socialNames[platform].trim();
    if (!name) { toast.error('Enter a display name first'); return; }
    setSocialSaving((s) => ({ ...s, [platform]: true }));
    try {
      await updateSocialDisplayName(platform, name);
      toast.success(`${SOCIAL_HINTS[platform].label} display name saved`);
    } catch (err: any) {
      toast.error(err?.message || `Could not save ${platform} name`);
    } finally {
      setSocialSaving((s) => ({ ...s, [platform]: false }));
    }
  }

  async function saveProfile() {
    setSaving(true);
    try {
      const nextProfile = await updateShopProfile({
        ...form,
        selected_competitor_codes: selected,
        requested_competitor_names: splitNames(customCompetitors),
      });
      setProfile(nextProfile);
      setCustomCompetitors('');
      toast.success('Shop profile saved');
    } catch (error: any) {
      toast.error(error?.message || 'Could not save shop profile');
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <TopBar title="Shop Profile" subtitle="Account workspace, contact details, and competitor tracking" />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in max-w-4xl">
        <Section title="Shop Workspace" subtitle={profile ? `Tenant: ${profile.tenant_slug}` : undefined}>
          {loading ? (
            <div className="text-sm text-muted-foreground">Loading profile...</div>
          ) : (
            <form onSubmit={onSubmit} className="space-y-5">
              <div className="grid md:grid-cols-2 gap-4">
                <Field label="Business name" value={form.business_name} onChange={(value) => updateField('business_name', value)} required />
                <Field label="Legal name" value={form.legal_name} onChange={(value) => updateField('legal_name', value)} />
                <Field label="Phone" value={form.phone} onChange={(value) => updateField('phone', value)} />
                <Field label="Website" value={form.website_url} onChange={(value) => updateField('website_url', value)} />
                <Field label="Country" value={form.country} onChange={(value) => updateField('country', value)} />
                <Field label="Timezone" value={form.timezone} onChange={(value) => updateField('timezone', value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="profile-address">Address</Label>
                <Textarea id="profile-address" rows={3} value={form.address} onChange={(event) => updateField('address', event.target.value)} />
              </div>
              <Button type="submit" disabled={saving}>{saving ? 'Saving...' : 'Save profile'}</Button>
            </form>
          )}
        </Section>

        <Section title="Competitors" subtitle="Only selected competitors feed your competitive intelligence and recommendations">
          <div className="space-y-5">
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

            <div className="space-y-2">
              <Label htmlFor="profile-custom-competitors">Request missing competitors</Label>
              <Textarea
                id="profile-custom-competitors"
                rows={4}
                value={customCompetitors}
                onChange={(event) => setCustomCompetitors(event.target.value)}
                placeholder="One competitor name per line"
              />
              <Button onClick={() => void saveProfile()} disabled={saving} type="button">
                {saving ? 'Saving...' : 'Save competitors'}
              </Button>
            </div>
          </div>
        </Section>

        <Section title="Pending Competitor Requests">
          {pendingRequests.length === 0 ? (
            <div className="text-sm text-muted-foreground">No pending competitor requests.</div>
          ) : (
            <div className="space-y-2">
              {pendingRequests.map((request) => (
                <div key={request.id} className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
                  <span>{request.competitor_name}</span>
                  <span className="text-xs uppercase tracking-wider text-muted-foreground">{request.status}</span>
                </div>
              ))}
            </div>
          )}
        </Section>

        <Section title="Social Accounts" subtitle="Set how your shop name appears on each connected platform">
          <div className="grid sm:grid-cols-3 gap-4">
            {(['facebook', 'instagram', 'telegram'] as SocialPlatform[]).map((platform) => {
              const meta = SOCIAL_HINTS[platform];
              const account = socialAccounts.find((a) => a.platform === platform && a.is_active);
              return (
                <div key={platform} className="border border-border rounded-lg p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-sm">{meta.label}</span>
                    <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full ${account ? 'bg-green-500/15 text-green-400' : 'bg-muted text-muted-foreground'}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${account ? 'bg-green-400' : 'bg-muted-foreground'}`} />
                      {account ? 'Connected' : 'Not connected'}
                    </span>
                  </div>
                  {account ? (
                    <>
                      <div className="space-y-1">
                        <Input
                          placeholder={meta.placeholder}
                          value={socialNames[platform]}
                          onChange={(e) => setSocialNames((n) => ({ ...n, [platform]: e.target.value }))}
                        />
                        <p className="text-[11px] text-muted-foreground/70 flex items-start gap-1 px-0.5">
                          <Info className="w-3 h-3 mt-0.5 shrink-0 opacity-60" />
                          {meta.hint}
                        </p>
                      </div>
                      <Button size="sm" className="w-full" disabled={socialSaving[platform]} onClick={() => void saveSocialName(platform)}>
                        {socialSaving[platform] ? 'Saving...' : 'Save name'}
                      </Button>
                    </>
                  ) : (
                    <p className="text-xs text-muted-foreground">Your admin needs to connect this platform first before you can set a display name.</p>
                  )}
                </div>
              );
            })}
          </div>
        </Section>
      </main>
    </>
  );
}

function Field({
  label,
  value,
  onChange,
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  const id = `profile-${label.toLowerCase().replace(/\s+/g, '-')}`;
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} value={value} required={required} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}

function splitNames(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}
