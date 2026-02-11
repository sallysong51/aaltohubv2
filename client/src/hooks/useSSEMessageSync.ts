/**
 * Shared SSE message sync utilities for EventFeed and AdminDashboard.
 *
 * Both pages receive insert/update/delete events via SSE and apply
 * identical logic: dedup, truncation fetch, cap at 500 messages.
 * This hook extracts that shared logic.
 */
import { useCallback, type Dispatch, type SetStateAction } from 'react';
import type { Message } from '@/lib/api';

const MAX_MESSAGES = 500;
const TRUNCATION_THRESHOLD = 200;

interface SSEMessageSyncOptions {
  setMessages: Dispatch<SetStateAction<Message[]>>;
  /** Fetch full messages from API when truncated content is detected */
  fetchFullMessages: (groupId: string) => Promise<Message[]>;
  /** Optional: filter by selected group ID (null = accept all) */
  selectedGroupIdRef?: React.RefObject<string | null>;
  /** Optional: filter by selected topic ID (null = accept all) */
  selectedTopicIdRef?: React.RefObject<number | null>;
  /** Called after a new message is inserted (e.g., for scroll-to-bottom) */
  onInserted?: () => void;
}

export function useSSEMessageSync({
  setMessages,
  fetchFullMessages,
  selectedGroupIdRef,
  selectedTopicIdRef,
  onInserted,
}: SSEMessageSyncOptions) {
  const handleInsert = useCallback((newMsg: Message) => {
    if (!newMsg || !newMsg.group_id) return;
    if (selectedGroupIdRef?.current && String(newMsg.group_id) !== String(selectedGroupIdRef.current)) return;
    if (selectedTopicIdRef?.current !== null && selectedTopicIdRef?.current !== undefined && newMsg.topic_id !== selectedTopicIdRef.current) return;
    if (newMsg.is_deleted) return;

    // Truncated content — fetch full message from API
    if (newMsg.content && newMsg.content.endsWith('...') && newMsg.content.length >= TRUNCATION_THRESHOLD) {
      fetchFullMessages(String(newMsg.group_id)).then(messages => {
        const full = messages.find(
          (m) => m.telegram_message_id === newMsg.telegram_message_id
        );
        if (full) {
          setMessages(prev => {
            const exists = prev.some(m => m.telegram_message_id === full.telegram_message_id && String(m.group_id) === String(full.group_id));
            if (exists) {
              return prev.map(m => m.telegram_message_id === full.telegram_message_id && String(m.group_id) === String(full.group_id) ? full : m);
            }
            const updated = [...prev, full];
            return updated.length > MAX_MESSAGES ? updated.slice(-MAX_MESSAGES) : updated;
          });
        }
      }).catch(() => {});
      return;
    }

    setMessages(prev => {
      if (prev.some(m => m.telegram_message_id === newMsg.telegram_message_id && String(m.group_id) === String(newMsg.group_id))) return prev;
      const updated = [...prev, newMsg];
      return updated.length > MAX_MESSAGES ? updated.slice(-MAX_MESSAGES) : updated;
    });
    onInserted?.();
  }, [setMessages, fetchFullMessages, selectedGroupIdRef, selectedTopicIdRef, onInserted]);

  const handleUpdate = useCallback((updated: Message) => {
    if (!updated) return;
    setMessages(prev =>
      updated.is_deleted
        ? prev.filter(m => !(m.telegram_message_id === updated.telegram_message_id && String(m.group_id) === String(updated.group_id)))
        : prev.map(m => (m.telegram_message_id === updated.telegram_message_id && String(m.group_id) === String(updated.group_id)) ? { ...m, ...updated } : m)
    );
  }, [setMessages]);

  const handleDelete = useCallback((deleted: { telegram_message_id: number; group_id: string }) => {
    if (!deleted) return;
    setMessages(prev => prev.filter(m => !(m.telegram_message_id === deleted.telegram_message_id && String(m.group_id) === String(deleted.group_id))));
  }, [setMessages]);

  return { handleInsert, handleUpdate, handleDelete };
}
