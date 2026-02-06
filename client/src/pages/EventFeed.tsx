/**
 * Event Feed Page
 * Shows aggregated messages from all registered groups
 * Uses Supabase Realtime for instant message updates + polling fallback
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { Loader2, Calendar, Users, Settings, MessageSquare, Globe, RefreshCw, Zap } from 'lucide-react';
import { groupsApi, RegisteredGroup, Message, getApiErrorMessage } from '@/lib/api';
import ProtectedRoute from '@/components/ProtectedRoute';
import { useAuth } from '@/contexts/AuthContext';
import TopicFilter from '@/components/TopicFilter';
import supabase from '@/lib/supabase';

const FALLBACK_POLLING_INTERVAL = 60_000; // 60 seconds (Realtime is primary)

function EventFeedContent() {
  const [, setLocation] = useLocation();
  const { user, logout } = useAuth();
  const [groups, setGroups] = useState<RegisteredGroup[]>([]);
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
  const [realtimeConnected, setRealtimeConnected] = useState(false);
  const groupsRef = useRef<RegisteredGroup[]>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const selectedGroupIdRef = useRef<string | null>(null);
  const selectedTopicIdRef = useRef<number | null>(null);

  // Keep refs in sync
  useEffect(() => {
    groupsRef.current = groups;
  }, [groups]);
  useEffect(() => {
    selectedGroupIdRef.current = selectedGroupId;
  }, [selectedGroupId]);
  useEffect(() => {
    selectedTopicIdRef.current = selectedTopicId;
  }, [selectedTopicId]);

  // Load user's registered groups
  useEffect(() => {
    loadGroups();
  }, []);

  // Load messages when groups are loaded or filter changes (reset to page 1)
  useEffect(() => {
    if (groups.length > 0) {
      setPage(1);
      setHasMore(false);
      loadMessages();
    }
  }, [groups, selectedGroupId, selectedTopicId]);

  // Supabase Realtime subscription for instant message updates
  useEffect(() => {
    if (groups.length === 0) return;

    const groupIds = new Set(groups.map(g => g.id));

    const channel = supabase
      .channel('live-messages')
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'messages' },
        (payload) => {
          const newMsg = payload.new as Message;
          // Skip messages without a valid id
          if (!newMsg.id) return;
          // Only add if it belongs to one of the user's groups
          if (!groupIds.has(newMsg.group_id)) return;
          // Filter by selected group
          if (selectedGroupIdRef.current && newMsg.group_id !== selectedGroupIdRef.current) return;
          // Filter by selected topic
          if (selectedTopicIdRef.current !== null && newMsg.topic_id !== selectedTopicIdRef.current) return;
          // Skip deleted messages
          if (newMsg.is_deleted) return;

          setMessages(prev => {
            // Deduplicate
            if (prev.some(m => m.id === newMsg.id)) return prev;
            // Insert at the top (newest first)
            return [newMsg, ...prev];
          });
          setLastUpdated(new Date());
        }
      )
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'messages' },
        (payload) => {
          const updated = payload.new as Message;
          if (!groupIds.has(updated.group_id)) return;

          setMessages(prev =>
            updated.is_deleted
              ? prev.filter(m => m.id !== updated.id)
              : prev.map(m => m.id === updated.id ? updated : m)
          );
        }
      )
      .subscribe((status) => {
        setRealtimeConnected(status === 'SUBSCRIBED');
      });

    return () => {
      supabase.removeChannel(channel);
      setRealtimeConnected(false);
    };
  }, [groups]);

  // Fallback polling (only when on page 1, less frequent since Realtime is primary)
  useEffect(() => {
    if (groups.length === 0 || page > 1) return;

    intervalRef.current = setInterval(() => {
      silentRefresh();
    }, FALLBACK_POLLING_INTERVAL);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [groups, selectedGroupId, selectedTopicId, page]);

  const loadGroups = async () => {
    setIsLoading(true);
    try {
      const response = await groupsApi.getRegisteredGroups();
      // Deduplicate groups by id
      const seen = new Set<string>();
      const unique = response.data.filter((g: RegisteredGroup) => {
        if (!g.id || seen.has(g.id)) return false;
        seen.add(g.id);
        return true;
      });
      setGroups(unique);
    } catch (error) {
      toast.error(getApiErrorMessage(error, '그룹 목록을 불러오는데 실패했습니다'));
    } finally {
      setIsLoading(false);
    }
  };

  const fetchMessages = useCallback(async (currentGroups: RegisteredGroup[], pageNum: number = 1) => {
    const groupsToFetch = selectedGroupId
      ? currentGroups.filter(g => g.id === selectedGroupId)
      : currentGroups;

    const validGroups = groupsToFetch.filter(g => g.id);

    if (validGroups.length === 0) {
      return { messages: [] as Message[], hasMore: false };
    }

    const messagePromises = validGroups.map(group =>
      groupsApi.getGroupMessages(group.id, pageNum, 50)
    );

    const responses = await Promise.all(messagePromises);

    let anyHasMore = false;
    const seen = new Set<string>();
    const allMessages: Message[] = [];
    responses.forEach(response => {
      for (const msg of response.data.messages) {
        if (msg.id && !seen.has(msg.id)) {
          seen.add(msg.id);
          allMessages.push(msg);
        }
      }
      if (response.data.has_more) anyHasMore = true;
    });

    // Filter by topic if selected
    if (selectedTopicId !== null) {
      allMessages = allMessages.filter(msg => msg.topic_id === selectedTopicId);
    }

    // Sort by sent_at descending (newest first)
    allMessages.sort((a, b) =>
      new Date(b.sent_at).getTime() - new Date(a.sent_at).getTime()
    );

    return { messages: allMessages, hasMore: anyHasMore };
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

  // Silent refresh (no loading spinner, no error toast - used by auto-refresh)
  const silentRefresh = async () => {
    try {
      const result = await fetchMessages(groupsRef.current, 1);
      setMessages(result.messages);
      setHasMore(result.hasMore);
      setLastUpdated(new Date());
    } catch {
      // Silently ignore errors during auto-refresh
    }
  };

  // Manual refresh with spinner (resets to page 1)
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

  // Load more (next page, append with deduplication)
  const handleLoadMore = async () => {
    setIsLoadingMore(true);
    const nextPage = page + 1;
    try {
      const result = await fetchMessages(groups, nextPage);
      setMessages(prev => {
        const existingIds = new Set(prev.map(m => m.id));
        const newMessages = result.messages.filter(m => !existingIds.has(m.id));
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

  const getGroupById = (groupId: string) => {
    return groups.find(g => g.id === groupId);
  };

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

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  // If no groups registered, show onboarding
  if (groups.length === 0) {
    return (
      <div className="min-h-screen bg-background">
        <div className="border-b-4 border-border bg-card">
          <div className="container py-6">
            <div className="flex items-center justify-between">
              <h1 className="text-4xl font-bold">이벤트 피드</h1>
              <Button
                variant="outline"
                onClick={logout}
                className="border-2 border-border"
              >
                로그아웃
              </Button>
            </div>
          </div>
        </div>

        <div className="container py-8">
          <Card className="brutalist-card border-4">
            <CardContent className="pt-6">
              <div className="text-center py-12">
                <MessageSquare className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
                <h2 className="text-2xl font-bold mb-2">등록된 그룹이 없습니다</h2>
                <p className="text-muted-foreground mb-6">
                  텔레그램 그룹을 등록하여 이벤트 정보를 받아보세요
                </p>
                <Button
                  onClick={() => setLocation('/groups/select')}
                  className="border-2 border-border btn-pressed"
                  size="lg"
                >
                  <Globe className="mr-2 h-5 w-5" />
                  그룹 등록하기
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b-4 border-border bg-card sticky top-0 z-10">
        <div className="container py-4">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-3xl font-bold mb-1">이벤트 피드</h1>
              <p className="text-sm text-muted-foreground">
                {user?.first_name || user?.username || '사용자'}님의 그룹 메시지
              </p>
            </div>
            <div className="flex gap-2 items-center">
              {realtimeConnected && (
                <Badge variant="outline" className="border-green-500 text-green-600 hidden sm:flex items-center gap-1">
                  <Zap className="h-3 w-3" />
                  실시간
                </Badge>
              )}
              {lastUpdated && (
                <span className="text-xs text-muted-foreground hidden sm:inline">
                  {lastUpdated.toLocaleTimeString('ko-KR')} 업데이트
                </span>
              )}
              <Button
                variant="outline"
                onClick={handleManualRefresh}
                disabled={isRefreshing}
                className="border-2 border-border"
                size="sm"
              >
                <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
              </Button>
              <Button
                variant="outline"
                onClick={() => setLocation('/groups')}
                className="border-2 border-border"
                size="sm"
              >
                <Settings className="h-4 w-4 mr-2" />
                그룹 관리
              </Button>
              <Button
                variant="outline"
                onClick={logout}
                className="border-2 border-border"
                size="sm"
              >
                로그아웃
              </Button>
            </div>
          </div>

          {/* Filters */}
          <div className="flex gap-2 flex-wrap">
            <Button
              variant={selectedGroupId === null ? 'default' : 'outline'}
              onClick={() => setSelectedGroupId(null)}
              className="border-2 border-border"
              size="sm"
            >
              전체
            </Button>
            {groups.filter(g => g.id).map(group => (
              <Button
                key={`filter-${group.id}`}
                variant={selectedGroupId === group.id ? 'default' : 'outline'}
                onClick={() => setSelectedGroupId(group.id)}
                className="border-2 border-border"
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

      {/* Messages Feed */}
      <div className="container py-6">
        {isLoadingMessages ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : messages.length === 0 ? (
          <Card className="brutalist-card border-4">
            <CardContent className="pt-6">
              <div className="text-center py-12">
                <MessageSquare className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
                <h2 className="text-xl font-bold mb-2">메시지가 없습니다</h2>
                <p className="text-muted-foreground">
                  {selectedGroupId || selectedTopicId
                    ? '선택한 필터에 해당하는 메시지가 없습니다'
                    : '아직 크롤링된 메시지가 없습니다'
                  }
                </p>
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-4">
            {messages.filter(m => m.id).map((message, index) => {
              const group = getGroupById(message.group_id);
              return (
                <Card key={message.id ?? `msg-${index}`} className="brutalist-card border-4">
                  <CardContent className="p-4">
                    {/* Message Header */}
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-bold">
                            {message.sender_name || message.sender_username || 'Anonymous'}
                          </span>
                          {message.sender_username && (
                            <span className="text-xs text-muted-foreground">
                              @{message.sender_username}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <Badge variant="outline" className="border-2">
                            {group?.title || 'Unknown Group'}
                          </Badge>
                          {message.topic_title && (
                            <Badge variant="secondary" className="border-2">
                              {message.topic_title}
                            </Badge>
                          )}
                          <span className="text-xs text-muted-foreground">
                            <Calendar className="inline h-3 w-3 mr-1" />
                            {formatMessageTime(message.sent_at)}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Message Content */}
                    {message.content && (
                      <div className="text-sm whitespace-pre-wrap mb-3">
                        {message.content}
                      </div>
                    )}

                    {/* Media */}
                    {message.media_type !== 'text' && (
                      <div className="mt-2">
                        <Badge variant="outline" className="border-2">
                          {message.media_type}
                        </Badge>
                      </div>
                    )}

                    {message.media_url && message.media_type === 'photo' && (
                      <div className="mt-2">
                        <img
                          src={message.media_url}
                          alt={`${message.sender_name || '사용자'}의 미디어`}
                          className="max-w-full rounded border-2 border-border"
                        />
                      </div>
                    )}

                    {/* Edit indicator */}
                    {message.edit_count > 0 && (
                      <div className="mt-2 text-xs text-muted-foreground">
                        (수정됨 {message.edit_count}회)
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}

            {/* Load More Button */}
            {hasMore && (
              <div className="flex justify-center pt-4 pb-8">
                <Button
                  variant="outline"
                  onClick={handleLoadMore}
                  disabled={isLoadingMore}
                  className="border-2 border-border w-full max-w-md"
                >
                  {isLoadingMore ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  ) : null}
                  {isLoadingMore ? '불러오는 중...' : '더 보기'}
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
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
