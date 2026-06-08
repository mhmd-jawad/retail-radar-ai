import { Section } from '@/components/shared/Section';
import { useAuth } from '@/store/auth';
import { AdminHeader } from './AdminDashboard';

export default function AdminSettings() {
  const user = useAuth((state) => state.user);

  return (
    <>
      <AdminHeader title="Admin Settings" subtitle="Admin account and workspace separation" />
      <main className="px-6 lg:px-8 py-6 animate-fade-in max-w-3xl">
        <Section title="Admin Account">
          <div className="space-y-3 text-sm">
            <Row label="Name" value={user?.full_name || '-'} />
            <Row label="Email" value={user?.email || '-'} />
            <Row label="Role" value={user?.global_role || '-'} />
          </div>
        </Section>

        <Section title="Workspace Rules" subtitle="Current separation policy" className="mt-6">
          <div className="space-y-2 text-sm text-muted-foreground">
            <p>Admin accounts can access admin routes, shop lists, competitor requests, notifications, and global competitor catalog data.</p>
            <p>Shop accounts can access only their tenant-scoped inventory, recommendations, competitors, and profile screens.</p>
            <p>Admin users are blocked from shop routes unless a dedicated “view as shop” feature is added later.</p>
          </div>
        </Section>
      </main>
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-border/60 pb-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
