import { createContext, useContext, useState, useEffect, useRef, ReactNode } from 'react';
import { setBackendReachable } from '@/lib/api';

interface BackendConnectivityContextType {
  isBackendConnected: boolean;
}

const BackendConnectivityContext = createContext<BackendConnectivityContextType | undefined>(undefined);

export function useBackendConnectivity() {
  const ctx = useContext(BackendConnectivityContext);
  if (!ctx) throw new Error('useBackendConnectivity must be used within BackendConnectivityProvider');
  return ctx;
}

const POLL_CONNECTED = 30_000;
const POLL_DISCONNECTED = 10_000;
const HEALTH_TIMEOUT = 5_000;
const JITTER_MAX = 2_000;

/**
 * Polls /health to track backend reachability.
 *
 * Uses a single setTimeout chain (NOT setInterval) to avoid the race condition
 * where multiple overlapping intervals accumulate on rapid state changes.
 * The next poll interval is calculated AFTER each check completes, using the
 * freshly-determined connected state — so the switch from 30s → 10s is instant.
 */
export function BackendConnectivityProvider({ children }: { children: ReactNode }) {
  // null = initial check not yet completed (treated as connected to avoid banner flash)
  const [isConnected, setIsConnected] = useState<boolean | null>(null);
  const mountedRef = useRef(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    mountedRef.current = true;

    async function poll() {
      let connected: boolean;
      try {
        await fetch('/health', { signal: AbortSignal.timeout(HEALTH_TIMEOUT) });
        connected = true;
      } catch {
        connected = false;
      }

      if (!mountedRef.current) return;

      setIsConnected(connected);
      setBackendReachable(connected);

      // Schedule next poll with jitter to avoid thundering herd
      const base = connected ? POLL_CONNECTED : POLL_DISCONNECTED;
      const jitter = Math.floor(Math.random() * JITTER_MAX);
      timerRef.current = setTimeout(poll, base + jitter);
    }

    poll();

    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []); // Empty deps — single chain, never re-created

  return (
    <BackendConnectivityContext.Provider value={{ isBackendConnected: isConnected !== false }}>
      {children}
    </BackendConnectivityContext.Provider>
  );
}
