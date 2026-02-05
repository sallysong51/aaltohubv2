/**
 * Protected Route Component
 * Redirects to login if not authenticated
 */
import { ReactNode } from 'react';
import { Redirect } from 'wouter';
import { useAuth } from '@/contexts/AuthContext';
import { Loader2 } from 'lucide-react';

interface ProtectedRouteProps {
  children: ReactNode;
  adminOnly?: boolean;
  requireAdmin?: boolean;
}

export default function ProtectedRoute({ children, adminOnly = false, requireAdmin = false }: ProtectedRouteProps) {
  const isAdminRequired = adminOnly || requireAdmin;
  const { user, isLoading, isAuthenticated } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Redirect to="/login" />;
  }

  if (isAdminRequired && user?.role !== 'admin') {
    return <Redirect to="/groups" />;
  }

  return <>{children}</>;
}
