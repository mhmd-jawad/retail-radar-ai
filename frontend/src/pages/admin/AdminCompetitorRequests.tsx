import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Section } from '@/components/shared/Section';
import { fetchAdminCompetitorRequests, reviewAdminCompetitorRequest } from '@/lib/adapter';
import { relativeTime } from '@/lib/format';
import type { CompetitorRequest } from '@/types/domain';
import { AdminHeader, Empty, Status } from './AdminDashboard';

export default function AdminCompetitorRequests() {
  const [items, setItems] = useState<CompetitorRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    fetchAdminCompetitorRequests()
      .then(setItems)
      .catch((error) => toast.error(error?.message || 'Could not load competitor requests'))
      .finally(() => setLoading(false));
  }, []);

  async function review(item: CompetitorRequest, action: 'approve' | 'reject') {
    setBusyId(item.id);
    try {
      const next = await reviewAdminCompetitorRequest(item.id, action);
      setItems((current) => current.map((entry) => (entry.id === next.id ? { ...entry, ...next } : entry)));
      toast.success(
        action === 'approve'
          ? `${item.competitor_name} added to the competitor catalog`
          : `${item.competitor_name} request declined`,
      );
    } catch (error: any) {
      toast.error(error?.message || 'Could not update request');
    } finally {
      setBusyId(null);
    }
  }

  const pendingCount = items.filter((item) => item.status === 'pending').length;

  return (
    <>
      <AdminHeader title="Competitor Requests" subtitle="Missing competitors requested by shops" />
      <main className="px-6 lg:px-8 py-6 animate-fade-in">
        <Section title="Requests" subtitle={`${pendingCount} pending`}>
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
                    <th className="py-2 pr-4">Created</th>
                    <th className="py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id} className="border-b border-border/60">
                      <td className="py-3 pr-4 font-semibold">
                        {item.competitor_name}
                        {item.website_url && (
                          <a
                            href={item.website_url}
                            target="_blank"
                            rel="noreferrer"
                            className="block text-xs font-normal text-primary hover:underline"
                          >
                            {item.website_url}
                          </a>
                        )}
                      </td>
                      <td className="py-3 pr-4 text-muted-foreground">{item.shop_name || '-'}</td>
                      <td className="py-3 pr-4 text-muted-foreground">{item.requested_by_email || '-'}</td>
                      <td className="py-3 pr-4"><Status value={item.status} /></td>
                      <td className="py-3 pr-4 text-muted-foreground">{relativeTime(item.created_at)}</td>
                      <td className="py-3 text-right">
                        {item.status === 'pending' ? (
                          <div className="inline-flex gap-2">
                            <Button
                              size="sm"
                              disabled={busyId === item.id}
                              onClick={() => void review(item, 'approve')}
                            >
                              Approve
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={busyId === item.id}
                              onClick={() => void review(item, 'reject')}
                            >
                              Reject
                            </Button>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            Reviewed {item.reviewed_at ? relativeTime(item.reviewed_at) : ''}
                          </span>
                        )}
                      </td>
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
