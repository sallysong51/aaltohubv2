/**
 * Admin Dashboard - Telegram UI Clone
 * Design Philosophy: Telegram-Native Brutalism
 * - Split-screen layout (groups list + message viewer)
 * - Telegram-style message bubbles
 * - Realtime updates via Supabase
 */
import { useState, useEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { toast } from 'sonner';
import { Loader2, Users, AlertCircle, RefreshCw, LogOut, Circle, Hash, Plus, ChevronRight, ExternalLink, UserCog, BarChart3, ArrowLeft, Zap, Download } from 'lucide-react';
import { adminApi, RegisteredGroup, Message, getApiErrorMessage } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import ProtectedRoute from '@/components/ProtectedRoute';
import supabase from '@/lib/supabase';
import { useLocation } from 'wouter';
import MessageBubble from '@/components/MessageBubble';
import TopicFilter from '@/components/TopicFilter';

function AdminDashboardContent() {
  const [, setLocation] = useLocation();
  const { user, logout } = useAuth();

  const [groups, setGroups] = useState<RegisteredGroup[]>([]);
  const [selectedGroup, setSelectedGroup] = useState<RegisteredGroup | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoadingGroups, setIsLoadingGroups] = useState(true);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [selectedTopicId, setSelectedTopicId] = useState<number | null>(null);
  const [crawlerStatusMap, setCrawlerStatusMap] = useState<Map<string, string>>(new Map());
  const [liveCrawlerStatus, setLiveCrawlerStatus] = useState<{
    running: boolean; connected: boolean; groups_count: number;
    messages_received: number; historical_crawl_running: boolean;
    crawled_groups: number; uptime_seconds: number;
  } | null>(null);
  const [realtimeConnected, setRealtimeConnected] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  // Load groups on mount
  useEffect(() => {
    loadGroups();
    loadLiveCrawlerStatus();
    const interval = setInterval(loadLiveCrawlerStatus, 30_000);
    return () => clearInterval(interval);
  }, []);

  // Subscribe to realtime messages when group is selected
  useEffect(() => {
    if (!selectedGroup) return;

    const channel = supabase
      .channel('messages')
      .on('broadcast', { event: 'insert' }, ({ payload: newMessage }: { payload: Message }) => {
        if (!newMessage || String(newMessage.group_id) !== String(selectedGroup.id)) return;
        // Filter by selected topic if active
        if (selectedTopicId !== null && newMessage.topic_id !== selectedTopicId) return;
        setMessages((prev) => {
          // Deduplicate by telegram_message_id + group_id
          if (prev.some(m => m.telegram_message_id === newMessage.telegram_message_id && String(m.group_id) === String(newMessage.group_id))) return prev;
          return [...prev, newMessage];
        });

        // Auto-scroll to bottom
        requestAnimationFrame(() => {
          messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        });
      })
      .on('broadcast', { event: 'update' }, ({ payload: updated }: { payload: Message }) => {
        if (!updated || String(updated.group_id) !== String(selectedGroup.id)) return;
        setMessages((prev) =>
          updated.is_deleted
            ? prev.filter((m) => !(m.telegram_message_id === updated.telegram_message_id && String(m.group_id) === String(updated.group_id)))
            : prev.map((m) =>
                m.telegram_message_id === updated.telegram_message_id ? { ...m, ...updated } : m
              )
        );
      })
      .subscribe((status) => {
        setRealtimeConnected(status === 'SUBSCRIBED');
      });

    return () => {
      supabase.removeChannel(channel);
      setRealtimeConnected(false);
    };
  }, [selectedGroup, selectedTopicId]);

  const loadLiveCrawlerStatus = async () => {
    try {
      const res = await adminApi.getLiveCrawlerStatus();
      setLiveCrawlerStatus(res.data);
    } catch {
      // Non-critical
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

  const loadGroups = async () => {
    setIsLoadingGroups(true);
    try {
      const response = await adminApi.getAllGroups();
      setGroups(response.data);

      // N+1 latest-message fetch removed — messages load when a group is selected.
      // The sidebar shows group metadata without message previews.

      // Load crawler statuses
      try {
        const statusResponse = await adminApi.getCrawlerStatus();
        const statusMap = new Map<string, string>();
        (statusResponse.data || []).forEach((s: { group_id: string; status?: string }) => {
          statusMap.set(String(s.group_id), s.status || 'inactive');
        });
        setCrawlerStatusMap(statusMap);
      } catch {
        // Non-critical: leave map empty
      }

      // Auto-select first group
      if (response.data.length > 0 && !selectedGroup) {
        setSelectedGroup(response.data[0]);
      }
    } catch (error) {
      toast.error(getApiErrorMessage(error, '그룹 목록을 불러오는데 실패했습니다'));
    } finally {
      setIsLoadingGroups(false);
    }
  };

  const loadMessages = async (groupId: string, pageNum: number = 1) => {
    setIsLoadingMessages(true);
    try {
      const response = await adminApi.getGroupMessages(groupId, pageNum, 50, 30, selectedTopicId);
      
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

  const getCrawlerStatus = (group: RegisteredGroup): 'active' | 'inactive' | 'error' => {
    const status = crawlerStatusMap.get(String(group.telegram_id || group.id));
    if (status === 'active') return 'active';
    if (status === 'error') return 'error';
    return 'inactive';
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

  if (isLoadingGroups) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-background">
      {/* Header */}
      <div className="border-b border-border bg-card flex-shrink-0">
        <div className="container py-4">
          {/* Breadcrumb */}
          <div className="flex items-center gap-2 mb-3 text-sm text-muted-foreground">
            <span>Admin</span>
            <ChevronRight className="h-4 w-4" />
            <span className="text-foreground font-medium">Dashboard</span>
          </div>

          {/* Main Header */}
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-4xl font-bold">관리자 대시보드</h1>
              <div className="flex items-center gap-2 mt-1">
                <p className="text-sm text-muted-foreground">
                  {user?.first_name || 'Admin'} (@{user?.username})
                </p>
                {liveCrawlerStatus && (
                  <Badge
                    variant="outline"
                    className={liveCrawlerStatus.running && liveCrawlerStatus.connected
                      ? 'border-green-500 text-green-600'
                      : 'border-red-500 text-red-600'
                    }
                  >
                    <Zap className="h-3 w-3 mr-1" />
                    {liveCrawlerStatus.running && liveCrawlerStatus.connected
                      ? `크롤러 활성 (${liveCrawlerStatus.messages_received}건)`
                      : '크롤러 비활성'
                    }
                    {liveCrawlerStatus.historical_crawl_running && ' | 역사 수집 중...'}
                  </Badge>
                )}
                {selectedGroup && (
                  <Badge
                    variant="outline"
                    className={realtimeConnected
                      ? 'border-green-500 text-green-600'
                      : 'border-yellow-500 text-yellow-600'
                    }
                  >
                    <Circle className={`h-2 w-2 mr-1 ${realtimeConnected ? 'fill-green-500' : 'fill-yellow-500'}`} />
                    {realtimeConnected ? '실시간 연결됨' : '연결 중...'}
                  </Badge>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                onClick={() => setLocation('/feed')}
                className="border-2 border-border"
              >
                <ArrowLeft className="mr-2 h-4 w-4" />
                피드로 돌아가기
              </Button>
              <Button
                variant="outline"
                onClick={() => setLocation('/groups/select')}
                className="border-2 border-border"
              >
                <Plus className="mr-2 h-4 w-4" />
                그룹 추가
              </Button>
              <Button
                variant="outline"
                onClick={handleRestartCrawler}
                className="border-2 border-border"
                title="라이브 크롤러 재시작"
              >
                <RefreshCw className="mr-2 h-4 w-4" />
                크롤러 재시작
              </Button>
              <Button
                variant="outline"
                onClick={() => setLocation('/admin/crawler')}
                className="border-2 border-border"
              >
                <BarChart3 className="mr-2 h-4 w-4" />
                크롤러 관리
              </Button>
              <Button
                variant="outline"
                onClick={() => setLocation('/admin/users')}
                className="border-2 border-border"
              >
                <UserCog className="mr-2 h-4 w-4" />
                사용자 관리
              </Button>
              <Button
                variant="outline"
                onClick={handleLogout}
                className="border-2 border-border"
              >
                <LogOut className="mr-2 h-4 w-4" />
                로그아웃
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content: Split Screen */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar: Groups List */}
        <div className="w-80 border-r border-border bg-sidebar flex-shrink-0 flex flex-col">
          <div className="p-4 border-b border-sidebar-border">
            <h2 className="font-bold text-lg">등록된 그룹</h2>
            <p className="text-xs text-muted-foreground">{groups.length}개 그룹</p>
          </div>
          
          <ScrollArea className="flex-1">
            <div className="p-2">
              {groups.map((group) => {
                const crawlerStatus = getCrawlerStatus(group);

                return (
                  <button
                    key={group.id}
                    onClick={() => handleGroupSelect(group)}
                    className={`w-full text-left p-3 rounded border-2 mb-2 transition-all ${
                      selectedGroup?.id === group.id
                        ? 'border-primary bg-accent'
                        : 'border-transparent hover:bg-accent/50'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="font-bold truncate flex-1">{group.title}</div>
                      <Circle
                        className={`h-2 w-2 flex-shrink-0 ml-2 ${
                          crawlerStatus === 'active'
                            ? 'fill-green-500 text-green-500'
                            : crawlerStatus === 'error'
                            ? 'fill-yellow-500 text-yellow-500'
                            : 'fill-red-500 text-red-500'
                        }`}
                      />
                    </div>
                    {group.invite_link && (
                      <a
                        href={group.invite_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-xs text-primary hover:underline truncate flex items-center gap-1"
                      >
                        <ExternalLink className="h-3 w-3 flex-shrink-0" />
                        {group.username ? `@${group.username}` : '텔레그램 링크'}
                      </a>
                    )}
                    <div className="flex items-center justify-between mt-1">
                      {group.member_count && (
                        <Badge variant="outline" className="text-xs">
                          <Users className="mr-1 h-3 w-3" />
                          {group.member_count.toLocaleString()}
                        </Badge>
                      )}
                      <div className="flex items-center gap-1">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleTriggerCrawl(group.id);
                          }}
                          className="text-xs text-primary hover:underline flex items-center gap-0.5"
                          title="역사 크롤링 시작"
                        >
                          <Download className="h-3 w-3" />
                        </button>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </ScrollArea>

        </div>

        {/* Right: Message Viewer */}
        <div className="flex-1 flex flex-col bg-background">
          {selectedGroup ? (
            <>
              {/* Chat Header */}
              <div className="p-4 border-b border-border bg-card flex-shrink-0">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h2 className="font-bold text-2xl">{selectedGroup.title}</h2>
                    {selectedGroup.username && (
                      <p className="text-sm text-muted-foreground">@{selectedGroup.username}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => loadMessages(selectedGroup.id, 1)}
                      disabled={isLoadingMessages}
                      className="border-2 border-border"
                      title="메시지 새로고침"
                    >
                      <RefreshCw className={`h-4 w-4 ${isLoadingMessages ? 'animate-spin' : ''}`} />
                    </Button>
                  </div>
                </div>
                <TopicFilter
                  groupId={selectedGroup.id}
                  selectedTopicId={selectedTopicId}
                  onTopicSelect={(topicId: number | null) => {
                    setSelectedTopicId(topicId);
                    loadMessages(selectedGroup.id, 1);
                  }}
                />
              </div>

              {/* Messages Area */}
              <ScrollArea className="flex-1 p-4" ref={scrollAreaRef}>
                {isLoadingMessages && page === 1 ? (
                  <div className="flex items-center justify-center h-full">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                  </div>
                ) : messages.length === 0 ? (
                  <div className="flex items-center justify-center h-full">
                    <div className="text-center">
                      <AlertCircle className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                      <p className="text-lg font-medium">메시지가 없습니다</p>
                      <p className="text-sm text-muted-foreground">
                        지난 30일간 메시지가 없습니다
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {/* Load More Button */}
                    {hasMore && (
                      <div className="text-center mb-4">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleLoadMore}
                          disabled={isLoadingMessages}
                          className="border-2 border-border"
                        >
                          {isLoadingMessages ? (
                            <>
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                              로딩 중...
                            </>
                          ) : (
                            '이전 메시지 불러오기'
                          )}
                        </Button>
                      </div>
                    )}

                    {/* Messages grouped by date */}
                    {Object.entries(groupedMessages).map(([dateKey, msgs]) => (
                      <div key={dateKey}>
                        {/* Date Divider */}
                        <div className="flex items-center justify-center my-4">
                          <div className="px-3 py-1 bg-muted rounded-full text-xs font-medium">
                            {formatDate(msgs[0].sent_at)}
                          </div>
                        </div>

                        {/* Messages */}
                        <div>
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
                <Users className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
                <p className="text-lg font-medium">그룹을 선택하세요</p>
                <p className="text-sm text-muted-foreground">
                  왼쪽에서 그룹을 선택하여 메시지를 확인하세요
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
