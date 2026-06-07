import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Section } from '@/components/shared/Section';
import {
  fetchAdminCompetitorRequests,
  fetchAdminNotifications,
  reviewAdminCompetitorRequest,
  updateAdminNotificationStatus,
  updateAdminShopStatus,
} from '@/lib/adapter';
import { relativeTime } from '@/lib/format';
import type { AppNotification, CompetitorRequest } from '@/types/domain';
import { AdminHeader, Empty, Status } from './AdminDashboard';

export default function AdminInbox() {
  const [requests, setRequests] = useState<CompetitorRequest[]>([]);
  const [items, setItems] = useState<AppNotification[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    load();
  }, []);

  function load() {
    setLoading(true);
    Promise.all([fetchAdminCompetitorRequests(), fetchAdminNotifications()])
      .then(([nextRequests, nextItems]) => {
        setRequests(nextRequests);
        setItems(nextItems);
      })
      .catch((error) => toast.error(error?.message || 'Could not load inbox'))
      .finally(() => setLoading(false));
  }

  function patchNotification(id: string, patch: Partial<AppNotification>) {
    setItems((current) => current.map((entry) => (entry.id === id ? { ...entry, ...patch } : entry)));
  }

  // ── Competitor requests ──────────────────────────────────────────────
  async function reviewRequest(item: CompetitorRequest, action: 'approve' | 'reject') {
    setBusyId(item.id);
    try {
      const next = await reviewAdminCompetitorRequest(item.id, action);
      setRequests((current) => current.map((entry) => (entry.id === next.id ? { ...entry, ...next } : entry)));
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

  // ── Other alerts (shop signups, system) ──────────────────────────────
  async function setStatus(item: AppNotification, status: AppNotification['status']) {
    try {
      const next = await updateAdminNotificationStatus(item.id, status);
      patchNotification(item.id, next);
      toast.success(`Alert ${status}`);
    } catch (error: any) {
      toast.error(error?.message || 'Could not update alert');
    }
  }

  async function approveShop(item: AppNotification) {
    const tenantId = item.payload?.tenant_id as string | undefined;
    if (!tenantId) return;
    setBusyId(item.id);
    try {
      await updateAdminShopStatus(tenantId, 'active');
      patchNotification(item.id, { status: 'resolved', resolved_at: new Date().toISOString() });
      toast.success('Shop approved');
    } catch (error: any) {
      toast.error(error?.message || 'Could not approve shop');
    } finally {
      setBusyId(null);
    }
  }

  const pendingRequests = requests.filter((item) => item.status === 'pending');
  // Competitor-request notifications are represented by the table above; keep the
  // alert inbox for everything else (shop signups, system messages).
  const alerts = items.filter((item) => item.type !== 'competitor_request');
  const archivedCount = alerts.filter((item) => item.status === 'resolved' || item.status === 'dismissed').length;
  const visibleAlerts = showAll
    ? alerts
    : alerts.filter((item) => item.status !== 'resolved' && item.status !== 'dismissed');

  return (
    <>
      <AdminHeader title="Requests & Alerts" subtitle="Competitor requests and notifications from shops" />
      <main className="px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        <Section title="Competitor Requests" subtitle={`${pendingRequests.length} pending`}>
          {loading ? (
            <Empty>Loading...</Empty>
          ) : requests.length === 0 ? (
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
                  {requests.map((item) => (
                    <tr key={item.id} className="border-b border-border/60">
                      <td className="py-3 pr-4 font-semibold">
                        {item.competitor_name}
                        {item.website_url && (
                          <a href={item.website_url} target="_blank" rel="noreferrer" className="block text-xs font-normal text-primary hover:underline">
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
                            <Button size="sm" disabled={busyId === item.id} onClick={() => void reviewRequest(item, 'approve')}>Approve</Button>
                            <Button size="sm" variant="outline" disabled={busyId === item.id} onClick={() => void reviewRequest(item, 'reject')}>Reject</Button>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">Reviewed {item.reviewed_at ? relativeTime(item.reviewed_at) : ''}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>

        <Section title="Other Alerts" subtitle={`${alerts.filter((item) => item.status === 'unread').length} unread`}>
          {archivedCount > 0 && (
            <div className="mb-3 flex justify-end">
              <Button size="sm" variant="ghost" onClick={() => setShowAll((value) => !value)}>
                {showAll ? 'Hide resolved & dismissed' : `Show resolved & dismissed (${archivedCount})`}
              </Button>
            </div>
          )}
          {loading ? (
            <Empty>Loading...</Empty>
          ) : visibleAlerts.length === 0 ? (
            <Empty>{alerts.length === 0 ? 'No alerts.' : 'Inbox clear — nothing pending.'}</Empty>
          ) : (
            <div className="space-y-3">
              {visibleAlerts.map((item) => {
                const canApproveShop = item.status !== 'resolved' && item.type === 'shop_signup' && item.payload?.tenant_id;
                return (
                  <div key={item.id} className="rounded-lg border border-border bg-card px-4 py-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <h3 className="text-sm font-semibold">{item.title}</h3>
                          <Status value={item.status} />
                        </div>
                        <p className="text-sm text-muted-foreground mt-1">{item.message}</p>
                        <div className="text-[11px] text-muted-foreground mt-2">
                          {item.shop_name || 'System'} - {relativeTime(item.created_at)}
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {canApproveShop && (
                          <Button size="sm" disabled={busyId === item.id} onClick={() => void approveShop(item)}>Approve shop</Button>
                        )}
                        {item.status === 'unread' && (
                          <Button size="sm" variant="secondary" onClick={() => void setStatus(item, 'read')}>Mark read</Button>
                        )}
                        {item.status !== 'resolved' && (
                          <Button size="sm" variant="outline" onClick={() => void setStatus(item, 'resolved')}>Resolve</Button>
                        )}
                        {item.status !== 'dismissed' && (
                          <Button size="sm" variant="ghost" onClick={() => void setStatus(item, 'dismissed')}>Dismiss</Button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Section>
      </main>
    </>
  );
}
