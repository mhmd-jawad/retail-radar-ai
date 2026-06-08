import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { ChevronDown, ChevronUp, ExternalLink, Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  fetchAdminSocialAccounts,
  upsertAdminSocialAccount,
  removeAdminSocialAccount,
  type SocialAccountEntry,
} from '@/lib/adapter';

interface Props {
  tenantId: string;
}

type Platform = 'facebook' | 'instagram' | 'telegram';

interface TileState {
  token: string;
  pageId: string;
  userId: string;
  accountName: string;
  saving: boolean;
  removing: boolean;
  guideOpen: boolean;
}

const EMPTY_TILE: TileState = {
  token: '',
  pageId: '',
  userId: '',
  accountName: '',
  saving: false,
  removing: false,
  guideOpen: false,
};

// ── Per-platform setup guide content ─────────────────────────────────────────

const GUIDES = {
  facebook: {
    color: 'text-blue-400',
    borderColor: 'border-blue-500/30',
    bgColor: 'bg-blue-500/5',
    steps: [
      { label: 'Create a Facebook App', detail: 'Go to developers.facebook.com → My Apps → Create App → choose Business type.' },
      { label: 'Get your Page ID', detail: 'Open your Facebook Page → About → scroll to the bottom. The Page ID is a long number (e.g. 123456789012345).' },
      { label: 'Get a Page Access Token', detail: 'Go to developers.facebook.com/tools/explorer → select your App → click "Get Token" → "Get Page Access Token" → select your Page.' },
      { label: 'Extend to long-lived token', detail: 'In the Explorer, click the ⓘ icon next to the token → Open in Access Token Tool → click "Extend Access Token". This gives you a 60-day token.' },
    ],
    links: [
      { label: 'Graph API Explorer', url: 'https://developers.facebook.com/tools/explorer' },
      { label: 'Access Token Tool', url: 'https://developers.facebook.com/tools/accesstoken' },
    ],
  },
  instagram: {
    color: 'text-pink-400',
    borderColor: 'border-pink-500/30',
    bgColor: 'bg-pink-500/5',
    steps: [
      { label: 'Link Instagram to your Facebook Page', detail: 'Go to your Facebook Page → Settings → Linked Accounts (or Instagram) → Connect Account. You need an Instagram Business account.' },
      { label: 'Get your IG User ID', detail: 'In Graph API Explorer, run: /me/accounts to find your Page ID, then query: /{page-id}?fields=instagram_business_account — the "id" in the response is your IG User ID.' },
      { label: 'Access Token', detail: 'Use the same long-lived Page Access Token from Facebook — it works for Instagram publishing too.' },
    ],
    links: [
      { label: 'Graph API Explorer', url: 'https://developers.facebook.com/tools/explorer' },
    ],
  },
  telegram: {
    color: 'text-sky-400',
    borderColor: 'border-sky-500/30',
    bgColor: 'bg-sky-500/5',
    steps: [
      { label: 'Open BotFather in Telegram', detail: 'Search for @BotFather in the Telegram app and open the chat.' },
      { label: 'Create a new bot', detail: 'Send /newbot → enter a display name (e.g. "Fouani\'s Store") → enter a username ending in "bot" (e.g. FouanisStoreBot).' },
      { label: 'Copy the bot token', detail: 'BotFather replies with a token like: 123456789:ABCdefGHIjklMNOpqrSTUvwxYZ — paste this into the field below.' },
      { label: 'Retailer activation (one-time)', detail: 'After saving, the shop owner must open Telegram, search for their bot, and send any message. This registers their chat and activates alerts.' },
    ],
    links: [
      { label: 'Open @BotFather', url: 'https://t.me/BotFather' },
    ],
  },
} as const;

// ── Field helper text ─────────────────────────────────────────────────────────

const FIELD_HINTS = {
  fb_token: 'Long-lived Page Access Token from Meta Graph API Explorer',
  fb_page_id: 'Numeric ID found on your Facebook Page → About section',
  ig_token: 'Same as your Facebook Page Access Token (works for Instagram too)',
  ig_user_id: 'Query /{page-id}?fields=instagram_business_account in Graph API Explorer',
  tg_token: 'Get this from @BotFather on Telegram using /newbot',
  tg_username: 'The @username of your bot, used for display only',
};

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusPill({ connected }: { connected: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full ${
        connected ? 'bg-green-500/15 text-green-400' : 'bg-muted text-muted-foreground'
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-green-400' : 'bg-muted-foreground'}`} />
      {connected ? 'Connected' : 'Not connected'}
    </span>
  );
}

function FieldWithHint({
  placeholder,
  hint,
  type = 'text',
  value,
  onChange,
}: {
  placeholder: string;
  hint: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-1">
      <Input
        placeholder={placeholder}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <p className="text-[11px] text-muted-foreground/70 flex items-start gap-1 px-0.5">
        <Info className="w-3 h-3 mt-0.5 shrink-0 opacity-60" />
        {hint}
      </p>
    </div>
  );
}

function SetupGuide({ platform, open, onToggle }: { platform: Platform; open: boolean; onToggle: () => void }) {
  const guide = GUIDES[platform];
  return (
    <div className={`rounded-md border ${guide.borderColor} overflow-hidden`}>
      <button
        type="button"
        onClick={onToggle}
        className={`w-full flex items-center justify-between px-3 py-2 text-xs font-medium ${guide.color} ${guide.bgColor} hover:opacity-80 transition-opacity`}
      >
        <span className="flex items-center gap-1.5">
          <Info className="w-3.5 h-3.5" />
          How to get these credentials
        </span>
        {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
      </button>

      {open && (
        <div className={`px-3 py-3 space-y-3 ${guide.bgColor}`}>
          <ol className="space-y-2.5">
            {guide.steps.map((step, i) => (
              <li key={i} className="flex gap-2.5 text-xs">
                <span className={`shrink-0 w-5 h-5 rounded-full ${guide.bgColor} border ${guide.borderColor} ${guide.color} flex items-center justify-center font-bold text-[10px]`}>
                  {i + 1}
                </span>
                <div>
                  <p className="font-semibold text-foreground">{step.label}</p>
                  <p className="text-muted-foreground mt-0.5 leading-relaxed">{step.detail}</p>
                </div>
              </li>
            ))}
          </ol>

          {guide.links.length > 0 && (
            <div className="flex flex-wrap gap-2 pt-1 border-t border-border/40">
              {guide.links.map((link) => (
                <a
                  key={link.url}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`inline-flex items-center gap-1 text-[11px] font-medium ${guide.color} hover:underline`}
                >
                  <ExternalLink className="w-3 h-3" />
                  {link.label}
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function SocialAccountsManager({ tenantId }: Props) {
  const [accounts, setAccounts] = useState<Record<Platform, SocialAccountEntry | null>>({
    facebook: null,
    instagram: null,
    telegram: null,
  });
  const [tiles, setTiles] = useState<Record<Platform, TileState>>({
    facebook: { ...EMPTY_TILE },
    instagram: { ...EMPTY_TILE },
    telegram: { ...EMPTY_TILE },
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAdminSocialAccounts(tenantId)
      .then((list) => {
        const map: Record<Platform, SocialAccountEntry | null> = {
          facebook: null,
          instagram: null,
          telegram: null,
        };
        for (const entry of list) map[entry.platform] = entry;
        setAccounts(map);
        setTiles({
          facebook: { ...EMPTY_TILE, pageId: map.facebook?.page_id ?? '', accountName: map.facebook?.account_name ?? '' },
          instagram: { ...EMPTY_TILE, userId: map.instagram?.user_id ?? '', accountName: map.instagram?.account_name ?? '' },
          telegram: { ...EMPTY_TILE, accountName: map.telegram?.account_name ?? '' },
        });
      })
      .catch((err) => toast.error(err?.message || 'Could not load social accounts'))
      .finally(() => setLoading(false));
  }, [tenantId]);

  function setTile(platform: Platform, patch: Partial<TileState>) {
    setTiles((t) => ({ ...t, [platform]: { ...t[platform], ...patch } }));
  }

  async function save(platform: Platform) {
    const t = tiles[platform];
    if (!t.token) {
      toast.error('Paste the token first before saving');
      return;
    }
    setTile(platform, { saving: true });
    try {
      const result = await upsertAdminSocialAccount(tenantId, {
        platform,
        access_token: t.token,
        page_id: platform === 'facebook' ? t.pageId : undefined,
        user_id: platform === 'instagram' ? t.userId : undefined,
        account_name: t.accountName || undefined,
      });
      const webhookMsg =
        platform === 'telegram' && result.webhook_status === 'pending'
          ? ' — webhook pending, double-check the bot token'
          : platform === 'telegram'
          ? ' — webhook registered successfully'
          : '';
      toast.success(`${platform} credentials saved${webhookMsg}`);
      const list = await fetchAdminSocialAccounts(tenantId);
      const map: Record<Platform, SocialAccountEntry | null> = { facebook: null, instagram: null, telegram: null };
      for (const entry of list) map[entry.platform] = entry;
      setAccounts(map);
      setTile(platform, { token: '' });
    } catch (err: any) {
      toast.error(err?.message || `Could not save ${platform}`);
    } finally {
      setTile(platform, { saving: false });
    }
  }

  async function remove(platform: Platform) {
    setTile(platform, { removing: true });
    try {
      await removeAdminSocialAccount(tenantId, platform);
      toast.success(`${platform} disconnected`);
      setAccounts((a) => ({ ...a, [platform]: null }));
      setTile(platform, { token: '', pageId: '', userId: '', accountName: '' });
    } catch (err: any) {
      toast.error(err?.message || `Could not remove ${platform}`);
    } finally {
      setTile(platform, { removing: false });
    }
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground py-2">Loading social connections...</p>;
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2">

      {/* ── Facebook ── */}
      <div className="border border-border rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="font-semibold text-sm">Facebook</span>
          <StatusPill connected={!!accounts.facebook} />
        </div>

        <SetupGuide
          platform="facebook"
          open={tiles.facebook.guideOpen}
          onToggle={() => setTile('facebook', { guideOpen: !tiles.facebook.guideOpen })}
        />

        <FieldWithHint
          placeholder="Page Access Token"
          type="password"
          hint={FIELD_HINTS.fb_token}
          value={tiles.facebook.token}
          onChange={(v) => setTile('facebook', { token: v })}
        />
        <FieldWithHint
          placeholder="Page ID (numeric)"
          hint={FIELD_HINTS.fb_page_id}
          value={tiles.facebook.pageId}
          onChange={(v) => setTile('facebook', { pageId: v })}
        />
        <Input
          placeholder="Display name (optional)"
          value={tiles.facebook.accountName}
          onChange={(e) => setTile('facebook', { accountName: e.target.value })}
        />

        <div className="flex gap-2 pt-1">
          <Button size="sm" disabled={tiles.facebook.saving} onClick={() => void save('facebook')} className="flex-1">
            {tiles.facebook.saving ? 'Saving...' : 'Save'}
          </Button>
          {accounts.facebook && (
            <Button size="sm" variant="outline" disabled={tiles.facebook.removing} onClick={() => void remove('facebook')}>
              {tiles.facebook.removing ? '...' : 'Remove'}
            </Button>
          )}
        </div>
      </div>

      {/* ── Instagram ── */}
      <div className="border border-border rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="font-semibold text-sm">Instagram</span>
          <StatusPill connected={!!accounts.instagram} />
        </div>

        <SetupGuide
          platform="instagram"
          open={tiles.instagram.guideOpen}
          onToggle={() => setTile('instagram', { guideOpen: !tiles.instagram.guideOpen })}
        />

        <FieldWithHint
          placeholder="Access Token"
          type="password"
          hint={FIELD_HINTS.ig_token}
          value={tiles.instagram.token}
          onChange={(v) => setTile('instagram', { token: v })}
        />
        <FieldWithHint
          placeholder="IG User ID (numeric)"
          hint={FIELD_HINTS.ig_user_id}
          value={tiles.instagram.userId}
          onChange={(v) => setTile('instagram', { userId: v })}
        />
        <Input
          placeholder="Display name (optional)"
          value={tiles.instagram.accountName}
          onChange={(e) => setTile('instagram', { accountName: e.target.value })}
        />

        <div className="flex gap-2 pt-1">
          <Button size="sm" disabled={tiles.instagram.saving} onClick={() => void save('instagram')} className="flex-1">
            {tiles.instagram.saving ? 'Saving...' : 'Save'}
          </Button>
          {accounts.instagram && (
            <Button size="sm" variant="outline" disabled={tiles.instagram.removing} onClick={() => void remove('instagram')}>
              {tiles.instagram.removing ? '...' : 'Remove'}
            </Button>
          )}
        </div>
      </div>

      {/* ── Telegram ── */}
      <div className="border border-border rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="font-semibold text-sm">Telegram</span>
          <StatusPill connected={!!accounts.telegram} />
        </div>

        <SetupGuide
          platform="telegram"
          open={tiles.telegram.guideOpen}
          onToggle={() => setTile('telegram', { guideOpen: !tiles.telegram.guideOpen })}
        />

        <FieldWithHint
          placeholder="Bot Token (from BotFather)"
          type="password"
          hint={FIELD_HINTS.tg_token}
          value={tiles.telegram.token}
          onChange={(v) => setTile('telegram', { token: v })}
        />
        <FieldWithHint
          placeholder="Bot username (e.g. @ShopBot)"
          hint={FIELD_HINTS.tg_username}
          value={tiles.telegram.accountName}
          onChange={(v) => setTile('telegram', { accountName: v })}
        />

        {accounts.telegram && (
          <div className={`rounded-md px-3 py-2 text-xs flex items-start gap-2 ${
            accounts.telegram.webhook_registered_at
              ? 'bg-green-500/10 text-green-400 border border-green-500/20'
              : 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20'
          }`}>
            <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            {accounts.telegram.webhook_registered_at
              ? 'Webhook registered. Ask the retailer to message their bot once to activate alerts.'
              : 'Webhook pending — verify the bot token is correct and try saving again.'}
          </div>
        )}

        <div className="flex gap-2 pt-1">
          <Button size="sm" disabled={tiles.telegram.saving} onClick={() => void save('telegram')} className="flex-1">
            {tiles.telegram.saving ? 'Saving...' : 'Save'}
          </Button>
          {accounts.telegram && (
            <Button size="sm" variant="outline" disabled={tiles.telegram.removing} onClick={() => void remove('telegram')}>
              {tiles.telegram.removing ? '...' : 'Remove'}
            </Button>
          )}
        </div>
      </div>

    </div>
  );
}
