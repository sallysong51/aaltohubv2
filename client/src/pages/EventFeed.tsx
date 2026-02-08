/**
 * Event Feed Page
 * Shows aggregated messages from all registered groups
 * Uses SSE (Server-Sent Events) via Postgres LISTEN/NOTIFY for instant updates + polling fallback
 *
 * Features: date separators, dark mode toggle, skeleton loading, new message banner,
 * infinite scroll, search, image lightbox, context menu, desktop sidebar, keyboard shortcuts
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import {
  Loader2, Users, Settings, MessageSquare, RefreshCw, Zap, LayoutDashboard,
  Search, X, Sun, Moon,
} from 'lucide-react';
import { groupsApi, RegisteredGroup, Message, getApiErrorMessage } from '@/lib/api';
import ProtectedRoute from '@/components/ProtectedRoute';
import { useAuth } from '@/contexts/AuthContext';
import TopicFilter from '@/components/TopicFilter';
import { useSSE } from '@/hooks/useSSE';
import { useInfiniteScroll } from '@/hooks/useInfiniteScroll';
import { useMessageSearch } from '@/hooks/useMessageSearch';
import { useKeyboardShortcuts, ShortcutAction } from '@/hooks/useKeyboardShortcuts';
import ScrollToTop from '@/components/ScrollToTop';
import GroupSidebar from '@/components/GroupSidebar';
import ImageLightbox, { PhotoEntry } from '@/components/ImageLightbox';
import MessageContextMenu from '@/components/MessageContextMenu';
import KeyboardShortcutsHelp from '@/components/KeyboardShortcutsHelp';
import { useTheme } from 'next-themes';

const FALLBACK_POLLING_INTERVAL = 60_000;

import DateSeparator from '@/components/DateSeparator';
import MessageListSkeleton from '@/components/MessageListSkeleton';
import { formatDateLabel } from '@/lib/dateFormat';

function EventFeedContent() {
  const [, setLocation] = useLocation();
  const { user, logout, isLoading: isAuthLoading } = useAuth();
  const { theme, setTheme } = useTheme();
  const [groups, setGroups] = useState<RegisteredGroup[]>([]);
  const [groupsLoadFailed, setGroupsLoadFailed] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [selectedTopicId, setSelectedTopicId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const groupsRef = useRef<RegisteredGroup[]>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const selectedGroupIdRef = useRef<string | null>(null);
  const selectedTopicIdRef = useRef<number | null>(null);

  // New message banner
  const [newMsgCount, setNewMsgCount] = useState(0);
  const isScrolledToTop = useRef(true);

  // Image lightbox
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState(0);

  // Search
  const [showSearchBar, setShowSearchBar] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Keyboard shortcuts help dialog
  const [showShortcutsHelp, setShowShortcutsHelp] = useState(false);

  // Focused message index (j/k navigation)
  const [focusedIndex, setFocusedIndex] = useState(-1);

  // Keep refs in sync
  useEffect(() => { groupsRef.current = groups; }, [groups]);
  useEffect(() => { selectedGroupIdRef.current = selectedGroupId; }, [selectedGroupId]);
  useEffect(() => { selectedTopicIdRef.current = selectedTopicId; }, [selectedTopicId]);

  // Scroll detection for new message banner
  useEffect(() => {
    const onScroll = () => {
      const atTop = window.scrollY < 100;
      isScrolledToTop.current = atTop;
      if (atTop) setNewMsgCount(0);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // Load user's registered groups
  useEffect(() => { loadGroups(); }, []);

  // Load messages when groups are loaded or filter changes
  useEffect(() => {
    if (groups.length > 0) {
      setPage(1);
      setHasMore(false);
      loadMessages();
    }
  }, [groups, selectedGroupId, selectedTopicId]);

  const loadGroups = async () => {
    setIsLoading(true);
    setGroupsLoadFailed(false);
    try {
      const response = await groupsApi.getRegisteredGroups();
      const seen = new Set<string>();
      const unique = response.data.filter((g: RegisteredGroup) => {
        if (!g.id || seen.has(g.id)) return false;
        seen.add(g.id);
        return true;
      });
      setGroups(unique);
    } catch (error) {
      setGroupsLoadFailed(true);
      toast.error(getApiErrorMessage(error, '그룹 목록을 불러오는데 실패했습니다'));
    } finally {
      setIsLoading(false);
    }
  };

  const fetchMessages = useCallback(async (currentGroups: RegisteredGroup[], pageNum: number = 1) => {
    const groupIds = selectedGroupId
      ? [selectedGroupId]
      : currentGroups.filter(g => g.id).map(g => g.id);

    if (groupIds.length === 0) return { messages: [] as Message[], hasMore: false };

    const response = await groupsApi.getAggregatedMessages(groupIds, pageNum, 50, selectedTopicId ?? undefined);
    return { messages: response.data.messages, hasMore: response.data.has_more };
  }, [selectedGroupId, selectedTopicId]);

  const loadMessages = async () => {
    setIsLoadingMessages(true);
    try {
      const result = await fetchMessages(groups, 1);
      setMessages(result.messages);
      setHasMore(result.hasMore);
      setPage(1);
      setLastUpdated(new Date());
    } catch (error) {
      toast.error(getApiErrorMessage(error, '메시지를 불러오는데 실패했습니다'));
    } finally {
      setIsLoadingMessages(false);
    }
  };

  const silentRefresh = async () => {
    try {
      const result = await fetchMessages(groupsRef.current, 1);
      setMessages(result.messages);
      setHasMore(result.hasMore);
      setLastUpdated(new Date());
    } catch { /* silent */ }
  };

  // SSE
  const handleSSEInsert = useCallback((newMsg: Message) => {
    if (!newMsg || !newMsg.group_id) return;
    if (selectedGroupIdRef.current && String(newMsg.group_id) !== String(selectedGroupIdRef.current)) return;
    if (selectedTopicIdRef.current !== null && newMsg.topic_id !== selectedTopicIdRef.current) return;
    if (newMsg.is_deleted) return;

    if (newMsg.content && newMsg.content.endsWith('...') && newMsg.content.length >= 200) {
      groupsApi.getGroupMessages(String(newMsg.group_id), 1, 50).then(resp => {
        const full = resp.data?.messages?.find(
          (m: Message) => m.telegram_message_id === newMsg.telegram_message_id
        );
        if (full) {
          setMessages(prev => {
            if (prev.some(m => m.telegram_message_id === full.telegram_message_id && String(m.group_id) === String(full.group_id))) {
              return prev.map(m => m.telegram_message_id === full.telegram_message_id && String(m.group_id) === String(full.group_id) ? full : m);
            }
            const updated = [full, ...prev];
            return updated.length > 500 ? updated.slice(0, 500) : updated;
          });
        }
      }).catch(() => {});
      return;
    }

    setMessages(prev => {
      if (prev.some(m => m.telegram_message_id === newMsg.telegram_message_id && String(m.group_id) === String(newMsg.group_id))) return prev;
      const updated = [newMsg, ...prev];
      return updated.length > 500 ? updated.slice(0, 500) : updated;
    });
    setLastUpdated(new Date());

    // New message banner
    if (!isScrolledToTop.current) {
      setNewMsgCount(prev => prev + 1);
    }
  }, []);

  const handleSSEUpdate = useCallback((updated: Message) => {
    if (!updated) return;
    setMessages(prev =>
      updated.is_deleted
        ? prev.filter(m => !(m.telegram_message_id === updated.telegram_message_id && String(m.group_id) === String(updated.group_id)))
        : prev.map(m => (m.telegram_message_id === updated.telegram_message_id && String(m.group_id) === String(updated.group_id)) ? { ...m, ...updated } : m)
    );
  }, []);

  const handleSSEDelete = useCallback((deleted: { telegram_message_id: number; group_id: string }) => {
    if (!deleted) return;
    setMessages(prev => prev.filter(m => !(m.telegram_message_id === deleted.telegram_message_id && String(m.group_id) === String(deleted.group_id))));
  }, []);

  const { isConnected: realtimeConnected } = useSSE({
    groupIds: groups.map(g => String(g.id)),
    onInsert: handleSSEInsert,
    onUpdate: handleSSEUpdate,
    onDelete: handleSSEDelete,
    onOverflow: loadMessages,
  });

  // Fallback polling
  useEffect(() => {
    if (groups.length === 0 || page > 1 || realtimeConnected) return;
    intervalRef.current = setInterval(silentRefresh, FALLBACK_POLLING_INTERVAL);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [groups, selectedGroupId, selectedTopicId, page, realtimeConnected]);

  // Manual refresh
  const handleManualRefresh = async () => {
    setIsRefreshing(true);
    try {
      const result = await fetchMessages(groups, 1);
      setMessages(result.messages);
      setHasMore(result.hasMore);
      setPage(1);
      setLastUpdated(new Date());
    } catch (error) {
      toast.error(getApiErrorMessage(error, '새로고침에 실패했습니다'));
    } finally {
      setIsRefreshing(false);
    }
  };

  // Load more
  const handleLoadMore = async () => {
    if (isLoadingMore) return;
    setIsLoadingMore(true);
    const nextPage = page + 1;
    try {
      const result = await fetchMessages(groups, nextPage);
      setMessages(prev => {
        const existingKeys = new Set(prev.map(m => `${m.telegram_message_id}_${m.group_id}`));
        const newMessages = result.messages.filter(m => !existingKeys.has(`${m.telegram_message_id}_${m.group_id}`));
        return [...prev, ...newMessages];
      });
      setHasMore(result.hasMore);
      setPage(nextPage);
      setLastUpdated(new Date());
    } catch (error) {
      toast.error(getApiErrorMessage(error, '추가 메시지를 불러오는데 실패했습니다'));
    } finally {
      setIsLoadingMore(false);
    }
  };

  // Search
  const search = useMessageSearch({
    groupIds: groups.filter(g => g.id).map(g => g.id),
    selectedGroupId,
  });

  // Infinite scroll
  const { sentinelRef } = useInfiniteScroll({
    onLoadMore: handleLoadMore,
    isLoading: isLoadingMore,
    hasMore,
    enabled: !search.isActive,
  });

  // Photo entries for lightbox
  const displayMessages = search.isActive ? search.results : messages;

  const photoEntries: PhotoEntry[] = useMemo(() => {
    return displayMessages
      .filter(m => m.media_type === 'photo' && m.media_url && /^https?:\/\//i.test(m.media_url))
      .map(m => ({
        url: m.media_url!,
        alt: `${m.sender_name || '사용자'}의 미디어`,
        messageId: m.telegram_message_id,
      }));
  }, [displayMessages]);

  const handlePhotoClick = useCallback((messageId: number) => {
    const idx = photoEntries.findIndex(p => p.messageId === messageId);
    if (idx >= 0) {
      setLightboxIndex(idx);
      setLightboxOpen(true);
    }
  }, [photoEntries]);

  const getGroupById = (groupId: string) => groups.find(g => g.id === groupId);

  const formatMessageTime = (sentAt: string) => {
    const date = new Date(sentAt);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return '방금 전';
    if (diffMins < 60) return `${diffMins}분 전`;
    if (diffHours < 24) return `${diffHours}시간 전`;
    if (diffDays < 7) return `${diffDays}일 전`;
    return date.toLocaleDateString('ko-KR');
  };

  // Keyboard shortcuts
  const focusSearch = useCallback(() => {
    setShowSearchBar(true);
    requestAnimationFrame(() => searchInputRef.current?.focus());
  }, []);

  const moveFocus = useCallback((dir: number) => {
    setFocusedIndex(prev => {
      const next = prev + dir;
      if (next < 0 || next >= displayMessages.length) return prev;
      const el = document.querySelector(`[data-msg-index="${next}"]`);
      el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      return next;
    });
  }, [displayMessages.length]);

  const handleGroupSelect = useCallback((groupId: string | null) => {
    setSelectedGroupId(groupId);
    setFocusedIndex(-1);
  }, []);

  const shortcutDefs: ShortcutAction[] = useMemo(() => [
    { key: '/', description: '검색', handler: focusSearch },
    { key: 'r', description: '새로고침', handler: handleManualRefresh },
    { key: 'j', description: '다음 메시지', handler: () => moveFocus(1) },
    { key: 'k', description: '이전 메시지', handler: () => moveFocus(-1) },
    { key: 'Escape', description: '검색/포커스 해제', handler: () => {
      search.clearSearch();
      setShowSearchBar(false);
      setFocusedIndex(-1);
    }},
    { key: '?', description: '단축키 도움말', handler: () => setShowShortcutsHelp(true), shift: true },
    ...groups.slice(0, 9).map((g, i) => ({
      key: String(i + 1),
      description: `그룹 ${i + 1}`,
      handler: () => handleGroupSelect(g.id),
    })),
    { key: '0', description: '전체 그룹', handler: () => handleGroupSelect(null) },
  ], [focusSearch, handleManualRefresh, moveFocus, search, groups, handleGroupSelect]);

  useKeyboardShortcuts({ shortcuts: shortcutDefs });

  // --- Render ---

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!isLoading && groups.length === 0 && groupsLoadFailed) {
    return (
      <div className="min-h-screen bg-background">
        <div className="border-b border-border bg-card">
          <div className="container py-6">
            <div className="flex items-center justify-between">
              <h1 className="text-4xl font-bold">이벤트 피드</h1>
              <Button variant="outline" onClick={logout}>로그아웃</Button>
            </div>
          </div>
        </div>
        <div className="container py-8">
          <Card className="refined-card">
            <CardContent className="pt-6">
              <div className="text-center py-12">
                <MessageSquare className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
                <h2 className="text-xl font-bold mb-2">그룹 목록을 불러올 수 없습니다</h2>
                <p className="text-muted-foreground mb-6">서버 연결을 확인하고 다시 시도해주세요</p>
                <Button onClick={loadGroups} size="lg">다시 시도</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <div className="min-h-screen bg-background">
        <div className="border-b border-border bg-card">
          <div className="container py-6">
            <div className="flex items-center justify-between">
              <h1 className="text-4xl font-bold">이벤트 피드</h1>
              <div className="flex gap-2">
                {!isAuthLoading && user?.role === 'admin' && (
                  <Button variant="outline" onClick={() => setLocation('/admin')} size="sm">
                    <LayoutDashboard className="h-4 w-4 mr-2" />관리자
                  </Button>
                )}
                <Button variant="outline" onClick={logout} size="sm">로그아웃</Button>
              </div>
            </div>
          </div>
        </div>
        <div className="container py-8">
          <Card className="refined-card">
            <CardContent className="pt-6">
              <div className="text-center py-12">
                <Users className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
                <h2 className="text-xl font-bold mb-2">등록된 그룹이 없습니다</h2>
                <p className="text-muted-foreground mb-6">텔레그램 그룹을 추가하면 메시지가 여기에 표시됩니다</p>
                <Button onClick={() => setLocation('/groups/select')} size="lg">그룹 추가하기</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* New message banner */}
      {newMsgCount > 0 && (
        <button
          className="fixed top-20 left-1/2 -translate-x-1/2 z-20 bg-primary text-primary-foreground px-4 py-2 rounded-full shadow-lg text-sm font-medium hover:opacity-90 transition-opacity"
          onClick={() => {
            window.scrollTo({ top: 0, behavior: 'smooth' });
            setNewMsgCount(0);
          }}
        >
          새 메시지 {newMsgCount}개 ↑
        </button>
      )}

      {/* Header */}
      <div className="border-b border-border bg-card sticky top-0 z-10">
        <div className="container py-4">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-4xl font-bold mb-1">이벤트 피드</h1>
              <p className="text-sm text-muted-foreground">
                {user?.first_name || user?.username || '사용자'}님의 그룹 메시지
              </p>
            </div>
            <div className="flex gap-2 items-center">
              {realtimeConnected && (
                <Badge variant="outline" className="border-green-500 text-green-600 hidden sm:flex items-center gap-1">
                  <Zap className="h-3 w-3" />실시간
                </Badge>
              )}
              {lastUpdated && (
                <span className="text-xs text-muted-foreground hidden sm:inline">
                  {lastUpdated.toLocaleTimeString('ko-KR')} 업데이트
                </span>
              )}
              {/* Search toggle */}
              <Button
                variant={showSearchBar ? 'default' : 'outline'}
                size="sm"
                onClick={() => {
                  setShowSearchBar(!showSearchBar);
                  if (!showSearchBar) requestAnimationFrame(() => searchInputRef.current?.focus());
                  else search.clearSearch();
                }}
              >
                <Search className="h-4 w-4" />
              </Button>
              {/* Dark mode toggle */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              >
                {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </Button>
              <Button
                variant="outline"
                onClick={handleManualRefresh}
                disabled={isRefreshing}
                size="sm"
              >
                <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
              </Button>
              {!isAuthLoading && user?.role === 'admin' && (
                <Button variant="outline" onClick={() => setLocation('/admin')} size="sm">
                  <LayoutDashboard className="h-4 w-4 mr-2" />관리자
                </Button>
              )}
              <Button variant="outline" onClick={() => setLocation('/groups')} size="sm">
                <Settings className="h-4 w-4 mr-2" />그룹 관리
              </Button>
              <Button variant="outline" onClick={logout} size="sm">로그아웃</Button>
            </div>
          </div>

          {/* Search bar */}
          {showSearchBar && (
            <div className="flex items-center gap-2 mb-3">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <input
                  ref={searchInputRef}
                  type="text"
                  placeholder="메시지 검색... (최소 2글자)"
                  value={search.query}
                  onChange={(e) => search.setQuery(e.target.value)}
                  className="w-full pl-10 pr-8 py-2 text-sm rounded-lg border border-border bg-background focus:outline-none focus:ring-2 focus:ring-primary"
                />
                {search.query && (
                  <button
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    onClick={search.clearSearch}
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
              {search.isSearching && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
            </div>
          )}

          {/* Mobile group filter buttons */}
          <div className="flex gap-2 flex-wrap md:hidden">
            <Button
              variant={selectedGroupId === null ? 'default' : 'outline'}
              onClick={() => handleGroupSelect(null)}
              size="sm"
            >
              전체
            </Button>
            {groups.filter(g => g.id).map(group => (
              <Button
                key={`filter-${group.id}`}
                variant={selectedGroupId === group.id ? 'default' : 'outline'}
                onClick={() => handleGroupSelect(group.id)}
                size="sm"
              >
                {group.title}
              </Button>
            ))}
          </div>

          {/* Topic Filter */}
          {selectedGroupId && (
            <div className="mt-3">
              <TopicFilter
                groupId={selectedGroupId}
                selectedTopicId={selectedTopicId}
                onTopicSelect={setSelectedTopicId}
              />
            </div>
          )}
        </div>
      </div>

      {/* Main content with sidebar */}
      <div className="md:flex">
        {/* Desktop sidebar */}
        <aside className="hidden md:block w-64 shrink-0 border-r border-border sticky top-[140px] h-[calc(100vh-140px)]">
          <GroupSidebar
            groups={groups}
            selectedGroupId={selectedGroupId}
            onGroupSelect={handleGroupSelect}
          />
        </aside>

        {/* Messages Feed */}
        <div className="flex-1 min-w-0">
          <div className="container py-3">
            {isLoadingMessages && !search.isActive ? (
              <MessageListSkeleton />
            ) : displayMessages.length === 0 ? (
              <Card className="refined-card">
                <CardContent className="pt-6">
                  <div className="text-center py-12">
                    <MessageSquare className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
                    <h2 className="text-xl font-bold mb-2">
                      {search.isActive ? '검색 결과가 없습니다' : '메시지가 없습니다'}
                    </h2>
                    <p className="text-muted-foreground">
                      {search.isActive
                        ? `"${search.query}"에 대한 결과를 찾을 수 없습니다`
                        : selectedGroupId || selectedTopicId
                          ? '선택한 필터에 해당하는 메시지가 없습니다'
                          : '아직 크롤링된 메시지가 없습니다'
                      }
                    </p>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-0 bg-card border border-border rounded-lg overflow-hidden divide-y divide-border">
                {displayMessages.map((message, index) => {
                  const group = getGroupById(message.group_id);
                  const showDateSep = index === 0 ||
                    new Date(displayMessages[index - 1].sent_at).toDateString() !== new Date(message.sent_at).toDateString();

                  return (
                    <div key={message.id ?? `${message.telegram_message_id}-${message.group_id}`}>
                      {showDateSep && <DateSeparator date={message.sent_at} />}
                      <MessageContextMenu message={message} group={group}>
                        <div
                          data-msg-index={index}
                          className={`p-2 hover:bg-accent/50 transition-colors ${focusedIndex === index ? 'ring-2 ring-primary ring-inset' : ''}`}
                        >
                          {/* Message Header */}
                          <div className="flex items-start justify-between gap-2 mb-1">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="font-semibold text-xs">
                                  {message.sender_name || 'Anonymous'}
                                </span>
                                <Badge variant="outline" className="text-xs py-0">
                                  {group?.title || 'Unknown Group'}
                                </Badge>
                              </div>
                            </div>
                            <span className="text-xs text-muted-foreground whitespace-nowrap">
                              {formatMessageTime(message.sent_at)}
                            </span>
                          </div>

                          {/* Content */}
                          {message.content && (
                            <div className="text-xs whitespace-pre-wrap break-words mb-1">
                              {message.content}
                            </div>
                          )}

                          {/* Media */}
                          {message.media_type && (
                            <div className="flex items-center gap-1">
                              {message.media_type === 'photo' && message.media_url && /^https?:\/\//i.test(message.media_url) ? (
                                <img
                                  src={message.media_url}
                                  alt={`${message.sender_name || '사용자'}의 미디어`}
                                  className="max-h-24 rounded border border-border cursor-pointer hover:opacity-80 transition-opacity"
                                  loading="lazy"
                                  onClick={() => handlePhotoClick(message.telegram_message_id)}
                                />
                              ) : (
                                <Badge variant="secondary" className="text-xs py-0">
                                  {message.media_type}
                                </Badge>
                              )}
                            </div>
                          )}
                        </div>
                      </MessageContextMenu>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Infinite scroll sentinel */}
            {!search.isActive && hasMore && (
              <div ref={sentinelRef} className="flex justify-center py-4">
                {isLoadingMore && <Loader2 className="h-5 w-5 animate-spin text-primary" />}
              </div>
            )}

            {/* Search load more */}
            {search.isActive && search.hasMore && (
              <div className="flex justify-center pt-3 pb-4">
                <Button
                  variant="outline"
                  onClick={search.loadMore}
                  disabled={search.isSearching}
                  size="sm"
                >
                  {search.isSearching ? <Loader2 className="h-3 w-3 animate-spin mr-2" /> : null}
                  검색 결과 더 보기
                </Button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Floating scroll-to-top */}
      <ScrollToTop />

      {/* Image lightbox */}
      <ImageLightbox
        photos={photoEntries}
        initialIndex={lightboxIndex}
        isOpen={lightboxOpen}
        onClose={() => setLightboxOpen(false)}
      />

      {/* Keyboard shortcuts help */}
      <KeyboardShortcutsHelp
        open={showShortcutsHelp}
        onOpenChange={setShowShortcutsHelp}
        shortcuts={shortcutDefs.filter(s => s.key !== '0' && !/^[1-9]$/.test(s.key))}
      />
    </div>
  );
}

export default function EventFeed() {
  return (
    <ProtectedRoute>
      <EventFeedContent />
    </ProtectedRoute>
  );
}
