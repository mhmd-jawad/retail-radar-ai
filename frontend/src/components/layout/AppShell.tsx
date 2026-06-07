import { Outlet, useNavigate } from 'react-router-dom';
import { Eye, X } from 'lucide-react';
import { AppSidebar } from './AppSidebar';
import { useAuth } from '@/store/auth';

export function AppShell() {
  return (
    <div className="min-h-screen flex bg-background">
      <AppSidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        <ImpersonationBanner />
        <Outlet />
      </div>
    </div>
  );
}

function ImpersonationBanner() {
  const user = useAuth((state) => state.user);
  const stopImpersonation = useAuth((state) => state.stopImpersonation);
  const navigate = useNavigate();

  if (!user?.read_only) return null;

  function exit() {
    stopImpersonation();
    navigate('/admin/shops');
  }

  return (
    <div className="flex items-center justify-between gap-3 border-b border-amber-500/30 bg-amber-500/10 px-6 py-2 text-amber-100">
      <div className="flex items-center gap-2 text-[13px]">
        <Eye className="h-4 w-4 text-amber-300" />
        <span>
          Viewing <span className="font-semibold">{user.tenant_name || 'shop'}</span> as admin
          <span className="ml-1 rounded bg-amber-500/20 px-1.5 py-0.5 text-[11px] font-mono uppercase tracking-wider">read-only</span>
        </span>
      </div>
      <button
        onClick={exit}
        className="inline-flex items-center gap-1.5 rounded-md border border-amber-400/40 px-2.5 py-1 text-[12px] font-semibold text-amber-100 hover:bg-amber-500/20 transition"
      >
        <X className="h-3.5 w-3.5" />
        Exit to admin
      </button>
    </div>
  );
}
