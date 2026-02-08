/**
 * Custom hook for SSE (Server-Sent Events) with exponential backoff reconnection.
 *
 * Replaces native EventSource auto-reconnect (~3s fixed interval, floods console)
 * with manual reconnection: 2s → 4s → 8s → ... → max 60s.
 * Pauses reconnection when backend is known to be unreachable.
 *
 * Safety features:
 * - mountedRef guard prevents setState after unmount
 * - Sustained-success backoff: delay only resets after connection stays open for 5s
 *   (prevents rapid retry loops on flaky connections that open then drop immediately)
 * - Listeners are attached to specific EventSource instances, so old listeners are
 *   garbage-collected when the EventSource is closed and dereferenced
 */
import { useState, useEffect, useRef } from 'react';
import { SSE_BASE_URL } from '@/lib/api';
import { useBackendConnectivity } from '@/contexts/BackendConnectivityContext';

const INITIAL_DELAY = 2000;
const MAX_DELAY = 60000;
const BACKOFF_FACTOR = 2;
const SUSTAINED_SUCCESS_MS = 5000; // Must stay open this long before resetting backoff

interface UseSSEOptions {
  /** Group IDs to subscribe to (comma-joined internally). Empty = disabled. */
  groupIds: string[];
  /** Called when a new message arrives (SSE 'insert' event) */
  onInsert?: (msg: any) => void;
  /** Called when a message is updated (SSE 'update' event) */
  onUpdate?: (msg: any) => void;
  /** Called when a message is deleted (SSE 'delete' event) */
  onDelete?: (data: { telegram_message_id: number; group_id: string }) => void;
  /** Called when server drops events due to backpressure */
  onOverflow?: () => void;
}

export function useSSE({ groupIds, onInsert, onUpdate, onDelete, onOverflow }: UseSSEOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const { isBackendConnected } = useBackendConnectivity();
  const esRef = useRef<EventSource | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const delayRef = useRef(INITIAL_DELAY);
  const mountedRef = useRef(true);
  const openedAtRef = useRef(0); // Timestamp when connection opened (for sustained-success check)

  // Store latest callbacks in refs to avoid re-triggering the effect
  const onInsertRef = useRef(onInsert);
  const onUpdateRef = useRef(onUpdate);
  const onDeleteRef = useRef(onDelete);
  const onOverflowRef = useRef(onOverflow);

  useEffect(() => { onInsertRef.current = onInsert; }, [onInsert]);
  useEffect(() => { onUpdateRef.current = onUpdate; }, [onUpdate]);
  useEffect(() => { onDeleteRef.current = onDelete; }, [onDelete]);
  useEffect(() => { onOverflowRef.current = onOverflow; }, [onOverflow]);

  const groupIdsKey = groupIds.sort().join(',');

  useEffect(() => {
    mountedRef.current = true;

    if (!groupIdsKey || !SSE_BASE_URL) return;

    const token = localStorage.getItem('access_token');
    if (!token) return;

    function cleanup() {
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    }

    function connect() {
      cleanup();

      if (!mountedRef.current) return;

      if (!isBackendConnected) {
        // Backend is known to be down — wait and check again
        timerRef.current = setTimeout(connect, INITIAL_DELAY);
        return;
      }

      const currentToken = localStorage.getItem('access_token');
      if (!currentToken) return;

      const url = `${SSE_BASE_URL}/api/events/stream?token=${encodeURIComponent(currentToken)}&groups=${encodeURIComponent(groupIdsKey)}`;
      const es = new EventSource(url);
      esRef.current = es;

      es.onopen = () => {
        if (!mountedRef.current) { es.close(); return; }
        openedAtRef.current = Date.now();
        setIsConnected(true);
      };

      es.onerror = () => {
        es.close();
        esRef.current = null;
        if (!mountedRef.current) return;
        setIsConnected(false);

        // Sustained-success backoff: only reset delay if connection was open long enough.
        // This prevents rapid retry loops on flaky backends that accept then drop connections.
        const wasOpenFor = openedAtRef.current > 0 ? Date.now() - openedAtRef.current : 0;
        if (wasOpenFor >= SUSTAINED_SUCCESS_MS) {
          delayRef.current = INITIAL_DELAY;
        }
        openedAtRef.current = 0;

        const delay = delayRef.current;
        delayRef.current = Math.min(delay * BACKOFF_FACTOR, MAX_DELAY);
        console.warn(`[SSE] Connection lost. Reconnecting in ${delay / 1000}s`);
        timerRef.current = setTimeout(connect, delay);
      };

      es.addEventListener('insert', (e: MessageEvent) => {
        if (!mountedRef.current) return;
        try {
          const data = JSON.parse(e.data);
          onInsertRef.current?.(data);
        } catch (err) {
          console.error('[SSE] insert handler error:', err);
        }
      });

      es.addEventListener('update', (e: MessageEvent) => {
        if (!mountedRef.current) return;
        try {
          const data = JSON.parse(e.data);
          onUpdateRef.current?.(data);
        } catch (err) {
          console.error('[SSE] update handler error:', err);
        }
      });

      es.addEventListener('delete', (e: MessageEvent) => {
        if (!mountedRef.current) return;
        try {
          const data = JSON.parse(e.data);
          onDeleteRef.current?.(data);
        } catch (err) {
          console.error('[SSE] delete handler error:', err);
        }
      });

      es.addEventListener('overflow', () => {
        if (!mountedRef.current) return;
        console.warn('[SSE] Overflow — server dropped events');
        onOverflowRef.current?.();
      });

      // Circuit breaker recovery or other server-side recovery — reload from DB
      es.addEventListener('refresh', () => {
        if (!mountedRef.current) return;
        console.info('[SSE] Server requested full refresh (recovery)');
        onOverflowRef.current?.();
      });

      // Server-initiated reconnect (e.g. max connection duration reached)
      es.addEventListener('reconnect', () => {
        if (!mountedRef.current) return;
        console.info('[SSE] Server requested reconnect');
        delayRef.current = INITIAL_DELAY; // Reset backoff for clean reconnect
        es.close();
        esRef.current = null;
        setIsConnected(false);
        timerRef.current = setTimeout(connect, 500); // Quick reconnect
      });
    }

    connect();

    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [groupIdsKey, isBackendConnected]);

  return { isConnected };
}
