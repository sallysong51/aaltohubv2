/**
 * Design Philosophy: Telegram-Native Brutalism
 * - Group cards with thick borders
 * - Clear disabled state for registered groups
 * - Public/Private toggle with visual hierarchy
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useLocation } from 'wouter';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Badge } from '@/components/ui/badge';
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { toast } from 'sonner';
import { Loader2, Users, Lock, Globe, ChevronRight, AlertCircle, Info, CheckCircle2, XCircle, Download, Send } from 'lucide-react';
import { groupsApi, telegramApi, TelegramGroup, TelegramConnection, CrawlProgressItem, getApiErrorMessage } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import ProtectedRoute from '@/components/ProtectedRoute';

function GroupSelectionContent() {
  const [, setLocation] = useLocation();
  const { user, refreshUser } = useAuth();

  const [step, setStep] = useState<'select' | 'visibility' | 'complete'>('select');
  const [groups, setGroups] = useState<TelegramGroup[]>([]);
  const [selectedGroups, setSelectedGroups] = useState<Set<number>>(new Set());
  const [groupVisibility, setGroupVisibility] = useState<Map<number, 'public' | 'private'>>(new Map());
  const [isLoading, setIsLoading] = useState(true);
  const [isRegistering, setIsRegistering] = useState(false);
  const [crawlInitiated, setCrawlInitiated] = useState(false);
  const [crawlProgress, setCrawlProgress] = useState<CrawlProgressItem[]>([]);
  const [registeredGroupIds, setRegisteredGroupIds] = useState<Set<string>>(new Set());
  const [pollError, setPollError] = useState(false);
  const [showTelegramLogin, setShowTelegramLogin] = useState(false);
  const [connections, setConnections] = useState<TelegramConnection[]>([]);
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [connectionsLoaded, setConnectionsLoaded] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollFailCountRef = useRef(0);

  // Load connections on mount
  useEffect(() => {
    loadConnections();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // Load groups when a connection is selected
  useEffect(() => {
    if (selectedConnectionId) {
      loadGroups(selectedConnectionId);
    }
  }, [selectedConnectionId]);

  const loadConnections = async () => {
    setIsLoading(true);
    try {
      const response = await telegramApi.getConnections();
      setConnections(response.data);
      setConnectionsLoaded(true);
      if (response.data.length > 0) {
        // Auto-select first connection
        setSelectedConnectionId(response.data[0].id);
      }
    } catch {
      setConnectionsLoaded(true);
      // No connections → show connect flow
    } finally {
      setIsLoading(false);
    }
  };

  const loadGroups = async (connectionId: string) => {
    setIsLoading(true);
    setShowTelegramLogin(false);
    try {
      const response = await groupsApi.getMyTelegramGroups(connectionId);
      setGroups(response.data);
      setSelectedGroups(new Set());

      const visibilityMap = new Map<number, 'public' | 'private'>();
      response.data.forEach(group => {
        if (!group.is_registered) {
          visibilityMap.set(group.telegram_id, 'public');
        }
      });
      setGroupVisibility(visibilityMap);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        setShowTelegramLogin(true);
        return;
      }
      toast.error(getApiErrorMessage(error, '그룹 목록을 불러오는데 실패했습니다'));
    } finally {
      setIsLoading(false);
    }
  };

  const toggleGroupSelection = (telegramId: number) => {
    const newSelected = new Set(selectedGroups);
    if (newSelected.has(telegramId)) {
      newSelected.delete(telegramId);
    } else {
      newSelected.add(telegramId);
    }
    setSelectedGroups(newSelected);
  };

  const selectAllGroups = () => {
    const allUnregisteredIds = unregisteredGroups.map(g => g.telegram_id);
    setSelectedGroups(new Set(allUnregisteredIds));
    toast.success(`${allUnregisteredIds.length}개 그룹이 모두 선택되었습니다`);
  };

  const deselectAllGroups = () => {
    setSelectedGroups(new Set());
    toast.info('선택이 모두 해제되었습니다');
  };

  const setAllVisibility = (visibility: 'public' | 'private') => {
    const newMap = new Map(groupVisibility);
    selectedGroups.forEach(groupId => {
      newMap.set(groupId, visibility);
    });
    setGroupVisibility(newMap);
    toast.success(`모든 그룹이 ${visibility === 'public' ? '공개' : '비공개'}로 설정되었습니다`);
  };

  const handleNext = () => {
    if (selectedGroups.size === 0) {
      toast.error('최소 하나의 그룹을 선택해주세요');
      return;
    }
    // Rebuild visibility map for currently selected groups only (prevents stale entries)
    const freshMap = new Map<number, 'public' | 'private'>();
    selectedGroups.forEach(gid => {
      freshMap.set(gid, groupVisibility.get(gid) || 'public');
    });
    setGroupVisibility(freshMap);
    setStep('visibility');
  };

  const pollCrawlProgress = useCallback(async () => {
    try {
      const res = await groupsApi.getCrawlProgress();
      // Filter to only show progress for newly registered groups
      const relevant = res.data.filter(
        (p: CrawlProgressItem) => registeredGroupIds.has(String(p.group_id))
      );
      setCrawlProgress(relevant);
      pollFailCountRef.current = 0;
      setPollError(false);

      // Stop polling when all groups are done (active or error)
      const allDone = relevant.length > 0 && relevant.every(
        (p: CrawlProgressItem) => p.status === 'active' || p.status === 'error'
      );
      if (allDone && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    } catch {
      pollFailCountRef.current += 1;
      if (pollFailCountRef.current >= 5) {
        setPollError(true);
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      }
    }
  }, [registeredGroupIds]);

  // Start polling when we enter complete step with registeredGroupIds
  useEffect(() => {
    if (step === 'complete' && registeredGroupIds.size > 0 && crawlInitiated) {
      pollCrawlProgress(); // immediate first call
      pollRef.current = setInterval(pollCrawlProgress, 3000);
      return () => {
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      };
    }
  }, [step, registeredGroupIds, crawlInitiated, pollCrawlProgress]);

  const handleRegister = async () => {
    setIsRegistering(true);
    try {
      const groupsToRegister = groups
        .filter(g => selectedGroups.has(g.telegram_id))
        .map(g => ({
          telegram_id: g.telegram_id,
          title: g.title,
          username: g.username,
          member_count: g.member_count,
          group_type: g.group_type,
          visibility: groupVisibility.get(g.telegram_id) || 'public',
        }));

      const response = await groupsApi.registerGroups({
        groups: groupsToRegister,
        connection_id: selectedConnectionId || undefined,
      });

      if (response.data.success) {
        const registeredCount = response.data.registered_groups.length;
        const initiated = !!response.data.crawl_initiated;
        setCrawlInitiated(initiated);

        // Track which groups were registered for progress filtering
        const newIds = new Set(
          response.data.registered_groups.map(g => String(g.telegram_id))
        );
        setRegisteredGroupIds(newIds);

        if (initiated) {
          toast.success(
            `${registeredCount}개 그룹 등록 완료`,
            { description: '과거 메시지를 수집하는 중입니다.' }
          );
        } else if (registeredCount > 0) {
          toast.success(`${registeredCount}개 그룹 등록 완료`, {
            description: '크롤러 연결에 실패했습니다. 관리자 대시보드에서 수동으로 크롤링을 시작할 수 있습니다.',
          });
        } else {
          toast.info('모든 그룹이 이미 등록되어 있습니다.');
        }

        setStep('complete');
      }
    } catch (error) {
      toast.error(getApiErrorMessage(error, '그룹 등록에 실패했습니다'));
    } finally {
      setIsRegistering(false);
    }
  };

  const handleContinue = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setLocation(user?.role === 'admin' ? '/admin' : '/feed');
  };

  const unregisteredGroups = groups.filter(g => !g.is_registered);
  const registeredGroups = groups.filter(g => g.is_registered);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  // Show connect flow when no connections exist
  if (connectionsLoaded && connections.length === 0 || showTelegramLogin) {
    return (
      <TelegramConnectFlow
        onConnectSuccess={async () => {
          setShowTelegramLogin(false);
          await loadConnections();
        }}
        onCancel={() => setLocation(user?.role === 'admin' ? '/admin' : '/feed')}
      />
    );
  }

  return (
    <div className="min-h-screen bg-background p-4">
      <div className="container max-w-4xl mx-auto py-8">
        {step === 'select' && (
          <>
            <div className="mb-8">
              <h1 className="text-4xl font-bold mb-2">그룹 선택</h1>
              <p className="text-muted-foreground">
                등록할 텔레그램 그룹을 선택하세요
              </p>

              {/* Connection picker */}
              {connections.length > 1 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {connections.map(conn => (
                    <Button
                      key={conn.id}
                      variant={selectedConnectionId === conn.id ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setSelectedConnectionId(conn.id)}
                      className="border-2"
                    >
                      {conn.first_name || conn.username || conn.phone_masked || '텔레그램'}
                      {conn.username && <span className="ml-1 text-xs opacity-70">@{conn.username}</span>}
                    </Button>
                  ))}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowTelegramLogin(true)}
                    className="border-2 border-dashed"
                  >
                    + 계정 추가
                  </Button>
                </div>
              )}
              {connections.length === 1 && (
                <div className="mt-4 flex items-center gap-2">
                  <Badge variant="outline" className="border-2">
                    {connections[0].first_name || connections[0].username || '텔레그램'} 계정
                  </Badge>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setShowTelegramLogin(true)}
                    className="text-xs"
                  >
                    + 다른 계정 추가
                  </Button>
                </div>
              )}
              {unregisteredGroups.length > 0 && (
                <div className="mt-4 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Badge variant={selectedGroups.size > 0 ? "default" : "outline"} className="border-2">
                      {selectedGroups.size}개 선택됨
                    </Badge>
                    <span className="text-sm text-muted-foreground">
                      / 총 {unregisteredGroups.length}개 그룹
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={selectAllGroups}
                      disabled={selectedGroups.size === unregisteredGroups.length}
                      className="border-2"
                    >
                      모두 선택
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={deselectAllGroups}
                      disabled={selectedGroups.size === 0}
                      className="border-2"
                    >
                      선택 해제
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {unregisteredGroups.length === 0 ? (
              <Card className="refined-card">
                <CardContent className="pt-6">
                  <div className="text-center py-8">
                    {registeredGroups.length > 0 ? (
                      <>
                        <Users className="h-12 w-12 mx-auto mb-4 text-primary" />
                        <p className="text-lg font-medium mb-2">모든 그룹이 등록되었습니다</p>
                        <p className="text-sm text-muted-foreground mb-4">
                          텔레그램 그룹 {registeredGroups.length}개가 모두 AaltoHub에 등록되어 있습니다
                        </p>
                        <Button
                          onClick={() => setLocation(user?.role === 'admin' ? '/admin' : '/groups')}
                          className="border-2 border-border btn-pressed"
                        >
                          그룹 관리로 이동
                        </Button>
                      </>
                    ) : (
                      <>
                        <AlertCircle className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                        <p className="text-lg font-medium mb-2">가입된 그룹이 없습니다</p>
                        <p className="text-sm text-muted-foreground mb-4">
                          텔레그램에서 그룹이나 채널에 가입한 후 아래 새로고침을 눌러주세요
                        </p>
                        <Button
                          onClick={() => selectedConnectionId && loadGroups(selectedConnectionId)}
                          variant="outline"
                          className="border-2 border-border"
                        >
                          새로고침
                        </Button>
                      </>
                    )}
                  </div>
                </CardContent>
              </Card>
            ) : (
              <>
                <div className="space-y-4 mb-6">
                  {unregisteredGroups.map((group) => (
                    <Card
                      key={group.telegram_id}
                      className={`refined-card cursor-pointer transition-all ${
                        selectedGroups.has(group.telegram_id)
                          ? 'border-primary'
                          : 'border-border'
                      }`}
                      onClick={() => toggleGroupSelection(group.telegram_id)}
                    >
                      <CardContent className="p-4">
                        <div className="flex items-start gap-4">
                          <Checkbox
                            checked={selectedGroups.has(group.telegram_id)}
                            onCheckedChange={() => toggleGroupSelection(group.telegram_id)}
                            className="mt-1"
                          />
                          <Avatar className="size-14 rounded-lg border-2 border-border shrink-0">
                            {group.photo_url && (
                              <AvatarImage src={group.photo_url} alt={group.title} />
                            )}
                            <AvatarFallback className="rounded-lg font-bold text-lg bg-accent">
                              {group.title.charAt(0).toUpperCase()}
                            </AvatarFallback>
                          </Avatar>
                          <div className="flex-1 min-w-0">
                            <h3 className="font-bold text-lg truncate">{group.title}</h3>
                            {group.username && (
                              <p className="text-sm text-muted-foreground truncate">@{group.username}</p>
                            )}
                            <div className="flex items-center gap-4 mt-2">
                              {group.member_count && (
                                <div className="flex items-center gap-1 text-sm text-muted-foreground">
                                  <Users className="h-4 w-4" />
                                  {group.member_count.toLocaleString()}명
                                </div>
                              )}
                              <Badge variant="outline" className="border-2">
                                {group.group_type === 'channel' ? '채널' :
                                 group.group_type === 'supergroup' ? '슈퍼그룹' : '그룹'}
                              </Badge>
                            </div>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>

                {registeredGroups.length > 0 && (
                  <div className="mb-6">
                    <h2 className="text-xl font-bold mb-4">이미 등록된 그룹</h2>
                    <div className="space-y-4">
                      {registeredGroups.map((group) => (
                        <TooltipProvider key={group.telegram_id}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Card
                                className="refined-card opacity-50 cursor-not-allowed"
                              >
                                <CardContent className="p-4">
                                  <div className="flex items-start gap-4">
                                    <Checkbox checked={false} disabled className="mt-1" />
                                    <Avatar className="size-14 rounded-lg border-2 border-border shrink-0 opacity-50">
                                      {group.photo_url && (
                                        <AvatarImage src={group.photo_url} alt={group.title} />
                                      )}
                                      <AvatarFallback className="rounded-lg font-bold text-lg bg-accent">
                                        {group.title.charAt(0).toUpperCase()}
                                      </AvatarFallback>
                                    </Avatar>
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center gap-2">
                                        <h3 className="font-bold text-lg truncate">{group.title}</h3>
                                        <Info className="h-4 w-4 text-muted-foreground shrink-0" />
                                      </div>
                                      {group.username && (
                                        <p className="text-sm text-muted-foreground truncate">@{group.username}</p>
                                      )}
                                      <Badge variant="secondary" className="mt-2">
                                        이미 등록됨
                                      </Badge>
                                    </div>
                                  </div>
                                </CardContent>
                              </Card>
                            </TooltipTrigger>
                            <TooltipContent side="top" className="border-2 border-border">
                              <p className="font-medium">이미 등록된 그룹입니다</p>
                              <p className="text-xs text-muted-foreground mt-1">
                                이 그룹은 이미 AaltoHub에 등록되어 있어 선택할 수 없습니다
                              </p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex gap-4">
                  <Button
                    variant="outline"
                    onClick={() => setLocation('/groups')}
                    disabled={isRegistering}
                    className="border-2 border-border"
                    size="lg"
                  >
                    취소
                  </Button>
                  <Button
                    onClick={handleNext}
                    disabled={selectedGroups.size === 0 || isRegistering}
                    className="flex-1 border-2 border-border btn-pressed"
                    size="lg"
                  >
                    다음
                    <ChevronRight className="ml-2 h-5 w-5" />
                  </Button>
                </div>
              </>
            )}
          </>
        )}

        {step === 'visibility' && (
          <>
            <div className="mb-8">
              <h1 className="text-4xl font-bold mb-2">공개 여부 설정</h1>
              <p className="text-muted-foreground">
                각 그룹의 공개 여부를 선택하세요 (기본값: 공개)
              </p>
              {selectedGroups.size > 1 && (
                <div className="mt-4 flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setAllVisibility('public')}
                    className="border-2"
                  >
                    <Globe className="mr-2 h-4 w-4" />
                    모두 공개로 설정
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setAllVisibility('private')}
                    className="border-2"
                  >
                    <Lock className="mr-2 h-4 w-4" />
                    모두 비공개로 설정
                  </Button>
                </div>
              )}
            </div>

            <Card className="refined-card mb-6">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <AlertCircle className="h-5 w-5" />
                  안내사항
                </CardTitle>
                <CardDescription>
                  선택한 그룹은 기본적으로 공개(Public)로 설정됩니다. 다른 학생들이 이벤트 정보를 볼 수 있도록 공개를 권장합니다. 
                  비공개로 변경하려면 각 그룹의 설정을 개별적으로 변경해주세요.
                </CardDescription>
              </CardHeader>
            </Card>

            <div className="space-y-4 mb-6">
              {groups
                .filter(g => selectedGroups.has(g.telegram_id))
                .map((group) => (
                  <Card key={group.telegram_id} className="refined-card">
                    <CardContent className="p-6">
                      <h3 className="font-bold text-lg mb-4">{group.title}</h3>
                      <RadioGroup
                        value={groupVisibility.get(group.telegram_id)}
                        onValueChange={(value: 'public' | 'private') => {
                          const newMap = new Map(groupVisibility);
                          newMap.set(group.telegram_id, value);
                          setGroupVisibility(newMap);
                        }}
                      >
                        <div className="space-y-4">
                          <div className="flex items-start space-x-3 p-4 border-2 border-border rounded-lg bg-accent/10">
                            <RadioGroupItem value="public" id={`public-${group.telegram_id}`} />
                            <div className="flex-1">
                              <Label
                                htmlFor={`public-${group.telegram_id}`}
                                className="flex items-center gap-2 font-bold cursor-pointer"
                              >
                                <Globe className="h-4 w-4" />
                                퍼블릭 (Public)
                                <Badge variant="default" className="ml-2">권장</Badge>
                              </Label>
                              <p className="text-sm text-muted-foreground mt-1">
                                이 그룹의 이벤트 정보가 다른 사용자들에게도 공개됩니다. 
                                다른 학생들의 정보 접근을 위해 공개를 권장합니다.
                              </p>
                            </div>
                          </div>

                          <div className="flex items-start space-x-3 p-4 border-2 border-border rounded-lg">
                            <RadioGroupItem value="private" id={`private-${group.telegram_id}`} />
                            <div className="flex-1">
                              <Label
                                htmlFor={`private-${group.telegram_id}`}
                                className="flex items-center gap-2 font-bold cursor-pointer"
                              >
                                <Lock className="h-4 w-4" />
                                프라이빗 (Private)
                              </Label>
                              <p className="text-sm text-muted-foreground mt-1">
                                직접 친구를 초대하거나, 공유 링크를 클릭한 사람만 이 그룹의 이벤트 정보를 볼 수 있습니다.
                              </p>
                            </div>
                          </div>
                        </div>
                      </RadioGroup>
                    </CardContent>
                  </Card>
                ))}
            </div>

            <div className="flex gap-4">
              <Button
                variant="outline"
                onClick={() => setStep('select')}
                disabled={isRegistering}
                className="border-2 border-border"
                size="lg"
              >
                뒤로
              </Button>
              <Button
                onClick={handleRegister}
                disabled={isRegistering}
                className="flex-1 border-2 border-border btn-pressed"
                size="lg"
              >
                {isRegistering ? (
                  <>
                    <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                    등록 중...
                  </>
                ) : (
                  '등록'
                )}
              </Button>
            </div>
          </>
        )}

        {step === 'complete' && (
          <div className="py-8">
            <div className="text-center mb-8">
              <Download className="h-16 w-16 mx-auto mb-4 text-primary" />
              <h2 className="text-2xl font-bold mb-2">등록 완료!</h2>
              {crawlInitiated ? (
                <p className="text-muted-foreground">
                  과거 2주간의 메시지를 수집하고 있습니다
                </p>
              ) : (
                <p className="text-muted-foreground">
                  그룹이 성공적으로 등록되었습니다.
                </p>
              )}
            </div>

            {crawlInitiated && crawlProgress.length > 0 && (
              <div className="space-y-4 mb-8 max-w-xl mx-auto">
                {crawlProgress.map((p) => {
                  const pct = p.initial_crawl_total > 0
                    ? Math.min(100, Math.round((p.initial_crawl_progress / p.initial_crawl_total) * 100))
                    : 0;
                  const isDone = p.status === 'active';
                  const isError = p.status === 'error';
                  const isInitializing = p.status === 'initializing' || p.status === 'inactive';
                  const isCrawling = isInitializing && !!p.is_currently_crawling;
                  const isQueued = isInitializing && !p.is_currently_crawling;

                  return (
                    <Card key={p.group_id} className="refined-card">
                      <CardContent className="p-4">
                        <div className="flex items-center gap-3 mb-2">
                          {isDone && <CheckCircle2 className="h-5 w-5 text-green-500 shrink-0" />}
                          {isError && <XCircle className="h-5 w-5 text-red-500 shrink-0" />}
                          {isCrawling && <Loader2 className="h-5 w-5 animate-spin text-primary shrink-0" />}
                          {isQueued && <Download className="h-5 w-5 text-muted-foreground shrink-0" />}
                          <span className="font-bold truncate">{p.group_name}</span>
                          <span className="ml-auto text-sm text-muted-foreground shrink-0">
                            {isDone && '수집 완료'}
                            {isError && '오류'}
                            {isCrawling && p.initial_crawl_total > 0 && `수집 중: ${p.initial_crawl_progress.toLocaleString()} / ${p.initial_crawl_total.toLocaleString()}`}
                            {isCrawling && p.initial_crawl_total === 0 && '수집 시작 중...'}
                            {isQueued && '대기 중...'}
                          </span>
                        </div>
                        {isCrawling && (
                          <div className="w-full bg-muted rounded-full h-2 overflow-hidden">
                            <div
                              className="bg-primary h-2 rounded-full transition-all duration-500"
                              style={{ width: `${p.initial_crawl_total > 0 ? pct : 10}%` }}
                            />
                          </div>
                        )}
                        {isQueued && (
                          <div className="w-full bg-muted rounded-full h-2 overflow-hidden">
                            <div className="bg-muted-foreground/30 h-2 rounded-full w-[5%]" />
                          </div>
                        )}
                        {isDone && (
                          <div className="w-full bg-green-100 dark:bg-green-950 rounded-full h-2">
                            <div className="bg-green-500 h-2 rounded-full w-full" />
                          </div>
                        )}
                        {isError && p.last_error && (
                          <p className="text-xs text-red-500 mt-1 truncate">{p.last_error}</p>
                        )}
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}

            {crawlInitiated && crawlProgress.length === 0 && !pollError && (
              <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground mb-8">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>크롤러에 연결 중...</span>
              </div>
            )}

            {pollError && (
              <div className="text-center text-sm text-red-500 mb-8">
                <AlertCircle className="h-4 w-4 inline mr-1" />
                진행 상태를 가져올 수 없습니다.{' '}
                <button
                  className="underline ml-1"
                  onClick={() => {
                    setPollError(false);
                    pollFailCountRef.current = 0;
                    pollCrawlProgress();
                    pollRef.current = setInterval(pollCrawlProgress, 3000);
                  }}
                >
                  다시 시도
                </button>
              </div>
            )}

            <div className="flex justify-center gap-4">
              {(() => {
                const allDone = crawlProgress.length > 0 && crawlProgress.every(
                  p => p.status === 'active' || p.status === 'error'
                );
                return (
                  <>
                    <Button
                      onClick={handleContinue}
                      className="border-2 border-border btn-pressed"
                      size="lg"
                    >
                      {allDone || !crawlInitiated ? '계속하기' : '건너뛰기'}
                      <ChevronRight className="ml-2 h-5 w-5" />
                    </Button>
                  </>
                );
              })()}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Inline Telegram connect flow component for GroupSelection
interface TelegramConnectFlowProps {
  onConnectSuccess: () => void;
  onCancel: () => void;
}

function TelegramConnectFlow({ onConnectSuccess, onCancel }: TelegramConnectFlowProps) {
  const [step, setStep] = useState<'phone' | 'code' | '2fa'>('phone');
  const [phoneOrUsername, setPhoneOrUsername] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [phoneCodeHash, setPhoneCodeHash] = useState('');
  const [sendStatus, setSendStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [isLoading, setIsLoading] = useState(false);
  const [resendTimer, setResendTimer] = useState(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const phoneCodeHashRef = useRef('');
  const pendingCodeRef = useRef<string | null>(null);
  const isSubmitting = useRef(false);

  const startResendTimer = useCallback(() => {
    setResendTimer(60);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setResendTimer((prev) => {
        if (prev <= 1) {
          if (timerRef.current) clearInterval(timerRef.current);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const doVerifyCode = useCallback(async (codeValue: string, hash: string) => {
    if (isSubmitting.current) return;
    isSubmitting.current = true;
    setIsLoading(true);
    try {
      await telegramApi.verifyCode({
        phone_or_username: phoneOrUsername,
        code: codeValue,
        phone_code_hash: hash,
      });
      onConnectSuccess();
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 403) {
        setStep('2fa');
        toast.info('2단계 인증이 필요합니다');
      } else if (axios.isAxiosError(error) && error.response?.status === 408) {
        setStep('phone');
        setCode('');
        setPhoneCodeHash('');
        phoneCodeHashRef.current = '';
        setSendStatus('idle');
        toast.error('세션이 만료되었습니다. 다시 시도해주세요');
      } else {
        toast.error(getApiErrorMessage(error, '코드 검증 실패'));
      }
    } finally {
      setIsLoading(false);
      isSubmitting.current = false;
    }
  }, [phoneOrUsername, onConnectSuccess]);

  const submitCode = useCallback(async (codeValue: string) => {
    const hash = phoneCodeHashRef.current;
    if (!hash) {
      pendingCodeRef.current = codeValue;
      return;
    }
    await doVerifyCode(codeValue, hash);
  }, [doVerifyCode]);

  const handleSendCode = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!phoneOrUsername.trim()) {
      toast.error('전화번호 또는 username을 입력해주세요');
      return;
    }

    setSendStatus('sending');
    setCode('');
    setStep('code');

    try {
      const response = await telegramApi.sendCode({ phone_or_username: phoneOrUsername });
      if (response.data.success) {
        const hash = response.data.phone_code_hash || '';
        phoneCodeHashRef.current = hash;
        setPhoneCodeHash(hash);
        setSendStatus('sent');
        startResendTimer();

        if (pendingCodeRef.current) {
          const pending = pendingCodeRef.current;
          pendingCodeRef.current = null;
          await doVerifyCode(pending, hash);
        }
      } else {
        setSendStatus('error');
        toast.error(response.data.message || '코드 전송 실패');
      }
    } catch (error) {
      setSendStatus('error');
      toast.error(getApiErrorMessage(error, '코드 전송 중 오류가 발생했습니다'));
    }
  };

  const handleCodeChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value.replace(/\D/g, '').slice(0, 5);
    setCode(value);
    if (value.length === 5) {
      submitCode(value);
    }
  }, [submitCode]);

  const handleVerify2FA = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim()) {
      toast.error('2FA 비밀번호를 입력해주세요');
      return;
    }
    setIsLoading(true);
    try {
      await telegramApi.verify2FA({
        phone_or_username: phoneOrUsername,
        password,
        phone_code_hash: phoneCodeHash,
      });
      onConnectSuccess();
    } catch (error) {
      toast.error(getApiErrorMessage(error, '2FA 검증 실패'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md refined-card">
        <CardHeader>
          <CardTitle className="text-2xl font-bold text-center">
            텔레그램 연결
          </CardTitle>
          <CardDescription className="text-center">
            그룹을 추가하기 위해 텔레그램 계정을 연결하세요
          </CardDescription>
        </CardHeader>
        <CardContent>
          {step === 'phone' && (
            <form onSubmit={handleSendCode} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="phone">전화번호 또는 Username</Label>
                <Input
                  id="phone"
                  type="text"
                  placeholder="+358... 또는 @username"
                  value={phoneOrUsername}
                  onChange={(e) => setPhoneOrUsername(e.target.value)}
                  autoFocus
                />
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={onCancel}
                  disabled={isLoading}
                  className="flex-1 border-2 border-border"
                >
                  취소
                </Button>
                <Button
                  type="submit"
                  className="flex-1 border-2 border-border btn-pressed"
                  disabled={isLoading}
                >
                  {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                  코드 받기
                </Button>
              </div>
            </form>
          )}

          {step === 'code' && (
            <form onSubmit={(e) => { e.preventDefault(); submitCode(code); }} className="space-y-4">
              <div className="flex items-center gap-2 px-3 py-2 bg-muted rounded-md text-sm">
                <span className="font-medium flex-1 truncate">{phoneOrUsername}</span>
              </div>
              <div className="space-y-2">
                <Label htmlFor="code">인증 코드</Label>
                <Input
                  id="code"
                  type="text"
                  inputMode="numeric"
                  placeholder="12345"
                  value={code}
                  onChange={handleCodeChange}
                  className="border-2 border-border font-mono text-center text-2xl"
                  disabled={isLoading}
                  maxLength={5}
                  autoFocus
                />
              </div>
              {resendTimer > 0 && (
                <p className="text-xs text-center text-muted-foreground">
                  {resendTimer}초 후 재전송 가능
                </p>
              )}
              <Button
                type="submit"
                className="w-full border-2 border-border btn-pressed"
                disabled={isLoading || code.length < 5}
              >
                {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                확인
              </Button>
            </form>
          )}

          {step === '2fa' && (
            <form onSubmit={handleVerify2FA} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="password">2단계 인증 비밀번호</Label>
                <Input
                  id="password"
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isLoading}
                  autoFocus
                />
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={onCancel}
                  disabled={isLoading}
                  className="flex-1 border-2 border-border"
                >
                  취소
                </Button>
                <Button
                  type="submit"
                  className="flex-1 border-2 border-border btn-pressed"
                  disabled={isLoading}
                >
                  {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Lock className="mr-2 h-4 w-4" />}
                  확인
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function GroupSelection() {
  return (
    <ProtectedRoute>
      <GroupSelectionContent />
    </ProtectedRoute>
  );
}
