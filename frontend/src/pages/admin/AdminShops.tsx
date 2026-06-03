import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Section } from '@/components/shared/Section';
import { fetchAdminTenants } from '@/lib/adapter';
import { fmtNum, relativeTime } from '@/lib/format';
import type { AdminTenant } from '@/types/domain';
import { AdminHeader, Empty, Status } from './AdminDashboard';

export default function AdminShops() {
  const [tenants, setTenants] = useState<AdminTenant[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAdminTenants()
      .then(setTenants)
      .catch((error) => toast.error(error?.message || 'Could not load shops'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <AdminHeader title="Shops" subtitle="All business tenants and their isolated workspaces" />
      <main className="px-6 lg:px-8 py-6 animate-fade-in">
        <Section title="Business Accounts" subtitle={`${tenants.length} shops registered`}>
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
                    <th className="py-2">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {tenants.map((tenant) => (
                    <tr key={tenant.id} className="border-b border-border/60">
                      <td className="py-3 pr-4">
                        <div className="font-semibold">{tenant.name}</div>
                        <div className="text-xs text-muted-foreground">{tenant.slug}</div>
                      </td>
                      <td className="py-3 pr-4 text-muted-foreground">{tenant.contact_email || '-'}</td>
                      <td className="py-3 pr-4 font-mono">{fmtNum(tenant.sku_count)}</td>
                      <td className="py-3 pr-4 font-mono">{fmtNum(tenant.competitor_count)}</td>
                      <td className="py-3 pr-4"><Status value={tenant.onboarding_status || 'unknown'} /></td>
                      <td className="py-3 text-muted-foreground">{relativeTime(tenant.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      </main>
    </>
  );
}
