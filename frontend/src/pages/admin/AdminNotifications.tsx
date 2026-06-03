import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Section } from '@/components/shared/Section';
import { fetchAdminNotifications, updateAdminNotificationStatus } from '@/lib/adapter';
import { relativeTime } from '@/lib/format';
import type { AppNotification } from '@/types/domain';
import { AdminHeader, Empty, Status } from './AdminDashboard';

export default function AdminNotifications() {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    load();
  }, []);

  function load() {
    setLoading(true);
    fetchAdminNotifications()
      .then(setItems)
      .catch((error) => toast.error(error?.message || 'Could not load notifications'))
      .finally(() => setLoading(false));
  }

  async function setStatus(item: AppNotification, status: AppNotification['status']) {
    try {
      const next = await updateAdminNotificationStatus(item.id, status);
      setItems((current) => current.map((entry) => (entry.id === next.id ? { ...entry, ...next } : entry)));
      toast.success(`Notification ${status}`);
    } catch (error: any) {
      toast.error(error?.message || 'Could not update notification');
    }
  }

  return (
    <>
      <AdminHeader title="Notifications" subtitle="Requests and alerts sent from business workspaces" />
      <main className="px-6 lg:px-8 py-6 animate-fade-in">
        <Section title="Admin Inbox" subtitle={`${items.filter((item) => item.status === 'unread').length} unread`}>
          {loading ? (
            <Empty>Loading notifications...</Empty>
          ) : items.length === 0 ? (
            <Empty>No notifications yet.</Empty>
          ) : (
            <div className="space-y-3">
              {items.map((item) => (
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
                      {item.status === 'unread' && (
                        <Button size="sm" variant="secondary" onClick={() => void setStatus(item, 'read')}>Mark read</Button>
                      )}
                      {item.status !== 'resolved' && (
                        <Button size="sm" onClick={() => void setStatus(item, 'resolved')}>Resolve</Button>
                      )}
                      {item.status !== 'dismissed' && (
                        <Button size="sm" variant="outline" onClick={() => void setStatus(item, 'dismissed')}>Dismiss</Button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Section>
      </main>
    </>
  );
}
