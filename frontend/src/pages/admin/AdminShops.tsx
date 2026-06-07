import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Section } from '@/components/shared/Section';
import { fetchAdminTenants, impersonateShop, updateAdminShopStatus } from '@/lib/adapter';
import { fmtNum, relativeTime } from '@/lib/format';
import type { AdminTenant } from '@/types/domain';
import { useAuth } from '@/store/auth';
import { AdminHeader, Empty, Status } from './AdminDashboard';

type ShopStatus = 'pending' | 'active' | 'suspended' | 'archived';

export default function AdminShops() {
  const [tenants, setTenants] = useState<AdminTenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const navigate = useNavigate();
  const startImpersonation = useAuth((state) => state.startImpersonation);

  useEffect(() => {
    fetchAdminTenants()
      .then(setTenants)
      .catch((error) => toast.error(error?.message || 'Could not load shops'))
      .finally(() => setLoading(false));
  }, []);

  async function viewAsShop(tenant: AdminTenant) {
    setBusyId(tenant.id);
    try {
      const session = await impersonateShop(tenant.id);
      startImpersonation(session.access_token, session.user);
      toast.success(`Viewing ${tenant.name} (read-only)`);
      navigate('/overview');
    } catch (error: any) {
      toast.error(error?.message || 'Could not open shop view');
    } finally {
      setBusyId(null);
    }
  }

  async function setStatus(tenant: AdminTenant, status: ShopStatus) {
    setBusyId(tenant.id);
    try {
      const next = await updateAdminShopStatus(tenant.id, status);
      setTenants((current) => current.map((entry) => (entry.id === next.id ? { ...entry, ...next } : entry)));
      toast.success(`${tenant.name} ${status === 'active' ? 'approved' : status}`);
    } catch (error: any) {
      toast.error(error?.message || 'Could not update shop');
    } finally {
      setBusyId(null);
    }
  }

  const pendingCount = tenants.filter((tenant) => tenant.onboarding_status === 'pending').length;

  return (
    <>
      <AdminHeader title="Shops" subtitle="All business tenants and their isolated workspaces" />
      <main className="px-6 lg:px-8 py-6 animate-fade-in">
        <Section
          title="Business Accounts"
          subtitle={`${tenants.length} shops registered${pendingCount ? ` · ${pendingCount} awaiting approval` : ''}`}
        >
          {loading ? (
            <Empty>Loading shops...</Empty>
          ) : tenants.length === 0 ? (
            <Empty>No shops yet.</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-4">Shop</th>
                    <th className="py-2 pr-4">Email</th>
                    <th className="py-2 pr-4">SKUs</th>
                    <th className="py-2 pr-4">Competitors</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-4">Created</th>
                    <th className="py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {tenants.map((tenant) => {
                    const status = (tenant.onboarding_status || 'unknown') as string;
                    const busy = busyId === tenant.id;
                    return (
                      <tr key={tenant.id} className="border-b border-border/60">
                        <td className="py-3 pr-4">
                          <div className="font-semibold">{tenant.name}</div>
                          <div className="text-xs text-muted-foreground">{tenant.slug}</div>
                        </td>
                        <td className="py-3 pr-4 text-muted-foreground">{tenant.contact_email || '-'}</td>
                        <td className="py-3 pr-4 font-mono">{fmtNum(tenant.sku_count)}</td>
                        <td className="py-3 pr-4 font-mono">{fmtNum(tenant.competitor_count)}</td>
                        <td className="py-3 pr-4"><Status value={status} /></td>
                        <td className="py-3 pr-4 text-muted-foreground">{relativeTime(tenant.created_at)}</td>
                        <td className="py-3 text-right">
                          <div className="inline-flex gap-2">
                            <Button size="sm" variant="secondary" disabled={busy} onClick={() => void viewAsShop(tenant)}>
                              View as shop
                            </Button>
                            {status !== 'active' && (
                              <Button size="sm" disabled={busy} onClick={() => void setStatus(tenant, 'active')}>
                                {status === 'pending' ? 'Approve' : 'Reactivate'}
                              </Button>
                            )}
                            {status === 'active' && (
                              <Button size="sm" variant="outline" disabled={busy} onClick={() => void setStatus(tenant, 'suspended')}>
                                Suspend
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      </main>
    </>
  );
}
