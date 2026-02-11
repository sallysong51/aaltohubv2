import { useState, useEffect, lazy, Suspense } from "react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/NotFound";
import { Route, Switch, Redirect } from "wouter";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { BackendConnectivityProvider, useBackendConnectivity } from "./contexts/BackendConnectivityContext";
import Login from "./pages/Login";
import Signup from "./pages/Signup";

// Lazy-loaded pages (code splitting for faster initial load)
const EmailLinking = lazy(() => import("./pages/EmailLinking"));
const GroupSelection = lazy(() => import("./pages/GroupSelection"));
const UserGroups = lazy(() => import("./pages/UserGroups"));
const EventFeed = lazy(() => import("./pages/EventFeed"));
const AdminDashboard = lazy(() => import("./pages/AdminDashboard"));
const InviteAccept = lazy(() => import("./pages/InviteAccept"));
const GroupSettings = lazy(() => import("./pages/GroupSettings"));
const CrawlerManagement = lazy(() => import("./pages/CrawlerManagement"));
const UserManagement = lazy(() => import("./pages/UserManagement"));
const UnmappedGroups = lazy(() => import("./pages/UnmappedGroups"));
const Privacy = lazy(() => import("./pages/Privacy"));

function HomeRedirect() {
  const { isAuthenticated, user, isLoading } = useAuth();

  if (isLoading) {
    return null;
  }

  if (!isAuthenticated) {
    return <Redirect to="/login" />;
  }

  // Redirect based on role
  if (user?.role === 'admin') {
    return <Redirect to="/admin" />;
  }

  return <Redirect to="/feed" />;
}

function Router() {
  return (
    <Switch>
      <Route path="/" component={HomeRedirect} />
      <Route path="/login" component={Login} />
      <Route path="/signup" component={Signup} />
      <Route path="/email-linking" component={EmailLinking} />
      <Route path="/feed" component={EventFeed} />
      <Route path="/groups/select" component={GroupSelection} />
      <Route path="/groups" component={UserGroups} />
      <Route path="/admin" component={AdminDashboard} />
      <Route path="/admin/crawler" component={CrawlerManagement} />
      <Route path="/admin/users" component={UserManagement} />
      <Route path="/admin/unmapped-groups" component={UnmappedGroups} />
      <Route path="/invite/:token" component={InviteAccept} />
      <Route path="/groups/:groupId/settings" component={GroupSettings} />
      <Route path="/privacy" component={Privacy} />
      <Route path="/404" component={NotFound} />
      {/* Final fallback route */}
      <Route component={NotFound} />
    </Switch>
  );
}

function OfflineBanner() {
  const [isOffline, setIsOffline] = useState(!navigator.onLine);

  useEffect(() => {
    const goOffline = () => setIsOffline(true);
    const goOnline = () => setIsOffline(false);
    window.addEventListener('offline', goOffline);
    window.addEventListener('online', goOnline);
    return () => {
      window.removeEventListener('offline', goOffline);
      window.removeEventListener('online', goOnline);
    };
  }, []);

  if (!isOffline) return null;
  return (
    <div className="fixed top-0 left-0 right-0 z-50 bg-destructive text-destructive-foreground text-center py-1 text-sm">
      네트워크 연결이 끊어졌습니다. 인터넷 연결을 확인해주세요.
    </div>
  );
}

function BackendBanner() {
  const { isBackendConnected } = useBackendConnectivity();
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (!isBackendConnected) {
      const timer = setTimeout(() => setShow(true), 3000);
      return () => clearTimeout(timer);
    }
    setShow(false);
  }, [isBackendConnected]);

  if (!show) return null;
  return (
    <div className="fixed top-0 left-0 right-0 z-50 bg-amber-500 text-white text-center py-1 text-sm">
      백엔드에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.
    </div>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider defaultTheme="light">
        <AuthProvider>
          <BackendConnectivityProvider>
            <TooltipProvider>
              <OfflineBanner />
              <BackendBanner />
              <Toaster />
              <Suspense fallback={<div className="min-h-screen flex items-center justify-center"><div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" /></div>}>
                <Router />
              </Suspense>
            </TooltipProvider>
          </BackendConnectivityProvider>
        </AuthProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
