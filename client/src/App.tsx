import { useState, useEffect } from "react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/NotFound";
import { Route, Switch, Redirect } from "wouter";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { groupsApi, authApi } from "./lib/api";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import EmailLinking from "./pages/EmailLinking";
import GroupSelection from "./pages/GroupSelection";
import UserGroups from "./pages/UserGroups";
import EventFeed from "./pages/EventFeed";
import AdminDashboard from "./pages/AdminDashboard";
import InviteAccept from "./pages/InviteAccept";
import GroupSettings from "./pages/GroupSettings";
import CrawlerManagement from "./pages/CrawlerManagement";
import UserManagement from "./pages/UserManagement";
import Privacy from "./pages/Privacy";

function HomeRedirect() {
  const { isAuthenticated, user, isLoading } = useAuth();
  const [hasGroups, setHasGroups] = useState<boolean | null>(null);
  const [emailLinkRequired, setEmailLinkRequired] = useState<boolean | null>(null);

  useEffect(() => {
    if (!isAuthenticated || isLoading) return;

    let cancelled = false;

    // Check email linking status first (forced migration)
    authApi.getEmailLinkingStatus()
      .then(res => {
        if (cancelled) return;
        if (res.data.email_link_required) {
          setEmailLinkRequired(true);
          return;
        }
        setEmailLinkRequired(false);

        // Then check groups
        return groupsApi.getRegisteredGroups();
      })
      .then(res => {
        if (cancelled || !res) return;
        setHasGroups(res.data.length > 0);
      })
      .catch(err => {
        if (cancelled) return;
        console.error('HomeRedirect check failed:', err);
        // On error, assume email not required and has groups to avoid redirect loop
        setEmailLinkRequired(false);
        setHasGroups(true);
      });

    return () => { cancelled = true; };
  }, [isAuthenticated, isLoading]);

  if (isLoading || (isAuthenticated && (emailLinkRequired === null || hasGroups === null))) {
    return null;
  }

  if (!isAuthenticated) {
    return <Redirect to="/login" />;
  }

  // Force email linking if required (migration checkpoint)
  if (emailLinkRequired) {
    return <Redirect to="/email-linking" />;
  }

  // No registered groups → go to group selection
  if (hasGroups === false) {
    return <Redirect to="/groups/select" />;
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

function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider defaultTheme="light">
        <AuthProvider>
          <TooltipProvider>
            <OfflineBanner />
            <Toaster />
            <Router />
          </TooltipProvider>
        </AuthProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
