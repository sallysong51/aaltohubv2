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
import { Loader2, AlertCircle, CheckCircle, XCircle, RefreshCw, ArrowLeft } from 'lucide-react';
import ProtectedRoute from '@/components/ProtectedRoute';
import apiClient, { getApiErrorMessage } from '@/lib/api';

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

interface ErrorLog {
  id: string;
  group_id?: string;
  group_title?: string;
  error_type: string;
  error_message: string;
  error_details?: Record<string, unknown>;
  created_at: string;
}

interface LiveCrawlerStatus {
  running: boolean;
  connected: boolean;
  groups_count: number;
  messages_received: number;
  historical_crawl_running: boolean;
  crawled_groups: number;
  uptime_seconds: number;
}

function CrawlerManagementContent() {
  const [, setLocation] = useLocation();
  const [crawlerStatuses, setCrawlerStatuses] = useState<CrawlerStatus[]>([]);
  const [errorLogs, setErrorLogs] = useState<ErrorLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingLogs, setIsLoadingLogs] = useState(false);
  const [liveStatus, setLiveStatus] = useState<LiveCrawlerStatus | null>(null);

  useEffect(() => {
    loadCrawlerStatuses();
    loadLiveStatus();
    const interval = setInterval(loadLiveStatus, 30_000);
    return () => clearInterval(interval);
  }, []);

  const loadLiveStatus = async () => {
    try {
      const res = await apiClient.get('/admin/live-crawler/status');
      setLiveStatus(res.data);
    } catch { /* ignore */ }
  };

  const handleRestartLiveCrawler = async () => {
    try {
      await apiClient.post('/admin/live-crawler/restart');
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
      const response = await apiClient.get('/admin/crawler-status');
      setCrawlerStatuses(response.data);
    } catch (error) {
      toast.error(getApiErrorMessage(error, '크롤러 상태를 불러오는데 실패했습니다'));
    } finally {
      setIsLoading(false);
    }
  };

  const loadErrorLogs = async (groupId?: string) => {
    setIsLoadingLogs(true);
    try {
      const response = await apiClient.get('/admin/error-logs', {
        params: groupId ? { group_id: groupId } : undefined,
      });
      setErrorLogs(response.data);
    } catch (error) {
      toast.error(getApiErrorMessage(error, '에러 로그를 불러오는데 실패했습니다'));
    } finally {
      setIsLoadingLogs(false);
    }
  };

  const toggleCrawler = async (groupId: string, isEnabled: boolean) => {
    try {
      await apiClient.post(`/admin/crawler-status/${groupId}/toggle`, null, {
        params: { is_enabled: isEnabled },
      });
      toast.success(isEnabled ? '크롤러가 활성화되었습니다' : '크롤러가 비활성화되었습니다');
      loadCrawlerStatuses();
    } catch (error) {
      toast.error(getApiErrorMessage(error, '크롤러 상태 변경에 실패했습니다'));
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

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleString('ko-KR');
  };

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
            <TabsTrigger value="errors" onClick={() => loadErrorLogs()}>
              에러 로그
            </TabsTrigger>
          </TabsList>

          <TabsContent value="status">
            {/* Live Crawler Status */}
            {liveStatus && (
              <Card className="mb-4">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle>라이브 크롤러</CardTitle>
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
                              onClick={() => loadErrorLogs(crawler.group_id)}
                            >
                              에러 로그 보기
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

          <TabsContent value="errors">
            <Card>
              <CardHeader>
                <CardTitle>에러 로그</CardTitle>
              </CardHeader>
              <CardContent>
                {isLoadingLogs ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                  </div>
                ) : errorLogs.length === 0 ? (
                  <div className="text-center py-12 text-muted-foreground">
                    에러 로그가 없습니다
                  </div>
                ) : (
                  <ScrollArea className="h-[600px]">
                    <div className="space-y-3">
                      {errorLogs.map((log) => (
                        <Card key={log.id} className="border-2 border-destructive/20">
                          <CardContent className="p-4">
                            <div className="flex items-start justify-between mb-2">
                              <Badge variant="destructive">{log.error_type}</Badge>
                              <span className="text-xs text-muted-foreground">
                                {formatDate(log.created_at)}
                              </span>
                            </div>
                            {log.group_title && (
                              <p className="text-sm font-medium mb-2">{log.group_title}</p>
                            )}
                            <p className="text-sm font-mono bg-muted p-2 rounded">
                              {log.error_message}
                            </p>
                            {log.error_details && (
                              <details className="mt-2">
                                <summary className="text-sm text-muted-foreground cursor-pointer">
                                  상세 정보
                                </summary>
                                <pre className="text-xs bg-muted p-2 rounded mt-2 overflow-auto">
                                  {JSON.stringify(log.error_details, null, 2)}
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
