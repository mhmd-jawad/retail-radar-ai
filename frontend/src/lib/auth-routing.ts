import type { AuthUser } from '@/types/domain';

export function homeForRole(role?: AuthUser['global_role'] | null) {
  return role === 'admin' ? '/admin' : '/overview';
}

export function pathAllowedForRole(path: string, role?: AuthUser['global_role'] | null) {
  if (!role) return false;
  if (path.startsWith('/admin')) return role === 'admin';
  return role === 'shop';
}

export function redirectForLogin(user: AuthUser, requestedPath: string) {
  return pathAllowedForRole(requestedPath, user.global_role) ? requestedPath : homeForRole(user.global_role);
}
