import { Outlet } from 'react-router-dom';
import { AppSidebar } from './AppSidebar';

export function AppShell() {
  return (
    <div className="min-h-screen flex bg-background">
      <AppSidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        <Outlet />
      </div>
    </div>
  );
}
