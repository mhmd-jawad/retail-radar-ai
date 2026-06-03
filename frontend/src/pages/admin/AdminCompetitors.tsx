import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Section } from '@/components/shared/Section';
import { fetchAdminCompetitors } from '@/lib/adapter';
import type { CompetitorOption } from '@/types/domain';
import { AdminHeader, Empty, Status } from './AdminDashboard';

export default function AdminCompetitors() {
  const [items, setItems] = useState<CompetitorOption[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAdminCompetitors()
      .then(setItems)
      .catch((error) => toast.error(error?.message || 'Could not load competitor catalog'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <AdminHeader title="Competitor Catalog" subtitle="Global competitors available for shop selection" />
      <main className="px-6 lg:px-8 py-6 animate-fade-in">
        <Section title="Available Competitors" subtitle={`${items.length} active competitors`}>
          {loading ? (
            <Empty>Loading competitors...</Empty>
          ) : items.length === 0 ? (
            <Empty>No competitors in the catalog yet.</Empty>
          ) : (
            <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
              {items.map((item) => (
                <div key={item.shop_code} className="rounded-lg border border-border bg-card px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold">{item.shop_name}</div>
                      <div className="text-xs text-muted-foreground font-mono mt-1">{item.shop_code}</div>
                    </div>
                    <Status value={item.is_active === false ? 'inactive' : 'active'} />
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
