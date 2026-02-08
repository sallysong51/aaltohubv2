import { useEffect, useRef, useCallback } from 'react';

interface UseInfiniteScrollOptions {
  onLoadMore: () => void;
  isLoading: boolean;
  hasMore: boolean;
  enabled?: boolean;
  rootMargin?: string;
}

export function useInfiniteScroll({
  onLoadMore,
  isLoading,
  hasMore,
  enabled = true,
  rootMargin = '0px 0px 200px 0px',
}: UseInfiniteScrollOptions) {
  const observerRef = useRef<IntersectionObserver | null>(null);
  const isLoadingRef = useRef(isLoading);
  const hasMoreRef = useRef(hasMore);
  const onLoadMoreRef = useRef(onLoadMore);

  useEffect(() => { isLoadingRef.current = isLoading; }, [isLoading]);
  useEffect(() => { hasMoreRef.current = hasMore; }, [hasMore]);
  useEffect(() => { onLoadMoreRef.current = onLoadMore; }, [onLoadMore]);

  const sentinelRef = useCallback((node: HTMLDivElement | null) => {
    if (observerRef.current) {
      observerRef.current.disconnect();
      observerRef.current = null;
    }

    if (!node || !enabled) return;

    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !isLoadingRef.current && hasMoreRef.current) {
          onLoadMoreRef.current();
        }
      },
      { rootMargin, threshold: 0 },
    );

    observerRef.current.observe(node);
  }, [enabled, rootMargin]);

  useEffect(() => {
    return () => { observerRef.current?.disconnect(); };
  }, []);

  return { sentinelRef };
}
