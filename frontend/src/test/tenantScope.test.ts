import { beforeEach, describe, expect, it } from 'vitest';
import { scopedSkuKey, tenantScopeKey } from '@/lib/tenantScope';
import { useAuth } from '@/store/auth';
import { useSettings } from '@/store/settings';
import type { AuthUser, CampaignCreative } from '@/types/domain';

const shopA: AuthUser = {
  user_id: 'user-a',
  email: 'owner-a@example.com',
  full_name: 'Owner A',
  global_role: 'shop',
  tenant_id: 'tenant-a',
  tenant_slug: 'shop-a',
};

const shopB: AuthUser = {
  user_id: 'user-b',
  email: 'owner-b@example.com',
  full_name: 'Owner B',
  global_role: 'shop',
  tenant_id: 'tenant-b',
  tenant_slug: 'shop-b',
};

const creative: CampaignCreative = {
  headline: 'Headline',
  subheadline: 'Subheadline',
  ad_copy_short: 'Short copy',
  ad_copy_long: 'Long copy',
  instagram_post: 'Instagram',
  facebook_post: 'Facebook',
  telegram_broadcast: 'Telegram',
  cta_primary: 'Shop now',
  cta_secondary: 'Learn more',
  image_url: '',
  tone_used: 'aspirational',
  generation_confidence: 1,
  fallback_used: false,
  social_posts: [],
};

describe('tenant-scoped browser state', () => {
  beforeEach(() => {
    localStorage.clear();
    useAuth.setState({ token: null, user: null });
    useSettings.setState({ recState: {}, campaignCache: {} });
  });

  it('uses stable tenant scope keys', () => {
    expect(tenantScopeKey(shopA)).toBe('tenant-a');
    expect(scopedSkuKey('SKU-1', tenantScopeKey(shopA))).toBe('tenant-a::SKU-1');
  });

  it('keeps same-SKU recommendation and campaign state isolated by shop', () => {
    useAuth.getState().setSession('token-a', shopA);
    useSettings.getState().setRecStatus('SKU-SHARED', 'approved');
    useSettings.getState().setCampaign('SKU-SHARED', creative);

    useAuth.getState().setSession('token-b', shopB);
    useSettings.getState().setRecStatus('SKU-SHARED', 'rejected');

    const { recState, campaignCache } = useSettings.getState();
    expect(recState['tenant-a::SKU-SHARED'].status).toBe('approved');
    expect(recState['tenant-b::SKU-SHARED'].status).toBe('rejected');
    expect(recState['SKU-SHARED']).toBeUndefined();
    expect(campaignCache['tenant-a::SKU-SHARED']).toEqual(creative);
    expect(campaignCache['tenant-b::SKU-SHARED']).toBeUndefined();
  });
});
