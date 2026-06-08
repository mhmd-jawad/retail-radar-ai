import { useEffect, useState } from 'react';
import { toast } from 'sonner';
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
}

const EMPTY_TILE: TileState = {
  token: '',
  pageId: '',
  userId: '',
  accountName: '',
  saving: false,
  removing: false,
};

function StatusPill({ connected }: { connected: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full ${
        connected
          ? 'bg-green-500/15 text-green-400'
          : 'bg-muted text-muted-foreground'
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-green-400' : 'bg-muted-foreground'}`} />
      {connected ? 'Connected' : 'Not connected'}
    </span>
  );
}

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
        for (const entry of list) {
          map[entry.platform] = entry;
        }
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
      toast.error('Token is required');
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
          ? ' (webhook pending — check bot token)'
          : platform === 'telegram'
          ? ' · webhook registered'
          : '';
      toast.success(`${platform} credentials saved${webhookMsg}`);
      // Refresh
      const list = await fetchAdminSocialAccounts(tenantId);
      const map: Record<Platform, SocialAccountEntry | null> = { facebook: null, instagram: null, telegram: null };
      for (const entry of list) map[entry.platform] = entry;
      setAccounts(map);
      setTile(platform, { token: '' }); // clear token field after save (security)
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
        <Input
          placeholder="Page Access Token"
          type="password"
          value={tiles.facebook.token}
          onChange={(e) => setTile('facebook', { token: e.target.value })}
        />
        <Input
          placeholder="Page ID (numeric)"
          value={tiles.facebook.pageId}
          onChange={(e) => setTile('facebook', { pageId: e.target.value })}
        />
        <Input
          placeholder="Display name (optional)"
          value={tiles.facebook.accountName}
          onChange={(e) => setTile('facebook', { accountName: e.target.value })}
        />
        <div className="flex gap-2">
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
        <Input
          placeholder="Access Token"
          type="password"
          value={tiles.instagram.token}
          onChange={(e) => setTile('instagram', { token: e.target.value })}
        />
        <Input
          placeholder="IG User ID (numeric)"
          value={tiles.instagram.userId}
          onChange={(e) => setTile('instagram', { userId: e.target.value })}
        />
        <Input
          placeholder="Display name (optional)"
          value={tiles.instagram.accountName}
          onChange={(e) => setTile('instagram', { accountName: e.target.value })}
        />
        <div className="flex gap-2">
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
        <Input
          placeholder="Bot Token (from BotFather)"
          type="password"
          value={tiles.telegram.token}
          onChange={(e) => setTile('telegram', { token: e.target.value })}
        />
        <Input
          placeholder="Bot username (optional, e.g. @ShopBot)"
          value={tiles.telegram.accountName}
          onChange={(e) => setTile('telegram', { accountName: e.target.value })}
        />
        {accounts.telegram && (
          <p className="text-xs text-muted-foreground">
            {accounts.telegram.webhook_registered_at
              ? 'Webhook registered. Retailer must message the bot once to activate alerts.'
              : 'Webhook pending — verify the bot token is correct.'}
          </p>
        )}
        <div className="flex gap-2">
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
