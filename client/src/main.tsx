import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

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
