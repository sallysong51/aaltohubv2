/**
 * Admin Dashboard - Telegram UI Clone
 * Design Philosophy: Telegram-Native Brutalism
 * - Split-screen layout (groups list + message viewer)
 * - Telegram-style message bubbles
 * - Realtime updates via SSE (Server-Sent Events)
 * - Telegram account tabs for group filtering
 */
import { useState, useEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { toast } from 'sonner';
import {
  Loader2, Users, AlertCircle, LogOut, Circle, Plus,
  UserCog, BarChart3, Download, LinkIcon, Settings2, RefreshCw, Brain, Activity,
  ChevronDown, Check,
} from 'lucide-react';
import {
  adminApi,
  telegramApi,
  TelegramConnection,
  RegisteredGroup,
  Message,
  getApiErrorMessage,
  LiveCrawlerStatus,
  BackendHealth,
} from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import { useBackendConnectivity } from '@/contexts/BackendConnectivityContext';
import ProtectedRoute from '@/components/ProtectedRoute';
import { useLocation } from 'wouter';
import { useTheme } from 'next-themes';
import { useSSE } from '@/hooks/useSSE';
import GroupManagementTable from '@/components/admin/GroupManagementTable';
import AdminMessageViewer from '@/components/admin/AdminMessageViewer';
import CrawlerStatusBadge from '@/components/admin/CrawlerStatusBadge';
import ConnectionTabs from '@/components/admin/ConnectionTabs';
import GapFillMonitor from '@/components/admin/GapFillMonitor';
import AnalysisTab from '@/components/admin/AnalysisTab';
import PipelineVisibilityDashboard from '@/components/admin/PipelineVisibilityDashboard';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu';

function AdminDashboardContent() {
  const [, setLocation] = useLocation();
  const { user, logout } = useAuth();
  const { isBackendConnected } = useBackendConnectivity();

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
  const [liveCrawlerStatus, setLiveCrawlerStatus] = useState<LiveCrawlerStatus | null>(null);
  const [crawlerUnreachable, setCrawlerUnreachable] = useState(false);
  const [lastCrawlerContact, setLastCrawlerContact] = useState<number | null>(null);
  const [crawlerConsecutiveFailures, setCrawlerConsecutiveFailures] = useState(0);
  const [health, setHealth] = useState<BackendHealth | null>(null);
  // realtimeConnected comes from useSSE hook below
  const [groupSearch, setGroupSearch] = useState('');
  const [viewMode, setViewMode] = useState<'messages' | 'groups' | 'gap-fill' | 'analysis' | 'pipeline'>('messages');

  // Telegram account tabs
  const [connections, setConnections] = useState<TelegramConnection[]>([]);
  const [activeConnectionTab, setActiveConnectionTab] = useState<string | null>(null); // null = "전체"

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  // Load health (for environment detection)
  const loadHealth = async () => {
    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL || ''}/health`);
      if (res.ok) {
        const data = await res.json();
        setHealth(data);
      }
    } catch (err) {
      console.debug('Health check failed:', err);
    }
  };

  // Load groups + connections on mount
  useEffect(() => {
    loadGroups();
    loadLiveCrawlerStatus();
    loadConnections();
    loadHealth();
  }, []);

  const loadConnections = async () => {
    try {
      const res = await telegramApi.getConnections();
      setConnections(res.data);
      // Auto-setup admin access to all groups
      if (res.data.length > 0) {
        try {
          await adminApi.ensureAdminMembership(); // Create missing user_groups rows
          await adminApi.backfillConnectionIds();  // Set connection_id for NULL rows
        } catch {
          // Non-critical: setup is best-effort
        }
      }
    } catch {
      // Non-critical: tabs won't show
    }
  };

  // Determine if any group is actively crawling
  const hasActiveCrawling = Array.from(crawlerStatusMap.values()).some(
    s => s.status === 'initializing'
  );

  // Poll crawler statuses: 5s during active crawling, 30s otherwise.
  // Skip polling entirely when backend is unreachable to avoid wasted requests.
  useEffect(() => {
    if (!isBackendConnected) return; // Backend down — don't poll

    const intervalMs = hasActiveCrawling ? 5000 : 30000;
    loadCrawlerStatuses();
    loadLiveCrawlerStatus();
    const interval = setInterval(() => {
      loadCrawlerStatuses();
      loadLiveCrawlerStatus();
    }, intervalMs);
    return () => clearInterval(interval);
  }, [hasActiveCrawling, isBackendConnected]);

  // SSE subscription with exponential backoff reconnection
  // Subscribe to ALL groups to maintain connection even during group switching.
  // Callbacks filter by selectedGroup for display purposes.
  const sseGroupIds = groups.map(g => String(g.id));

  const { isConnected: realtimeConnected } = useSSE({
    groupIds: sseGroupIds,
    onInsert: (newMessage: Message) => {
      if (!newMessage) return;
      if (selectedGroup && String(newMessage.group_id) !== String(selectedGroup.id)) return;
      if (selectedTopicId !== null && newMessage.topic_id !== selectedTopicId) return;

      const groupId = selectedGroup ? String(selectedGroup.id) : '';
      if (newMessage.content && newMessage.content.endsWith('...') && newMessage.content.length >= 200) {
        adminApi.getGroupMessages(groupId, 1, 50, 365, selectedTopicId).then((res) => {
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
    },
    onUpdate: (updated: Message) => {
      if (!updated) return;
      setMessages((prev) =>
        updated.is_deleted
          ? prev.filter((m) => !(m.telegram_message_id === updated.telegram_message_id && String(m.group_id) === String(updated.group_id)))
          : prev.map((m) =>
              m.telegram_message_id === updated.telegram_message_id ? { ...m, ...updated } : m
            )
      );
    },
    onDelete: (deleted) => {
      if (!deleted) return;
      setMessages((prev) =>
        prev.filter((m) => !(m.telegram_message_id === deleted.telegram_message_id && String(m.group_id) === String(deleted.group_id)))
      );
    },
    onOverflow: () => {
      if (selectedGroup) {
        loadMessages(selectedGroup.id, 1);
      }
    },
  });

  const loadLiveCrawlerStatus = async () => {
    try {
      const res = await adminApi.getLiveCrawlerStatus();
      setLiveCrawlerStatus(res.data);
      setLastCrawlerContact(Date.now());
      setCrawlerConsecutiveFailures(0);
      setCrawlerUnreachable(false);
    } catch (err: any) {
      console.error('크롤러 상태 로드 실패:', err);
      setLiveCrawlerStatus(null);
      setCrawlerConsecutiveFailures(prev => prev + 1);

      // Only show error if persistent (>3 failures, >2 minutes)
      const timeSinceLastContact = lastCrawlerContact
        ? (Date.now() - lastCrawlerContact) / 1000
        : Infinity;

      if (err?.response?.status === 503) {
        setCrawlerUnreachable(true);

        if (crawlerConsecutiveFailures >= 3 && timeSinceLastContact > 120) {
          toast.error(
            health?.environment === "production"
              ? "프로덕션 크롤러 연결 실패 (시스템 관리자에게 문의)"
              : "크롤러 연결 실패 (프로세스가 실행 중인지 확인하세요)"
          );
        }
      }
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

  // FIX #2: Use days=365 so crawled historical messages appear
  const loadMessages = async (groupId: string, pageNum: number = 1) => {
    setIsLoadingMessages(true);
    try {
      const response = await adminApi.getGroupMessages(groupId, pageNum, 100, 365, selectedTopicId);

      if (pageNum === 1) {
        setMessages(response.data.messages);
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
    setMessages([]);
    setPage(1);
    setSelectedTopicId(null);
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

  // FIX #3: Filter groups by selected Telegram connection tab
  const filteredGroups = groups
    .filter((g) => {
      const matchesSearch = !groupSearch || g.title.toLowerCase().includes(groupSearch.toLowerCase());
      let matchesTab = true;
      if (activeConnectionTab === '__unlinked__') {
        matchesTab = !g.connection_id;
      } else if (activeConnectionTab) {
        matchesTab = g.connection_id === activeConnectionTab;
      }
      return matchesSearch && matchesTab;
    })
    .sort((a, b) => {
      const countA = a.message_count_total || 0;
      const countB = b.message_count_total || 0;
      return countB - countA; // 내림차순 (많은 순)
    });

  // Count groups per connection for tab badges
  const groupCountByConnection = (connId: string) =>
    groups.filter(g => g.connection_id === connId).length;
  const unlinkedGroupCount = groups.filter(g => !g.connection_id).length;

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
        <div className="text-center">
          <Users className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
          <h2 className="text-xl font-bold mb-2">등록된 그룹이 없습니다</h2>
          <p className="text-muted-foreground mb-4">텔레그램 그룹을 추가하세요</p>
          <Button onClick={() => setLocation('/groups/select')}>
            <Plus className="h-4 w-4 mr-1.5" />
            그룹 추가하기
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-background">
      {/* Header */}
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
              {/* Environment badge */}
              {health && (
                <Badge variant={health.environment === "production" ? "default" : "secondary"} className="text-xs py-0.5">
                  {health.environment === "production" ? "🟢 프로덕션" : "🔵 로컬 개발"}
                </Badge>
              )}

              {/* Crawler status badge */}
              <CrawlerStatusBadge
                liveCrawlerStatus={liveCrawlerStatus}
                lastCrawlerContact={lastCrawlerContact}
                health={health}
              />

              {/* Helper message for development environment */}
              {health?.environment === "development" && !liveCrawlerStatus && lastCrawlerContact && (Date.now() - lastCrawlerContact) / 1000 < 30 && (
                <span className="text-xs text-blue-600">
                  💡 코드 변경 시 크롤러가 자동으로 재시작됩니다
                </span>
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
                  {realtimeConnected ? '실시간' : '폴링'}
                </Badge>
              )}
            </div>
          </div>

          {/* Admin Toolbar */}
          <div className="flex items-center gap-1 flex-wrap">
            {/* 그룹 Dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 px-3 text-xs"
                >
                  <Settings2 className="h-3.5 w-3.5 mr-1.5" />
                  그룹
                  <ChevronDown className="h-3.5 w-3.5 ml-1" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem onClick={() => setLocation('/groups/select')}>
                  <Plus className="h-4 w-4" />
                  그룹 추가
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => setViewMode(viewMode === 'groups' ? 'messages' : 'groups')}
                >
                  <Settings2 className="h-4 w-4" />
                  그룹 관리
                  {viewMode === 'groups' && (
                    <Check className="h-4 w-4 ml-auto text-primary" />
                  )}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setLocation('/admin/unmapped-groups')}>
                  <LinkIcon className="h-4 w-4" />
                  미등록 그룹
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* 크롤링 Dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 px-3 text-xs"
                >
                  <BarChart3 className="h-3.5 w-3.5 mr-1.5" />
                  크롤링
                  <ChevronDown className="h-3.5 w-3.5 ml-1" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem onClick={() => setLocation('/admin/crawler')}>
                  <BarChart3 className="h-4 w-4" />
                  크롤러 관리
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => setViewMode(viewMode === 'pipeline' ? 'messages' : 'pipeline')}
                >
                  <Activity className="h-4 w-4" />
                  파이프라인
                  {viewMode === 'pipeline' && (
                    <Check className="h-4 w-4 ml-auto text-primary" />
                  )}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => setViewMode(viewMode === 'gap-fill' ? 'messages' : 'gap-fill')}
                >
                  <RefreshCw className="h-4 w-4" />
                  메시지 복구
                  {viewMode === 'gap-fill' && (
                    <Check className="h-4 w-4 ml-auto text-primary" />
                  )}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setLocation('/admin/users')}>
                  <UserCog className="h-4 w-4" />
                  관리자 권한
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* 정보가공 Dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 px-3 text-xs"
                >
                  <Brain className="h-3.5 w-3.5 mr-1.5" />
                  정보가공
                  <ChevronDown className="h-3.5 w-3.5 ml-1" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem
                  onClick={() => setViewMode(viewMode === 'analysis' ? 'messages' : 'analysis')}
                >
                  <Brain className="h-4 w-4" />
                  분석
                  {viewMode === 'analysis' && (
                    <Check className="h-4 w-4 ml-auto text-primary" />
                  )}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Logout Button */}
            <Button
              variant="ghost"
              size="sm"
              onClick={handleLogout}
              className="h-8 px-3 text-xs ml-auto"
            >
              <LogOut className="h-3.5 w-3.5 mr-1.5" />
              로그아웃
            </Button>
          </div>
        </div>
      </div>

      {/* Main Content */}
      {viewMode === 'pipeline' ? (
        <PipelineVisibilityDashboard health={health} />
      ) : viewMode === 'analysis' ? (
        <AnalysisTab groups={groups} />
      ) : viewMode === 'gap-fill' ? (
        <GapFillMonitor />
      ) : viewMode === 'groups' ? (
        <GroupManagementTable
          groups={groups}
          selectedGroup={selectedGroup}
          setSelectedGroup={setSelectedGroup}
          setGroups={setGroups}
          getCrawlerStatus={getCrawlerStatus}
          onTriggerCrawl={handleTriggerCrawl}
        />
      ) : (
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar: Groups List */}
        <div className="w-full sm:w-80 border-r border-border bg-sidebar flex-shrink-0 flex flex-col overflow-hidden">
          <ConnectionTabs
            connections={connections}
            activeConnectionTab={activeConnectionTab}
            setActiveConnectionTab={setActiveConnectionTab}
            totalGroupCount={groups.length}
            groupCountByConnection={groupCountByConnection}
            unlinkedGroupCount={unlinkedGroupCount}
          />

          <div className="p-2 border-b border-sidebar-border flex-shrink-0">
            <h2 className="font-bold text-sm">그룹 ({filteredGroups.length})</h2>
            <input
              type="text"
              placeholder="검색..."
              value={groupSearch}
              onChange={(e) => setGroupSearch(e.target.value)}
              className="mt-1 w-full px-2 py-1 text-xs rounded border border-border bg-background"
            />
          </div>

          {/* FIX #1: min-h-0 enables proper flex-based scrolling */}
          <ScrollArea className="flex-1 min-h-0">
            <div className="p-1">
              {filteredGroups.map((group) => {
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
                        <span
                          role="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleTriggerCrawl(group.id);
                          }}
                          title="역사 크롤링"
                          className="text-primary hover:text-primary/80 p-0.5 cursor-pointer"
                        >
                          <Download className="h-2.5 w-2.5" />
                        </span>
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
                        <span>{group.member_count.toLocaleString()}명</span>
                      )}
                      {group.message_count_total != null && (
                        <span>{(group.message_count_total || 0).toLocaleString()}건</span>
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
              {filteredGroups.length === 0 && (
                <div className="text-center py-8 text-xs text-muted-foreground">
                  {groupSearch ? '검색 결과가 없습니다' : '이 계정에 연결된 그룹이 없습니다'}
                </div>
              )}
            </div>
          </ScrollArea>
        </div>

        {/* Right: Message Viewer */}
        <AdminMessageViewer
          selectedGroup={selectedGroup}
          messages={messages}
          isLoadingMessages={isLoadingMessages}
          page={page}
          hasMore={hasMore}
          groupedMessages={groupedMessages}
          selectedTopicId={selectedTopicId}
          setSelectedTopicId={setSelectedTopicId}
          onRefresh={() => selectedGroup && loadMessages(selectedGroup.id, 1)}
          onLoadMore={handleLoadMore}
          messagesEndRef={messagesEndRef}
          scrollAreaRef={scrollAreaRef}
        />
      </div>
      )}
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
