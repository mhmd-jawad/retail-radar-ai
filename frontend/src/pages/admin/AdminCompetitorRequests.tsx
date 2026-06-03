import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Section } from '@/components/shared/Section';
import { fetchAdminCompetitorRequests } from '@/lib/adapter';
import { relativeTime } from '@/lib/format';
import type { CompetitorRequest } from '@/types/domain';
import { AdminHeader, Empty, Status } from './AdminDashboard';

export default function AdminCompetitorRequests() {
  const [items, setItems] = useState<CompetitorRequest[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAdminCompetitorRequests()
      .then(setItems)
      .catch((error) => toast.error(error?.message || 'Could not load competitor requests'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <AdminHeader title="Competitor Requests" subtitle="Missing competitors requested by shops" />
      <main className="px-6 lg:px-8 py-6 animate-fade-in">
        <Section title="Requests" subtitle={`${items.filter((item) => item.status === 'pending').length} pending`}>
          {loading ? (
            <Empty>Loading competitor requests...</Empty>
          ) : items.length === 0 ? (
            <Empty>No competitor requests yet.</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-4">Competitor</th>
                    <th className="py-2 pr-4">Shop</th>
                    <th className="py-2 pr-4">Requested By</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id} className="border-b border-border/60">
                      <td className="py-3 pr-4 font-semibold">{item.competitor_name}</td>
                      <td className="py-3 pr-4 text-muted-foreground">{item.shop_name || '-'}</td>
                      <td className="py-3 pr-4 text-muted-foreground">{item.requested_by_email || '-'}</td>
                      <td className="py-3 pr-4"><Status value={item.status} /></td>
                      <td className="py-3 text-muted-foreground">{relativeTime(item.created_at)}</td>
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
