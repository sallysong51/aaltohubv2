/**
 * Admin Dashboard - Telegram UI Clone
 * Design Philosophy: Telegram-Native Brutalism
 * - Split-screen layout (groups list + message viewer)
 * - Telegram-style message bubbles
 * - Realtime updates via SSE (Server-Sent Events)
 */
import { useState, useEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { toast } from 'sonner';
import { Loader2, Users, AlertCircle, RefreshCw, LogOut, Circle, Hash, Plus, ChevronRight, ExternalLink, UserCog, BarChart3, ArrowLeft, Zap, Download } from 'lucide-react';
import { adminApi, RegisteredGroup, Message, getApiErrorMessage, SSE_BASE_URL } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import ProtectedRoute from '@/components/ProtectedRoute';
import { useLocation } from 'wouter';
import MessageBubble from '@/components/MessageBubble';
import TopicFilter from '@/components/TopicFilter';

function AdminDashboardContent() {
  const [, setLocation] = useLocation();
  const { user, logout } = useAuth();

  const [groups, setGroups] = useState<RegisteredGroup[]>([]);
  const [groupsLoadFailed, setGroupsLoadFailed] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<RegisteredGroup | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoadingGroups, setIsLoadingGroups] = useState(true);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [selectedTopicId, setSelectedTopicId] = useState<number | null>(null);
  const [crawlerStatusMap, setCrawlerStatusMap] = useState<Map<string, { status: string; progress: number; total: number }>>(new Map());
  const [liveCrawlerStatus, setLiveCrawlerStatus] = useState<{
    running: boolean; connected: boolean; groups_count: number;
    messages_received: number; historical_crawl_running: boolean;
    crawled_groups: number; uptime_seconds: number;
    currently_crawling_group_id?: number | null;
    currently_crawling_group_title?: string | null;
    seconds_since_last_event?: number | null;
    start_error?: string | null;
  } | null>(null);
  const [crawlerUnreachable, setCrawlerUnreachable] = useState(false);
  const [realtimeConnected, setRealtimeConnected] = useState(false);
  const [groupSearch, setGroupSearch] = useState('');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  // Load groups on mount
  useEffect(() => {
    loadGroups();
    loadLiveCrawlerStatus();
  }, []);

  // Determine if any group is actively crawling
  const hasActiveCrawling = Array.from(crawlerStatusMap.values()).some(
    s => s.status === 'initializing'
  );

  // Poll crawler statuses: 5s during active crawling, 30s otherwise
  useEffect(() => {
    const intervalMs = hasActiveCrawling ? 5000 : 30000;
    loadCrawlerStatuses();
    loadLiveCrawlerStatus();
    const interval = setInterval(() => {
      loadCrawlerStatuses();
      loadLiveCrawlerStatus();
    }, intervalMs);
    return () => clearInterval(interval);
  }, [hasActiveCrawling]);

  // SSE subscription — single persistent connection for the selected group
  // Replaces Supabase Realtime. EventSource auto-reconnects on disconnect.
  useEffect(() => {
    if (!selectedGroup) return;

    // P1-1: SSE requires direct backend access — skip if not configured (Vercel proxy can't stream)
    if (!SSE_BASE_URL) {
      console.warn('[AdminDashboard] SSE_BASE_URL not configured — realtime disabled, using polling only');
      return;
    }

    const token = localStorage.getItem('access_token');
    if (!token) return;

    const groupId = String(selectedGroup.id);
    const url = `${SSE_BASE_URL}/api/events/stream?token=${encodeURIComponent(token)}&groups=${encodeURIComponent(groupId)}`;
    const es = new EventSource(url);

    es.addEventListener('insert', (e: MessageEvent) => {
      try {
        const newMessage: Message = JSON.parse(e.data);
        if (!newMessage) return;
        if (selectedTopicId !== null && newMessage.topic_id !== selectedTopicId) return;

        // P1-3: NOTIFY payload may be truncated at 8000 bytes — detect and fetch full message
        // Fetch a small page (10 msgs) to find the matching message by telegram_message_id
        if (newMessage.content && newMessage.content.endsWith('...') && newMessage.content.length >= 200) {
          adminApi.getGroupMessages(groupId, 1, 10, 30, selectedTopicId).then((res) => {
            const fullMsg = res.data.messages?.find(
              (m: Message) => m.telegram_message_id === newMessage.telegram_message_id
            );
            if (fullMsg) {
              setMessages((prev) => {
                if (prev.some(m => m.telegram_message_id === fullMsg.telegram_message_id && String(m.group_id) === String(fullMsg.group_id))) {
                  return prev.map(m => m.telegram_message_id === fullMsg.telegram_message_id && String(m.group_id) === String(fullMsg.group_id) ? fullMsg : m);
                }
                const updated = [...prev, fullMsg];
                return updated.length > 500 ? updated.slice(-500) : updated;
              });
            }
          }).catch(() => { /* best-effort */ });
          return;
        }

        setMessages((prev) => {
          if (prev.some(m => m.telegram_message_id === newMessage.telegram_message_id && String(m.group_id) === String(newMessage.group_id))) return prev;
          const updated = [...prev, newMessage];
          return updated.length > 500 ? updated.slice(-500) : updated;
        });
        requestAnimationFrame(() => {
          messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        });
      } catch (err) {
        console.error('[AdminDashboard] SSE insert handler error:', err);
      }
    });

    es.addEventListener('update', (e: MessageEvent) => {
      try {
        const updated: Message = JSON.parse(e.data);
        if (!updated) return;
        setMessages((prev) =>
          updated.is_deleted
            ? prev.filter((m) => !(m.telegram_message_id === updated.telegram_message_id && String(m.group_id) === String(updated.group_id)))
            : prev.map((m) =>
                m.telegram_message_id === updated.telegram_message_id ? { ...m, ...updated } : m
              )
        );
      } catch (err) {
        console.error('[AdminDashboard] SSE update handler error:', err);
      }
    });

    es.addEventListener('delete', (e: MessageEvent) => {
      try {
        const deleted: { telegram_message_id: number; group_id: string } = JSON.parse(e.data);
        if (!deleted) return;
        setMessages((prev) =>
          prev.filter((m) => !(m.telegram_message_id === deleted.telegram_message_id && String(m.group_id) === String(deleted.group_id)))
        );
      } catch (err) {
        console.error('[AdminDashboard] SSE delete handler error:', err);
      }
    });

    // P1-5: Overflow event — backend dropped events due to backpressure, refresh from DB
    es.addEventListener('overflow', () => {
      console.warn('[AdminDashboard] SSE overflow — refreshing messages from server');
      if (selectedGroup) {
        loadMessages(selectedGroup.id, 1);
      }
    });

    es.onopen = () => setRealtimeConnected(true);
    es.onerror = () => {
      setRealtimeConnected(false);
      console.warn('[AdminDashboard] SSE connection error — will auto-reconnect');
    };

    return () => {
      es.close();
      setRealtimeConnected(false);
    };
  }, [selectedGroup, selectedTopicId]);

  const loadLiveCrawlerStatus = async () => {
    try {
      const res = await adminApi.getLiveCrawlerStatus();
      setLiveCrawlerStatus(res.data);
      setCrawlerUnreachable(false);
    } catch (err: any) {
      if (err?.response?.status === 503) {
        setCrawlerUnreachable(true);
        setLiveCrawlerStatus(null);
      }
    }
  };

  const handleRestartCrawler = async () => {
    try {
      await adminApi.restartLiveCrawler();
      toast.success('라이브 크롤러가 재시작되었습니다');
      loadLiveCrawlerStatus();
    } catch (error) {
      toast.error(getApiErrorMessage(error, '크롤러 재시작에 실패했습니다'));
    }
  };

  const handleTriggerCrawl = async (groupId: string) => {
    try {
      await adminApi.triggerHistoricalCrawl(groupId);
      toast.success('역사 크롤링이 시작되었습니다');
    } catch (error) {
      toast.error(getApiErrorMessage(error, '크롤링 시작에 실패했습니다'));
    }
  };

  const loadCrawlerStatuses = async () => {
    try {
      const statusResponse = await adminApi.getCrawlerStatus();
      const statusMap = new Map<string, { status: string; progress: number; total: number }>();
      (statusResponse.data || []).forEach((s: { group_id: string; status?: string; initial_crawl_progress?: number; initial_crawl_total?: number }) => {
        statusMap.set(String(s.group_id), {
          status: s.status || 'inactive',
          progress: s.initial_crawl_progress || 0,
          total: s.initial_crawl_total || 0,
        });
      });
      setCrawlerStatusMap(statusMap);
    } catch {
      // Non-critical: leave map as-is
    }
  };

  const loadGroups = async () => {
    setIsLoadingGroups(true);
    setGroupsLoadFailed(false);
    try {
      const response = await adminApi.getAllGroups();
      setGroups(response.data);
      await loadCrawlerStatuses();

      // Auto-select first group (use functional update to avoid stale closure — P2-4.8)
      if (response.data.length > 0) {
        setSelectedGroup((prev) => prev ?? response.data[0]);
      }
    } catch (error) {
      setGroupsLoadFailed(true);
      toast.error(getApiErrorMessage(error, '그룹 목록을 불러오는데 실패했습니다'));
    } finally {
      setIsLoadingGroups(false);
    }
  };

  const loadMessages = async (groupId: string, pageNum: number = 1) => {
    setIsLoadingMessages(true);
    try {
      const response = await adminApi.getGroupMessages(groupId, pageNum, 150, 30, selectedTopicId);
      
      if (pageNum === 1) {
        setMessages(response.data.messages);
        // Scroll to bottom for initial load
        requestAnimationFrame(() => {
          messagesEndRef.current?.scrollIntoView({ behavior: 'auto' });
        });
      } else {
        setMessages((prev) => [...response.data.messages, ...prev]);
      }
      
      setHasMore(response.data.has_more);
      setPage(pageNum);
    } catch (error) {
      toast.error(getApiErrorMessage(error, '메시지를 불러오는데 실패했습니다'));
    } finally {
      setIsLoadingMessages(false);
    }
  };

  // Load messages when group is selected
  useEffect(() => {
    if (selectedGroup) {
      loadMessages(selectedGroup.id);
    }
  }, [selectedGroup]);

  const handleGroupSelect = (group: RegisteredGroup) => {
    setSelectedGroup(group);
    setMessages([]);  // Clear stale messages immediately on group change (P2-3.4)
    setPage(1);
  };

  const handleLoadMore = () => {
    if (selectedGroup && !isLoadingMessages) {
      loadMessages(selectedGroup.id, page + 1);
    }
  };

  const handleLogout = async () => {
    await logout();
    setLocation('/login');
  };

  const formatTimestamp = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
  };

  const getCrawlerStatus = (group: RegisteredGroup): 'active' | 'inactive' | 'error' | 'initializing' => {
    const info = crawlerStatusMap.get(String(group.telegram_id || group.id));
    if (!info) return 'inactive';
    if (info.status === 'active') return 'active';
    if (info.status === 'error') return 'error';
    if (info.status === 'initializing') return 'initializing';
    return 'inactive';
  };

  const getCrawlerProgressInfo = (group: RegisteredGroup) => {
    return crawlerStatusMap.get(String(group.telegram_id || group.id));
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    if (date.toDateString() === today.toDateString()) {
      return '오늘';
    } else if (date.toDateString() === yesterday.toDateString()) {
      return '어제';
    } else {
      return date.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' });
    }
  };

  // Group messages by date
  const groupMessagesByDate = (msgs: Message[]) => {
    const grouped: { [key: string]: Message[] } = {};
    msgs.forEach((msg) => {
      const dateKey = new Date(msg.sent_at).toDateString();
      if (!grouped[dateKey]) {
        grouped[dateKey] = [];
      }
      grouped[dateKey].push(msg);
    });
    return grouped;
  };

  const groupedMessages = groupMessagesByDate(messages);

  // If no groups registered, redirect to group selection
  // If no groups (confirmed, not API error), redirect to group selection
  useEffect(() => {
    if (!isLoadingGroups && groups.length === 0 && !groupsLoadFailed) {
      setLocation('/groups/select');
    }
  }, [isLoadingGroups, groups.length, groupsLoadFailed, setLocation]);

  if (isLoadingGroups) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (groups.length === 0 && groupsLoadFailed) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
          <p className="text-lg font-medium mb-2">그룹 목록을 불러올 수 없습니다</p>
          <p className="text-sm text-muted-foreground mb-4">서버 연결을 확인하고 다시 시도해주세요</p>
          <Button onClick={loadGroups}>다시 시도</Button>
        </div>
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-background">
      {/* Header - Compact */}
      <div className="border-b border-border bg-card flex-shrink-0">
        <div className="container py-3">
          {/* Top Row: Title + Status */}
          <div className="flex items-center justify-between gap-3 mb-2">
            <div>
              <h1 className="text-2xl font-bold">관리자</h1>
              <p className="text-xs text-muted-foreground">
                {user?.first_name || 'Admin'} (@{user?.username})
              </p>
            </div>
            <div className="flex items-center gap-2 flex-wrap justify-end">
              {crawlerUnreachable ? (
                <Badge variant="outline" className="border-orange-500 text-orange-600 text-xs py-0.5">
                  <Zap className="h-2.5 w-2.5 mr-1" />
                  크롤러 오류
                </Badge>
              ) : liveCrawlerStatus && (
                <Badge
                  variant="outline"
                  className={`text-xs py-0.5 ${liveCrawlerStatus.running && liveCrawlerStatus.connected
                    ? 'border-green-500 text-green-600'
                    : 'border-red-500 text-red-600'
                  }`}
                >
                  <Circle className={`h-1.5 w-1.5 mr-1 ${liveCrawlerStatus.running && liveCrawlerStatus.connected ? 'fill-green-500' : 'fill-red-500'}`} />
                  <span className="hidden sm:inline">
                    {liveCrawlerStatus.running && liveCrawlerStatus.connected ? '크롤러 활성' : '비활성'}
                  </span>
                  <span className="sm:hidden">활성</span>
                </Badge>
              )}
              {selectedGroup && (
                <Badge
                  variant="outline"
                  className={`text-xs py-0.5 ${realtimeConnected
                    ? 'border-green-500 text-green-600'
                    : 'border-yellow-500 text-yellow-600'
                  }`}
                >
                  <Circle className={`h-1.5 w-1.5 mr-1 ${realtimeConnected ? 'fill-green-500' : 'fill-yellow-500'}`} />
                  <span className="hidden sm:inline">{realtimeConnected ? '실시간' : '폴링'}</span>
                </Badge>
              )}
            </div>
          </div>

          {/* Button Row - Compact */}
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setLocation('/feed')}
              className="h-7 px-2 text-xs"
              title="피드"
            >
              <ArrowLeft className="h-3 w-3" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setLocation('/groups/select')}
              className="h-7 px-2 text-xs"
              title="그룹 추가"
            >
              <Plus className="h-3 w-3" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleRestartCrawler}
              className="h-7 px-2 text-xs"
              title="크롤러 재시작"
            >
              <RefreshCw className="h-3 w-3" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setLocation('/admin/crawler')}
              className="h-7 px-2 text-xs hidden md:inline-flex"
              title="크롤러 관리"
            >
              <BarChart3 className="h-3 w-3" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setLocation('/admin/users')}
              className="h-7 px-2 text-xs hidden lg:inline-flex"
              title="사용자 관리"
            >
              <UserCog className="h-3 w-3" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleLogout}
              className="h-7 px-2 text-xs"
              title="로그아웃"
            >
              <LogOut className="h-3 w-3" />
            </Button>
          </div>
        </div>
      </div>

      {/* Main Content: Split Screen */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar: Groups List - Compact */}
        <div className="w-full sm:w-72 border-r border-border bg-sidebar flex-shrink-0 flex flex-col overflow-hidden">
          <div className="p-2 border-b border-sidebar-border">
            <h2 className="font-bold text-sm">그룹 ({groups.length})</h2>
            <input
              type="text"
              placeholder="검색..."
              value={groupSearch}
              onChange={(e) => setGroupSearch(e.target.value)}
              className="mt-1 w-full px-2 py-1 text-xs rounded border border-border bg-background"
            />
          </div>

          <ScrollArea className="flex-1">
            <div className="p-1">
              {groups.filter((g) => !groupSearch || g.title.toLowerCase().includes(groupSearch.toLowerCase())).map((group) => {
                const crawlerStatus = getCrawlerStatus(group);

                return (
                  <button
                    key={group.id}
                    onClick={() => handleGroupSelect(group)}
                    className={`w-full text-left p-2 rounded mb-1 transition-all text-xs ${
                      selectedGroup?.id === group.id
                        ? 'border border-primary bg-accent'
                        : 'border border-transparent hover:bg-accent/50'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-0.5">
                      <div className="font-semibold truncate flex-1 text-xs">{group.title}</div>
                      <div className="flex items-center gap-1 flex-shrink-0 ml-1">
                        {crawlerStatus === 'initializing' ? (
                          <Loader2 className="h-2.5 w-2.5 animate-spin text-primary" />
                        ) : (
                          <Circle
                            className={`h-1.5 w-1.5 ${
                              crawlerStatus === 'active'
                                ? 'fill-green-500 text-green-500'
                                : crawlerStatus === 'error'
                                ? 'fill-yellow-500 text-yellow-500'
                                : 'fill-gray-400 text-gray-400'
                            }`}
                          />
                        )}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleTriggerCrawl(group.id);
                          }}
                          title="역사 크롤링"
                          className="text-primary hover:text-primary/80 p-0.5"
                        >
                          <Download className="h-2.5 w-2.5" />
                        </button>
                      </div>
                    </div>

                    {crawlerStatus === 'initializing' && (() => {
                      const info = getCrawlerProgressInfo(group);
                      if (!info) return null;
                      const pct = info.total > 0 ? Math.min(100, Math.round((info.progress / info.total) * 100)) : 0;
                      return (
                        <div className="mb-0.5">
                          <div className="w-full bg-muted rounded h-0.5 overflow-hidden">
                            <div
                              className="bg-primary h-0.5 transition-all duration-500"
                              style={{ width: `${info.total > 0 ? pct : 10}%` }}
                            />
                          </div>
                          <p className="text-[9px] text-muted-foreground mt-0.5">
                            {info.total > 0 ? `${pct}%` : '준비 중...'}
                          </p>
                        </div>
                      );
                    })()}

                    <div className="flex items-center gap-1 text-[9px] text-muted-foreground flex-wrap">
                      {group.member_count && (
                        <span>👥 {group.member_count.toLocaleString()}</span>
                      )}
                      {group.username && (
                        <a
                          href={group.invite_link || `https://t.me/${group.username}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="text-primary hover:underline"
                          title="텔레그램 링크"
                        >
                          @{group.username}
                        </a>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </ScrollArea>

        </div>

        {/* Right: Message Viewer */}
        <div className="flex-1 flex flex-col bg-background overflow-hidden">
          {selectedGroup ? (
            <>
              {/* Chat Header - Compact */}
              <div className="p-2 border-b border-border bg-card flex-shrink-0">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <h2 className="font-bold text-sm truncate">{selectedGroup.title}</h2>
                    {selectedGroup.username && (
                      <p className="text-xs text-muted-foreground truncate">@{selectedGroup.username}</p>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => loadMessages(selectedGroup.id, 1)}
                    disabled={isLoadingMessages}
                    className="h-7 px-2"
                    title="새로고침"
                  >
                    <RefreshCw className={`h-3 w-3 ${isLoadingMessages ? 'animate-spin' : ''}`} />
                  </Button>
                </div>
                <div className="mt-1">
                  <TopicFilter
                    groupId={selectedGroup.id}
                    selectedTopicId={selectedTopicId}
                    onTopicSelect={(topicId: number | null) => {
                      setSelectedTopicId(topicId);
                      loadMessages(selectedGroup.id, 1);
                    }}
                  />
                </div>
              </div>

              {/* Messages Area - Compact */}
              <ScrollArea className="flex-1 px-2 py-1" ref={scrollAreaRef}>
                {isLoadingMessages && page === 1 ? (
                  <div className="flex items-center justify-center h-full">
                    <Loader2 className="h-6 w-6 animate-spin text-primary" />
                  </div>
                ) : messages.length === 0 ? (
                  <div className="flex items-center justify-center h-full">
                    <div className="text-center">
                      <AlertCircle className="h-10 w-10 mx-auto mb-2 text-muted-foreground" />
                      <p className="text-sm font-medium">메시지 없음</p>
                      <p className="text-xs text-muted-foreground">
                        지난 30일간 메시지가 없습니다
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-0.5">
                    {/* Load More Button */}
                    {hasMore && (
                      <div className="text-center py-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleLoadMore}
                          disabled={isLoadingMessages}
                          className="h-6 text-xs border border-border"
                        >
                          {isLoadingMessages ? (
                            <>
                              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                              로딩
                            </>
                          ) : (
                            '이전 메시지'
                          )}
                        </Button>
                      </div>
                    )}

                    {/* Messages grouped by date */}
                    {Object.entries(groupedMessages).map(([dateKey, msgs]) => (
                      <div key={dateKey}>
                        {/* Date Divider */}
                        <div className="flex items-center justify-center py-2">
                          <div className="px-2 py-0.5 bg-muted rounded text-xs text-muted-foreground font-medium">
                            {formatDate(msgs[0].sent_at)}
                          </div>
                        </div>

                        {/* Messages */}
                        <div className="border border-border rounded divide-y divide-border">
                          {msgs.map((message) => (
                            <MessageBubble
                              key={message.id}
                              message={message}
                              onReplyClick={(replyId) => {
                                // Scroll to replied message
                                const element = document.querySelector(`[data-message-id="${replyId}"]`);
                                element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                              }}
                            />
                          ))}
                        </div>
                      </div>
                    ))}

                    {/* Scroll anchor */}
                    <div ref={messagesEndRef} />
                  </div>
                )}
              </ScrollArea>
            </>
          ) : (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <Users className="h-12 w-12 mx-auto mb-2 text-muted-foreground" />
                <p className="text-sm font-medium">그룹 선택</p>
                <p className="text-xs text-muted-foreground">
                  왼쪽에서 그룹을 선택하세요
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  return (
    <ProtectedRoute adminOnly>
      <AdminDashboardContent />
    </ProtectedRoute>
  );
}
