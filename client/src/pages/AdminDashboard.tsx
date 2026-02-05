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
import { Loader2, Users, AlertCircle, RefreshCw, LogOut, Circle, Hash } from 'lucide-react';
import { adminApi, RegisteredGroup, Message } from '@/lib/api';
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
  const [groupMessages, setGroupMessages] = useState<Map<string, Message>>(new Map());
  const [selectedGroup, setSelectedGroup] = useState<RegisteredGroup | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoadingGroups, setIsLoadingGroups] = useState(true);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [selectedTopicId, setSelectedTopicId] = useState<number | null>(null);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  // Load groups on mount
  useEffect(() => {
    loadGroups();
  }, []);

  // Subscribe to realtime messages when group is selected
  useEffect(() => {
    if (!selectedGroup) return;

    const channel = supabase
      .channel('messages')
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'messages',
          filter: `group_id=eq.${selectedGroup.id}`,
        },
        (payload) => {
          const newMessage = payload.new as Message;
          setMessages((prev) => [...prev, newMessage]);
          
          // Auto-scroll to bottom
          setTimeout(() => {
            messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
          }, 100);
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [selectedGroup]);

  const loadGroups = async () => {
    setIsLoadingGroups(true);
    try {
      const response = await adminApi.getAllGroups();
      setGroups(response.data);
      
      // Load latest message for each group
      const messagesMap = new Map<string, Message>();
      for (const group of response.data) {
        try {
          const msgResponse = await adminApi.getGroupMessages(group.id, 1, 1, 30);
          if (msgResponse.data.messages.length > 0) {
            messagesMap.set(group.id, msgResponse.data.messages[0]);
          }
        } catch (error) {
          // Ignore errors for individual groups
        }
      }
      setGroupMessages(messagesMap);
      
      // Auto-select first group
      if (response.data.length > 0 && !selectedGroup) {
        setSelectedGroup(response.data[0]);
      }
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '그룹 목록을 불러오는데 실패했습니다');
    } finally {
      setIsLoadingGroups(false);
    }
  };

  const loadMessages = async (groupId: string, pageNum: number = 1) => {
    setIsLoadingMessages(true);
    try {
      const response = await adminApi.getGroupMessages(groupId, pageNum, 50, 30);
      
      if (pageNum === 1) {
        setMessages(response.data.messages);
        // Scroll to bottom for initial load
        setTimeout(() => {
          messagesEndRef.current?.scrollIntoView({ behavior: 'auto' });
        }, 100);
      } else {
        setMessages((prev) => [...response.data.messages, ...prev]);
      }
      
      setHasMore(response.data.has_more);
      setPage(pageNum);
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '메시지를 불러오는데 실패했습니다');
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
    // TODO: Get actual crawler status from backend API
    // For now, assume all groups are active
    return 'active';
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
      <div className="border-b-4 border-border bg-card flex-shrink-0">
        <div className="container py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold">관리자 대시보드</h1>
              <p className="text-sm text-muted-foreground">
                {user?.first_name || 'Admin'} (@{user?.username})
              </p>
            </div>
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

      {/* Main Content: Split Screen */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar: Groups List */}
        <div className="w-80 border-r-4 border-border bg-sidebar flex-shrink-0 flex flex-col">
          <div className="p-4 border-b-2 border-sidebar-border">
            <h2 className="font-bold text-lg">등록된 그룹</h2>
            <p className="text-xs text-muted-foreground">{groups.length}개 그룹</p>
          </div>
          
          <ScrollArea className="flex-1">
            <div className="p-2">
              {groups.map((group) => {
                const lastMessage = groupMessages.get(group.id);
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
                    {group.username && (
                      <div className="text-xs text-muted-foreground truncate">
                        @{group.username}
                      </div>
                    )}
                    {lastMessage && (
                      <div className="text-xs text-muted-foreground truncate mt-1">
                        {lastMessage.sender_name}: {lastMessage.content || '[미디어]'}
                      </div>
                    )}
                    <div className="flex items-center justify-between mt-1">
                      {group.member_count && (
                        <Badge variant="outline" className="text-xs">
                          <Users className="mr-1 h-3 w-3" />
                          {group.member_count.toLocaleString()}
                        </Badge>
                      )}
                      {lastMessage && (
                        <span className="text-xs text-muted-foreground timestamp">
                          {formatTimestamp(lastMessage.sent_at)}
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </ScrollArea>

          {/* Failed Invites Section */}
          <div className="p-4 border-t-2 border-sidebar-border">
            <Button
              variant="outline"
              className="w-full border-2 border-border"
              size="sm"
              onClick={() => toast.info('초대 실패 목록 기능 준비 중')}
            >
              <AlertCircle className="mr-2 h-4 w-4" />
              초대 실패 목록
            </Button>
          </div>
        </div>

        {/* Right: Message Viewer */}
        <div className="flex-1 flex flex-col bg-background">
          {selectedGroup ? (
            <>
              {/* Chat Header */}
              <div className="p-4 border-b-2 border-border bg-card flex-shrink-0">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h2 className="font-bold text-xl">{selectedGroup.title}</h2>
                    {selectedGroup.username && (
                      <p className="text-sm text-muted-foreground">@{selectedGroup.username}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setLocation('/admin/crawler')}
                      className="border-2 border-border"
                    >
                      <Hash className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => loadMessages(selectedGroup.id, 1)}
                      disabled={isLoadingMessages}
                      className="border-2 border-border"
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
