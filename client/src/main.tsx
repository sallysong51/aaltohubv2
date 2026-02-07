import { createRoot } from "react-dom/client";
import * as Sentry from "@sentry/react";
import App from "./App";
import "./index.css";

// Initialize Sentry error tracking (only if DSN is configured)
const sentryDsn = import.meta.env.VITE_SENTRY_DSN;
if (sentryDsn) {
  Sentry.init({
    dsn: sentryDsn,
    environment: import.meta.env.MODE,
    tracesSampleRate: 0,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
  });
}

// Load analytics if configured (completely optional)
(() => {
  const analyticsEndpoint = import.meta.env.VITE_ANALYTICS_ENDPOINT;
  const analyticsWebsiteId = import.meta.env.VITE_ANALYTICS_WEBSITE_ID;

  if (analyticsEndpoint && typeof analyticsEndpoint === 'string' && analyticsEndpoint.startsWith('http')) {
    const script = document.createElement('script');
    script.defer = true;
    script.src = `${analyticsEndpoint}/umami`;
    script.setAttribute('data-website-id', analyticsWebsiteId || '');
    document.body.appendChild(script);
  }
})();

createRoot(document.getElementById("root")!).render(<App />);
