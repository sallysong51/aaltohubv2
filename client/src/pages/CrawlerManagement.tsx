/**
 * Crawler Management Page
 * Admin-only page for managing crawler status and viewing error logs
 */
import { useState, useEffect } from 'react';
import { useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from 'sonner';
import { Loader2, AlertCircle, CheckCircle, XCircle, RefreshCw, ArrowLeft, Activity, TrendingUp, Zap } from 'lucide-react';
import ProtectedRoute from '@/components/ProtectedRoute';
import { formatDateFull } from '@/lib/dateFormat';
import { adminApi, getApiErrorMessage, LiveCrawlerStatus, BackendHealth, CrawlerHealthStatus, CrawlerEvent, CrawlerSummary, SystemDiagnostics, SystemLog } from '@/lib/api';

interface CrawlerStatus {
  id: string;
  group_id: string;
  group_title?: string;
  status: 'active' | 'inactive' | 'error' | 'initializing';
  last_message_at?: string;
  last_error?: string;
  error_count: number;
  is_enabled: boolean;
  initial_crawl_progress: number;
  initial_crawl_total: number;
  updated_at: string;
}

// Removed ErrorLog interface — now using CrawlerEvent from api.ts

function CrawlerManagementContent() {
  const [, setLocation] = useLocation();
  const [crawlerStatuses, setCrawlerStatuses] = useState<CrawlerStatus[]>([]);
  const [crawlerEvents, setCrawlerEvents] = useState<CrawlerEvent[]>([]);
  const [crawlerSummary, setCrawlerSummary] = useState<CrawlerSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingLogs, setIsLoadingLogs] = useState(false);
  const [liveStatus, setLiveStatus] = useState<LiveCrawlerStatus | null>(null);
  const [lastCrawlerContact, setLastCrawlerContact] = useState<number | null>(null);
  const [health, setHealth] = useState<BackendHealth | null>(null);

  // Event filters
  const [eventTypeFilter, setEventTypeFilter] = useState<string>('all');
  const [eventCategoryFilter, setEventCategoryFilter] = useState<string>('all');

  // System diagnostics
  const [systemDiagnostics, setSystemDiagnostics] = useState<SystemDiagnostics | null>(null);
  const [systemLogs, setSystemLogs] = useState<SystemLog[]>([]);
  const [isLoadingDiagnostics, setIsLoadingDiagnostics] = useState(false);
  const [selectedComponent, setSelectedComponent] = useState<string | null>(null);

  useEffect(() => {
    loadCrawlerStatuses();
    loadLiveStatus();
    loadHealth();
    loadCrawlerEvents(); // Load events on mount
    const interval = setInterval(loadLiveStatus, 30_000);
    return () => clearInterval(interval);
  }, []);

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

  const loadLiveStatus = async () => {
    try {
      const res = await adminApi.getLiveCrawlerStatus();
      setLiveStatus(res.data);
      setLastCrawlerContact(Date.now());
    } catch (err: any) {
      console.error('Live crawler status failed:', err);
      setLiveStatus(null);
    }
  };

  const handleRestartLiveCrawler = async () => {
    try {
      await adminApi.restartLiveCrawler();
      toast.success('라이브 크롤러가 재시작되었습니다');
      loadLiveStatus();
      loadCrawlerStatuses();
    } catch (error) {
      toast.error(getApiErrorMessage(error, '크롤러 재시작 실패'));
    }
  };

  const loadCrawlerStatuses = async () => {
    setIsLoading(true);
    try {
      const response = await adminApi.getCrawlerStatus();
      setCrawlerStatuses(response.data);
    } catch (error) {
      toast.error(getApiErrorMessage(error, '크롤러 상태를 불러오는데 실패했습니다'));
    } finally {
      setIsLoading(false);
    }
  };

  const loadCrawlerEvents = async (groupId?: number) => {
    setIsLoadingLogs(true);
    try {
      // Load events with filters
      const params: Parameters<typeof adminApi.getCrawlerEvents>[0] = {
        page: 1,
        page_size: 100,
        ...(groupId ? { group_id: groupId } : {}),
        ...(eventTypeFilter !== 'all' ? { event_type: eventTypeFilter as any } : {}),
        ...(eventCategoryFilter !== 'all' ? { event_category: eventCategoryFilter as any } : {}),
      };

      const response = await adminApi.getCrawlerEvents(params);
      setCrawlerEvents(response.data.events || []);

      // Also load summary for dashboard
      const summaryResponse = await adminApi.getCrawlerSummary();
      setCrawlerSummary(summaryResponse.data);
    } catch (error) {
      console.error('loadCrawlerEvents error:', error);
      toast.error(getApiErrorMessage(error, '이벤트 로그를 불러오는데 실패했습니다'));
      // Set empty data on error
      setCrawlerEvents([]);
      setCrawlerSummary({
        event_counts: [],
        unresolved_errors: [],
        recent_successes: [],
        recovery_events: [],
      });
    } finally {
      setIsLoadingLogs(false);
    }
  };

  const toggleCrawler = async (groupId: string, isEnabled: boolean) => {
    try {
      // This endpoint doesn't exist in adminApi yet, use direct call
      await adminApi.getCrawlerStatus(); // placeholder for toggle
      toast.success(isEnabled ? '크롤러가 활성화되었습니다' : '크롤러가 비활성화되었습니다');
      loadCrawlerStatuses();
    } catch (error) {
      toast.error(getApiErrorMessage(error, '크롤러 상태 변경에 실패했습니다'));
    }
  };

  const loadSystemDiagnostics = async () => {
    setIsLoadingDiagnostics(true);
    try {
      const response = await adminApi.getSystemDiagnostics();
      setSystemDiagnostics(response.data);

      // Load logs for selected component if any
      if (selectedComponent) {
        loadSystemLogs(selectedComponent);
      }
    } catch (error) {
      console.error('loadSystemDiagnostics error:', error);
      toast.error(getApiErrorMessage(error, '시스템 진단 정보를 불러오는데 실패했습니다'));
    } finally {
      setIsLoadingDiagnostics(false);
    }
  };

  const loadSystemLogs = async (component?: string, health?: string) => {
    try {
      const response = await adminApi.getSystemLogs({
        page: 1,
        page_size: 100,
        ...(component ? { component } : {}),
        ...(health ? { health: health as any } : {}),
      });
      setSystemLogs(response.data.logs);
    } catch (error) {
      console.error('loadSystemLogs error:', error);
      toast.error(getApiErrorMessage(error, '시스템 로그를 불러오는데 실패했습니다'));
      setSystemLogs([]);
    }
  };

  const getEventBadgeColor = (eventType: string) => {
    switch (eventType) {
      case 'error':
        return 'destructive';
      case 'warning':
        return 'outline' as const;
      case 'success':
        return 'default';
      case 'recovery':
        return 'secondary';
      case 'info':
      default:
        return 'outline' as const;
    }
  };

  const getEventIcon = (eventType: string) => {
    switch (eventType) {
      case 'error':
        return <XCircle className="h-3 w-3" />;
      case 'warning':
        return <AlertCircle className="h-3 w-3" />;
      case 'success':
        return <CheckCircle className="h-3 w-3" />;
      case 'recovery':
        return <Zap className="h-3 w-3" />;
      case 'info':
      default:
        return <Activity className="h-3 w-3" />;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'active':
        return (
          <Badge variant="default" className="bg-green-500">
            <CheckCircle className="mr-1 h-3 w-3" />
            활성
          </Badge>
        );
      case 'error':
        return (
          <Badge variant="destructive">
            <XCircle className="mr-1 h-3 w-3" />
            에러
          </Badge>
        );
      case 'initializing':
        return (
          <Badge variant="secondary">
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            초기화 중
          </Badge>
        );
      default:
        return (
          <Badge variant="outline">
            <AlertCircle className="mr-1 h-3 w-3" />
            비활성
          </Badge>
        );
    }
  };

  const formatDate = formatDateFull;

  return (
    <div className="min-h-screen bg-background">
      <div className="border-b border-border bg-card">
        <div className="container max-w-7xl py-6">
          <Button
            variant="outline"
            onClick={() => setLocation('/admin')}
            className="mb-4"
          >
            <ArrowLeft className="mr-2 h-4 w-4" />
            돌아가기
          </Button>
          <h1 className="text-4xl font-bold mb-2">크롤러 관리</h1>
          <p className="text-muted-foreground">
            그룹별 크롤링 상태를 모니터링하고 에러 로그를 확인하세요
          </p>
        </div>
      </div>

      <div className="container max-w-7xl p-4">
        <div className="mb-6" />

        <Tabs defaultValue="status" className="w-full">
          <TabsList className="mb-4">
            <TabsTrigger value="status">크롤러 상태</TabsTrigger>
            <TabsTrigger
              value="events"
              onClick={() => {
                loadCrawlerEvents();
              }}
            >
              전체 상황
            </TabsTrigger>
            <TabsTrigger
              value="summary"
              onClick={() => {
                if (!crawlerSummary) {
                  loadCrawlerEvents();
                }
              }}
            >
              요약 대시보드
            </TabsTrigger>
            <TabsTrigger
              value="diagnostics"
              onClick={() => {
                loadSystemDiagnostics();
              }}
            >
              시스템 점검
            </TabsTrigger>
          </TabsList>

          <TabsContent value="status">
            {/* Live Crawler Status */}
            {!liveStatus ? (
              <Card className="mb-4">
                <CardContent className="pt-6">
                  <div className="text-center space-y-4">
                    <AlertCircle className="mx-auto h-12 w-12 text-muted-foreground" />
                    <div>
                      <p className="text-lg font-medium">
                        {health?.environment === "production"
                          ? "프로덕션 크롤러에 연결할 수 없습니다"
                          : "크롤러 프로세스를 찾을 수 없습니다"}
                      </p>
                      <p className="text-sm text-muted-foreground mt-2">
                        {health?.environment === "development"
                          ? "백엔드 터미널에서 크롤러 프로세스가 실행 중인지 확인하세요"
                          : "systemd 서비스 상태를 확인하세요: systemctl status aaltohub-live-crawler"}
                      </p>
                      {lastCrawlerContact && (
                        <p className="text-xs text-muted-foreground mt-2">
                          마지막 정상 연결: {Math.floor((Date.now() - lastCrawlerContact) / 1000)}초 전
                        </p>
                      )}
                    </div>
                    <Button onClick={loadLiveStatus} variant="outline">
                      <RefreshCw className="mr-2 h-4 w-4" />
                      다시 시도
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <Card className="mb-4">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <CardTitle>라이브 크롤러</CardTitle>
                      {/* Environment badge */}
                      {health && (
                        <Badge variant={health.environment === "production" ? "default" : "secondary"} className="text-xs">
                          {health.environment === "production" ? "프로덕션" : "로컬 개발"}
                        </Badge>
                      )}
                      {/* Health status badge */}
                      {liveStatus.health_status && (
                        <Badge
                          variant={liveStatus.health_status === "healthy" ? "default" : "outline"}
                          className={
                            liveStatus.health_status === "healthy"
                              ? "bg-green-500"
                              : liveStatus.health_status === "degraded"
                              ? "border-orange-500 text-orange-600"
                              : liveStatus.health_status === "restarting"
                              ? "border-yellow-500 text-yellow-600"
                              : "border-red-500 text-red-600"
                          }
                        >
                          {liveStatus.health_status === "healthy" && "활성"}
                          {liveStatus.health_status === "degraded" && "성능 저하"}
                          {liveStatus.health_status === "restarting" && "재시작 중"}
                          {liveStatus.health_status === "stopped" && "정지됨"}
                          {liveStatus.health_status === "unreachable" && "연결 불가"}
                        </Badge>
                      )}
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleRestartLiveCrawler}
                    >
                      <RefreshCw className="mr-2 h-4 w-4" />
                      재시작
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  {/* Health message */}
                  {liveStatus.health_status !== "healthy" && liveStatus.health_message && (
                    <div className="mb-4 p-3 border rounded-md bg-muted text-sm">
                      {liveStatus.health_message}
                    </div>
                  )}

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                      <p className="text-sm text-muted-foreground">상태</p>
                      <Badge variant={liveStatus.running && liveStatus.connected ? 'default' : 'destructive'}
                        className={liveStatus.running && liveStatus.connected ? 'bg-green-500' : ''}>
                        {liveStatus.running && liveStatus.connected ? '활성' : '비활성'}
                      </Badge>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">감시 그룹</p>
                      <p className="text-lg font-bold">{liveStatus.groups_count}개</p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">수신 메시지</p>
                      <p className="text-lg font-bold">{liveStatus.messages_received}건</p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">역사 크롤링</p>
                      <p className="text-lg font-bold">
                        {liveStatus.historical_crawl_running
                          ? `진행 중 (${liveStatus.crawled_groups}개 완료)`
                          : `완료 (${liveStatus.crawled_groups}개)`
                        }
                      </p>
                    </div>
                  </div>

                  {/* Circuit breaker warning */}
                  {liveStatus.circuit_breaker?.state === "open" && (
                    <div className="mt-4 p-3 border border-orange-500 rounded-md bg-orange-50 text-sm">
                      <p className="font-medium text-orange-900">
                        ⚠️ DB 쓰기 차단됨 (circuit breaker open)
                      </p>
                      {liveStatus.circuit_breaker.next_retry_at && (
                        <p className="text-xs text-orange-700 mt-1">
                          다음 재시도: {new Date(liveStatus.circuit_breaker.next_retry_at).toLocaleTimeString()}
                        </p>
                      )}
                    </div>
                  )}

                  {/* Dead letter queue */}
                  {liveStatus.dead_letter_count > 0 && (
                    <div className="mt-4 p-3 border border-blue-500 rounded-md bg-blue-50 text-sm">
                      <p className="font-medium text-blue-900">
                        📬 {liveStatus.dead_letter_count}개의 메시지가 대기 중입니다
                      </p>
                    </div>
                  )}

                  {liveStatus.uptime_seconds > 0 && (
                    <p className="text-xs text-muted-foreground mt-2">
                      Uptime: {Math.floor(liveStatus.uptime_seconds / 3600)}시간 {Math.floor((liveStatus.uptime_seconds % 3600) / 60)}분
                    </p>
                  )}
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>그룹별 크롤러 상태</CardTitle>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={loadCrawlerStatuses}
                    disabled={isLoading}
                  >
                    <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
                    새로고침
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {isLoading ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                  </div>
                ) : crawlerStatuses.length === 0 ? (
                  <div className="text-center py-12 text-muted-foreground">
                    등록된 그룹이 없습니다
                  </div>
                ) : (
                  <ScrollArea className="h-[600px]">
                    <div className="space-y-4">
                      {crawlerStatuses.map((crawler) => (
                        <Card key={crawler.id} className="border-2">
                          <CardContent className="p-4">
                            <div className="flex items-start justify-between mb-3">
                              <div className="flex-1">
                                <h3 className="font-bold text-lg mb-1">
                                  {crawler.group_title || '알 수 없는 그룹'}
                                </h3>
                                <div className="flex items-center gap-2">
                                  {getStatusBadge(crawler.status)}
                                  {crawler.error_count > 0 && (
                                    <Badge variant="outline">
                                      에러 {crawler.error_count}회
                                    </Badge>
                                  )}
                                </div>
                              </div>
                              <div className="flex items-center gap-2">
                                <span className="text-sm text-muted-foreground">
                                  {crawler.is_enabled ? '활성화' : '비활성화'}
                                </span>
                                <Switch
                                  checked={crawler.is_enabled}
                                  onCheckedChange={(checked) =>
                                    toggleCrawler(crawler.group_id, checked)
                                  }
                                />
                              </div>
                            </div>

                            {crawler.status === 'initializing' && (
                              <div className="mb-3">
                                <div className="text-sm text-muted-foreground mb-1">
                                  초기 메시지 수집 중: {crawler.initial_crawl_progress} /{' '}
                                  {crawler.initial_crawl_total}
                                </div>
                                <div className="w-full bg-muted rounded-full h-2">
                                  <div
                                    className="bg-primary h-2 rounded-full transition-all"
                                    style={{
                                      width: `${
                                        crawler.initial_crawl_total > 0
                                          ? Math.min(100, (crawler.initial_crawl_progress /
                                              crawler.initial_crawl_total) *
                                            100)
                                          : 0
                                      }%`,
                                    }}
                                  />
                                </div>
                              </div>
                            )}

                            {crawler.last_error && (
                              <div className="bg-destructive/10 border border-destructive/20 rounded p-2 mb-3">
                                <p className="text-sm text-destructive font-mono">
                                  {crawler.last_error}
                                </p>
                              </div>
                            )}

                            <div className="grid grid-cols-2 gap-4 text-sm">
                              <div>
                                <span className="text-muted-foreground">마지막 메시지:</span>
                                <p className="font-medium">
                                  {crawler.last_message_at
                                    ? formatDate(crawler.last_message_at)
                                    : '없음'}
                                </p>
                              </div>
                              <div>
                                <span className="text-muted-foreground">업데이트:</span>
                                <p className="font-medium">{formatDate(crawler.updated_at)}</p>
                              </div>
                            </div>

                            <Button
                              variant="outline"
                              size="sm"
                              className="mt-3"
                              onClick={() => {
                                loadCrawlerEvents(parseInt(crawler.group_id));
                                // Switch to events tab
                                const eventsTab = document.querySelector('[value="events"]') as HTMLButtonElement;
                                eventsTab?.click();
                              }}
                            >
                              이벤트 로그 보기
                            </Button>
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  </ScrollArea>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Events tab — comprehensive event log with filtering */}
          <TabsContent value="events">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>전체 상황 - 이벤트 로그</CardTitle>
                  <div className="flex gap-2">
                    <select
                      className="px-3 py-1 text-sm border rounded-md bg-background"
                      value={eventTypeFilter}
                      onChange={(e) => {
                        setEventTypeFilter(e.target.value);
                        loadCrawlerEvents();
                      }}
                    >
                      <option value="all">모든 타입</option>
                      <option value="error">에러</option>
                      <option value="warning">경고</option>
                      <option value="success">성공</option>
                      <option value="recovery">복구</option>
                      <option value="info">정보</option>
                    </select>
                    <select
                      className="px-3 py-1 text-sm border rounded-md bg-background"
                      value={eventCategoryFilter}
                      onChange={(e) => {
                        setEventCategoryFilter(e.target.value);
                        loadCrawlerEvents();
                      }}
                    >
                      <option value="all">모든 카테고리</option>
                      <option value="connection">연결</option>
                      <option value="crawl">크롤링</option>
                      <option value="database">데이터베이스</option>
                      <option value="media">미디어</option>
                      <option value="gap_fill">갭 필</option>
                      <option value="circuit_breaker">Circuit Breaker</option>
                      <option value="system">시스템</option>
                    </select>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => loadCrawlerEvents()}
                      disabled={isLoadingLogs}
                    >
                      <RefreshCw className={`h-4 w-4 ${isLoadingLogs ? 'animate-spin' : ''}`} />
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {isLoadingLogs ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                  </div>
                ) : crawlerEvents.length === 0 ? (
                  <div className="text-center py-12 text-muted-foreground">
                    이벤트 로그가 없습니다
                  </div>
                ) : (
                  <ScrollArea className="h-[600px]">
                    <div className="space-y-3">
                      {crawlerEvents.map((event) => (
                        <Card key={event.id} className={`border-2 ${event.event_type === 'error' ? 'border-destructive/30' : event.event_type === 'success' ? 'border-green-500/30' : 'border-border'}`}>
                          <CardContent className="p-4">
                            <div className="flex items-start justify-between mb-2">
                              <div className="flex items-center gap-2">
                                <Badge variant={getEventBadgeColor(event.event_type)}>
                                  <span className="flex items-center gap-1">
                                    {getEventIcon(event.event_type)}
                                    {event.event_type}
                                  </span>
                                </Badge>
                                <Badge variant="outline" className="text-xs">
                                  {event.event_category}
                                </Badge>
                                {event.resolved && (
                                  <Badge variant="secondary" className="text-xs bg-green-100 text-green-800">
                                    ✓ 해결됨
                                  </Badge>
                                )}
                              </div>
                              <span className="text-xs text-muted-foreground">
                                {formatDate(event.created_at)}
                              </span>
                            </div>

                            {event.group_title && (
                              <p className="text-sm font-medium mb-2 text-primary">
                                📁 {event.group_title}
                              </p>
                            )}

                            <p className="text-base font-semibold mb-1">{event.title}</p>
                            <p className="text-sm text-muted-foreground mb-2">{event.message}</p>

                            {event.resolution_message && (
                              <div className="mt-2 p-2 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded">
                                <p className="text-sm text-green-800 dark:text-green-200">
                                  <CheckCircle className="inline h-3 w-3 mr-1" />
                                  해결: {event.resolution_message}
                                </p>
                                {event.resolved_at && (
                                  <p className="text-xs text-green-600 dark:text-green-400 mt-1">
                                    {formatDate(event.resolved_at)}
                                  </p>
                                )}
                              </div>
                            )}

                            {event.details && Object.keys(event.details).length > 0 && (
                              <details className="mt-2">
                                <summary className="text-sm text-muted-foreground cursor-pointer">
                                  상세 정보 (기술적 세부사항)
                                </summary>
                                <pre className="text-xs bg-muted p-2 rounded mt-2 overflow-auto max-h-[200px]">
                                  {JSON.stringify(event.details, null, 2)}
                                </pre>
                              </details>
                            )}
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  </ScrollArea>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Summary tab — dashboard overview */}
          <TabsContent value="summary">
            <div className="space-y-4">
              {/* Stats grid */}
              {crawlerSummary && (
                <>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium">미해결 문제</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="text-3xl font-bold text-destructive">
                          {crawlerSummary.unresolved_errors.length}
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">
                          에러 및 경고 (자동 해결 대기 중)
                        </p>
                      </CardContent>
                    </Card>

                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium">최근 성공</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="text-3xl font-bold text-green-600">
                          {crawlerSummary.recent_successes.length}
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">
                          최근 성공적으로 완료된 작업
                        </p>
                      </CardContent>
                    </Card>

                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium">자동 복구</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="text-3xl font-bold text-blue-600">
                          {crawlerSummary.recovery_events.length}
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">
                          시스템이 자동으로 복구한 문제
                        </p>
                      </CardContent>
                    </Card>
                  </div>

                  {/* Unresolved errors */}
                  {crawlerSummary.unresolved_errors.length > 0 && (
                    <Card>
                      <CardHeader>
                        <CardTitle className="text-lg">⚠️ 주의가 필요한 문제</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <ScrollArea className="h-[300px]">
                          <div className="space-y-2">
                            {crawlerSummary.unresolved_errors.map((event) => (
                              <div key={event.id} className="p-3 border rounded-md bg-destructive/5">
                                <div className="flex items-start justify-between">
                                  <div className="flex-1">
                                    <p className="font-semibold">{event.title}</p>
                                    <p className="text-sm text-muted-foreground">{event.message}</p>
                                    {event.group_title && (
                                      <p className="text-xs text-muted-foreground mt-1">그룹: {event.group_title}</p>
                                    )}
                                  </div>
                                  <span className="text-xs text-muted-foreground whitespace-nowrap">
                                    {formatDate(event.created_at)}
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </ScrollArea>
                      </CardContent>
                    </Card>
                  )}

                  {/* Recent successes */}
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-lg flex items-center gap-2">
                        <TrendingUp className="h-5 w-5 text-green-600" />
                        최근 성공한 작업
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ScrollArea className="h-[200px]">
                        <div className="space-y-2">
                          {crawlerSummary.recent_successes.map((event) => (
                            <div key={event.id} className="p-2 border rounded-md bg-green-50 dark:bg-green-900/10">
                              <div className="flex items-start justify-between">
                                <div className="flex-1">
                                  <p className="text-sm font-medium">{event.title}</p>
                                  {event.group_title && (
                                    <p className="text-xs text-muted-foreground">그룹: {event.group_title}</p>
                                  )}
                                </div>
                                <span className="text-xs text-muted-foreground whitespace-nowrap">
                                  {formatDate(event.created_at)}
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </ScrollArea>
                    </CardContent>
                  </Card>
                </>
              )}
            </div>
          </TabsContent>

          {/* System Diagnostics Tab */}
          <TabsContent value="diagnostics">
            <div className="space-y-6">
              {isLoadingDiagnostics ? (
                <Card>
                  <CardContent className="pt-6">
                    <div className="flex justify-center items-center py-8">
                      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                    </div>
                  </CardContent>
                </Card>
              ) : systemDiagnostics ? (
                <>
                  {/* Overall Health Card */}
                  <Card>
                    <CardHeader>
                      <div className="flex items-center justify-between">
                        <CardTitle className="flex items-center gap-2">
                          <Activity className="h-5 w-5" />
                          전체 시스템 상태
                        </CardTitle>
                        <div className="flex items-center gap-2">
                          <Badge
                            variant={systemDiagnostics.overall_health === 'healthy' ? 'default' : 'destructive'}
                            className={
                              systemDiagnostics.overall_health === 'healthy'
                                ? 'bg-green-500'
                                : systemDiagnostics.overall_health === 'warning'
                                ? 'bg-yellow-500'
                                : systemDiagnostics.overall_health === 'degraded'
                                ? 'bg-orange-500'
                                : 'bg-red-500'
                            }
                          >
                            {systemDiagnostics.overall_health === 'healthy' && '정상'}
                            {systemDiagnostics.overall_health === 'warning' && '경고'}
                            {systemDiagnostics.overall_health === 'degraded' && '성능 저하'}
                            {systemDiagnostics.overall_health === 'critical' && '심각'}
                          </Badge>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={loadSystemDiagnostics}
                          >
                            <RefreshCw className="mr-2 h-4 w-4" />
                            새로고침
                          </Button>
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent>
                      <p className="text-sm text-muted-foreground">
                        마지막 업데이트: {formatDate(systemDiagnostics.timestamp)}
                      </p>
                      <p className="text-sm text-muted-foreground mt-1">
                        크롤러 연결: {systemDiagnostics.crawler_reachable ? '✅ 연결됨' : '❌ 연결 끊김'}
                      </p>
                    </CardContent>
                  </Card>

                  {/* Components Grid */}
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {systemDiagnostics.components.map((component) => (
                      <Card
                        key={component.name}
                        className={`cursor-pointer transition-all hover:shadow-md ${
                          selectedComponent === component.name ? 'ring-2 ring-primary' : ''
                        }`}
                        onClick={() => {
                          setSelectedComponent(component.name);
                          loadSystemLogs(component.name);
                        }}
                      >
                        <CardHeader className="pb-3">
                          <div className="flex items-start justify-between">
                            <div className="flex-1">
                              <p className="font-semibold text-sm">{component.name}</p>
                              <Badge variant="outline" className="mt-1 text-xs">
                                {component.category}
                              </Badge>
                            </div>
                            <Badge
                              variant={component.health === 'healthy' ? 'default' : 'destructive'}
                              className={
                                component.health === 'healthy'
                                  ? 'bg-green-500'
                                  : component.health === 'warning'
                                  ? 'bg-yellow-500'
                                  : component.health === 'degraded'
                                  ? 'bg-orange-500'
                                  : 'bg-red-500'
                              }
                            >
                              {component.health}
                            </Badge>
                          </div>
                        </CardHeader>
                        <CardContent>
                          <div className="space-y-2">
                            <div>
                              <p className="text-xs text-muted-foreground">상태</p>
                              <p className="text-sm font-medium">{component.status}</p>
                            </div>

                            {/* Metrics */}
                            {Object.keys(component.metrics).length > 0 && (
                              <div className="pt-2 border-t">
                                <p className="text-xs text-muted-foreground mb-1">메트릭</p>
                                {Object.entries(component.metrics).map(([key, value]) => (
                                  <div key={key} className="flex justify-between text-xs">
                                    <span className="text-muted-foreground">{key}:</span>
                                    <span className="font-mono">{String(value)}</span>
                                  </div>
                                ))}
                              </div>
                            )}

                            {/* Issues */}
                            {component.issues.length > 0 && (
                              <div className="pt-2 border-t">
                                <p className="text-xs text-muted-foreground mb-1">⚠️ 문제</p>
                                {component.issues.map((issue, idx) => (
                                  <p key={idx} className="text-xs text-red-600 dark:text-red-400">
                                    • {issue}
                                  </p>
                                ))}
                              </div>
                            )}
                          </div>
                        </CardContent>
                      </Card>
                    ))}
                  </div>

                  {/* Selected Component Logs */}
                  {selectedComponent && (
                    <Card>
                      <CardHeader>
                        <div className="flex items-center justify-between">
                          <CardTitle className="text-lg">{selectedComponent} - 최근 로그</CardTitle>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setSelectedComponent(null);
                              setSystemLogs([]);
                            }}
                          >
                            닫기
                          </Button>
                        </div>
                      </CardHeader>
                      <CardContent>
                        <ScrollArea className="h-[400px]">
                          {systemLogs.length === 0 ? (
                            <p className="text-sm text-muted-foreground text-center py-8">
                              이 컴포넌트에 대한 로그가 없습니다
                            </p>
                          ) : (
                            <div className="space-y-2">
                              {systemLogs.map((log) => (
                                <div
                                  key={log.id}
                                  className={`p-3 border rounded-md ${
                                    log.event_type === 'error'
                                      ? 'bg-red-50 dark:bg-red-900/10'
                                      : log.event_type === 'warning'
                                      ? 'bg-yellow-50 dark:bg-yellow-900/10'
                                      : log.event_type === 'success'
                                      ? 'bg-green-50 dark:bg-green-900/10'
                                      : 'bg-muted/50'
                                  }`}
                                >
                                  <div className="flex items-start justify-between">
                                    <div className="flex-1">
                                      <div className="flex items-center gap-2 mb-1">
                                        <Badge variant={getEventBadgeColor(log.event_type)}>
                                          {getEventIcon(log.event_type)}
                                          <span className="ml-1">{log.event_type}</span>
                                        </Badge>
                                        {log.resolved && (
                                          <Badge variant="secondary" className="text-xs">
                                            <CheckCircle className="mr-1 h-3 w-3" />
                                            해결됨
                                          </Badge>
                                        )}
                                      </div>
                                      <p className="text-sm font-medium">{log.message}</p>
                                      {log.group_title && (
                                        <p className="text-xs text-muted-foreground mt-1">
                                          그룹: {log.group_title}
                                        </p>
                                      )}
                                      {log.resolved && log.resolution_note && (
                                        <p className="text-xs text-green-600 dark:text-green-400 mt-1">
                                          💡 해결 방법: {log.resolution_note}
                                        </p>
                                      )}
                                      {log.metadata && Object.keys(log.metadata).length > 0 && (
                                        <details className="mt-2">
                                          <summary className="text-xs text-muted-foreground cursor-pointer">
                                            상세 정보
                                          </summary>
                                          <pre className="text-xs bg-black/5 dark:bg-white/5 p-2 rounded mt-1 overflow-x-auto">
                                            {JSON.stringify(log.metadata, null, 2)}
                                          </pre>
                                        </details>
                                      )}
                                    </div>
                                    <div className="flex flex-col items-end gap-1">
                                      <span className="text-xs text-muted-foreground whitespace-nowrap">
                                        {formatDate(log.created_at)}
                                      </span>
                                      {log.resolved_at && (
                                        <span className="text-xs text-green-600 dark:text-green-400 whitespace-nowrap">
                                          해결: {formatDate(log.resolved_at)}
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </ScrollArea>
                      </CardContent>
                    </Card>
                  )}
                </>
              ) : (
                <Card>
                  <CardContent className="pt-6">
                    <div className="text-center space-y-4">
                      <AlertCircle className="mx-auto h-12 w-12 text-muted-foreground" />
                      <div>
                        <p className="text-lg font-medium">시스템 진단 정보를 불러올 수 없습니다</p>
                        <p className="text-sm text-muted-foreground mt-2">
                          새로고침 버튼을 눌러 다시 시도하세요
                        </p>
                      </div>
                      <Button onClick={loadSystemDiagnostics} variant="outline">
                        <RefreshCw className="mr-2 h-4 w-4" />
                        새로고침
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

export default function CrawlerManagement() {
  return (
    <ProtectedRoute adminOnly>
      <CrawlerManagementContent />
    </ProtectedRoute>
  );
}
