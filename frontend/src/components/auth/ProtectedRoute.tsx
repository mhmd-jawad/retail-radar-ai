import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { homeForRole } from '@/lib/auth-routing';
import { useAuth } from '@/store/auth';
import type { AuthUser } from '@/types/domain';

interface Props {
  roles?: AuthUser['global_role'][];
}

export function ProtectedRoute({ roles }: Props) {
  const token = useAuth((state) => state.token);
  const user = useAuth((state) => state.user);
  const location = useLocation();

  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (roles?.length && (!user || !roles.includes(user.global_role))) {
    return <Navigate to={homeForRole(user?.global_role)} replace />;
  }

  return <Outlet />;
}
