import { useState, useRef, useEffect, useCallback } from 'react';
import { groupsApi, Message } from '@/lib/api';

interface UseMessageSearchOptions {
  groupIds: string[];
  selectedGroupId: string | null;
  debounceMs?: number;
}

interface UseMessageSearchReturn {
  query: string;
  setQuery: (q: string) => void;
  results: Message[];
  isSearching: boolean;
  hasMore: boolean;
  loadMore: () => void;
  clearSearch: () => void;
  isActive: boolean;
}

export function useMessageSearch({
  groupIds,
  selectedGroupId,
  debounceMs = 400,
}: UseMessageSearchOptions): UseMessageSearchReturn {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Message[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(1);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const isActive = query.trim().length >= 2;

  const doSearch = useCallback(async (q: string, pageNum: number, append: boolean) => {
    if (!mountedRef.current) return;
    setIsSearching(true);
    try {
      const ids = selectedGroupId ? [selectedGroupId] : groupIds;
      const resp = await groupsApi.searchMessages(q, ids, pageNum, 50);
      if (!mountedRef.current) return;
      const msgs = resp.data.messages;
      setResults(prev => append ? [...prev, ...msgs] : msgs);
      setHasMore(resp.data.has_more);
      setPage(pageNum);
    } catch {
      // silently ignore
    } finally {
      if (mountedRef.current) setIsSearching(false);
    }
  }, [groupIds, selectedGroupId]);

  // Debounced search on query change
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!isActive) {
      setResults([]);
      setHasMore(false);
      setPage(1);
      return;
    }
    timerRef.current = setTimeout(() => {
      doSearch(query.trim(), 1, false);
    }, debounceMs);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [query, isActive, debounceMs, doSearch]);

  const loadMore = useCallback(() => {
    if (isActive && hasMore && !isSearching) {
      doSearch(query.trim(), page + 1, true);
    }
  }, [isActive, hasMore, isSearching, query, page, doSearch]);

  const clearSearch = useCallback(() => {
    setQuery('');
    setResults([]);
    setHasMore(false);
    setPage(1);
  }, []);

  return { query, setQuery, results, isSearching, hasMore, loadMore, clearSearch, isActive };
}
