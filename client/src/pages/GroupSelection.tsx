/**
 * Group Selection wizard — 3-step flow: Select → Visibility → Complete.
 * Step UI is delegated to components/groups/{SelectStep,VisibilityStep,CompleteStep}.
 * This orchestrator owns all state and business logic.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useLocation } from 'wouter';
import axios from 'axios';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import { groupsApi, telegramApi, TelegramGroup, TelegramConnection, CrawlProgressItem, getApiErrorMessage } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import ProtectedRoute from '@/components/ProtectedRoute';
import TelegramConnectFlow from '@/components/TelegramConnectFlow';
import SelectStep from '@/components/groups/SelectStep';
import VisibilityStep from '@/components/groups/VisibilityStep';
import CompleteStep from '@/components/groups/CompleteStep';

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

  useEffect(() => {
    loadConnections();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  useEffect(() => {
    if (selectedConnectionId) loadGroups(selectedConnectionId);
  }, [selectedConnectionId]);

  const loadConnections = async () => {
    setIsLoading(true);
    try {
      const response = await telegramApi.getConnections();
      setConnections(response.data);
      setConnectionsLoaded(true);
      if (response.data.length > 0) setSelectedConnectionId(response.data[0].id);
    } catch {
      setConnectionsLoaded(true);
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
        if (!group.is_registered) visibilityMap.set(group.telegram_id, 'public');
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

  const unregisteredGroups = groups.filter(g => !g.is_registered);
  const registeredGroups = groups.filter(g => g.is_registered);

  const toggleGroupSelection = (telegramId: number) => {
    const next = new Set(selectedGroups);
    next.has(telegramId) ? next.delete(telegramId) : next.add(telegramId);
    setSelectedGroups(next);
  };

  const selectAllGroups = () => {
    setSelectedGroups(new Set(unregisteredGroups.map(g => g.telegram_id)));
    toast.success(`${unregisteredGroups.length}개 그룹이 모두 선택되었습니다`);
  };

  const deselectAllGroups = () => {
    setSelectedGroups(new Set());
    toast.info('선택이 모두 해제되었습니다');
  };

  const setAllVisibility = (visibility: 'public' | 'private') => {
    const newMap = new Map(groupVisibility);
    selectedGroups.forEach(gid => newMap.set(gid, visibility));
    setGroupVisibility(newMap);
    toast.success(`모든 그룹이 ${visibility === 'public' ? '공개' : '비공개'}로 설정되었습니다`);
  };

  const handleVisibilityChange = (groupId: number, visibility: 'public' | 'private') => {
    const newMap = new Map(groupVisibility);
    newMap.set(groupId, visibility);
    setGroupVisibility(newMap);
  };

  const handleNext = () => {
    if (selectedGroups.size === 0) { toast.error('최소 하나의 그룹을 선택해주세요'); return; }
    const freshMap = new Map<number, 'public' | 'private'>();
    selectedGroups.forEach(gid => freshMap.set(gid, groupVisibility.get(gid) || 'public'));
    setGroupVisibility(freshMap);
    setStep('visibility');
  };

  const pollCrawlProgress = useCallback(async () => {
    try {
      const res = await groupsApi.getCrawlProgress();
      const relevant = res.data.filter((p: CrawlProgressItem) => registeredGroupIds.has(String(p.group_id)));
      setCrawlProgress(relevant);
      pollFailCountRef.current = 0;
      setPollError(false);
      const allDone = relevant.length > 0 && relevant.every((p: CrawlProgressItem) => p.status === 'active' || p.status === 'error');
      if (allDone && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    } catch {
      pollFailCountRef.current += 1;
      if (pollFailCountRef.current >= 5) {
        setPollError(true);
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      }
    }
  }, [registeredGroupIds]);

  useEffect(() => {
    if (step === 'complete' && registeredGroupIds.size > 0 && crawlInitiated) {
      pollCrawlProgress();
      pollRef.current = setInterval(pollCrawlProgress, 3000);
      return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
    }
  }, [step, registeredGroupIds, crawlInitiated, pollCrawlProgress]);

  const handleRegister = async () => {
    setIsRegistering(true);
    try {
      const groupsToRegister = groups
        .filter(g => selectedGroups.has(g.telegram_id))
        .map(g => ({
          telegram_id: g.telegram_id, title: g.title, username: g.username,
          member_count: g.member_count, group_type: g.group_type,
          visibility: groupVisibility.get(g.telegram_id) || 'public',
        }));
      const response = await groupsApi.registerGroups({ groups: groupsToRegister, connection_id: selectedConnectionId || undefined });
      if (response.data.success) {
        const registeredCount = response.data.registered_groups.length;
        const initiated = !!response.data.crawl_initiated;
        setCrawlInitiated(initiated);
        setRegisteredGroupIds(new Set(response.data.registered_groups.map(g => String(g.telegram_id))));
        if (initiated) {
          toast.success(`${registeredCount}개 그룹 등록 완료`, { description: '과거 메시지를 수집하는 중입니다.' });
        } else if (registeredCount > 0) {
          toast.success(`${registeredCount}개 그룹 등록 완료`, { description: '크롤러 연결에 실패했습니다. 관리자 대시보드에서 수동으로 크롤링을 시작할 수 있습니다.' });
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
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    setLocation(user?.role === 'admin' ? '/admin' : '/feed');
  };

  const handleRetryPoll = () => {
    setPollError(false);
    pollFailCountRef.current = 0;
    pollCrawlProgress();
    pollRef.current = setInterval(pollCrawlProgress, 3000);
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  // No connections → show connect flow
  if ((connectionsLoaded && connections.length === 0) || showTelegramLogin) {
    return (
      <TelegramConnectFlow
        onConnectSuccess={async () => { setShowTelegramLogin(false); await loadConnections(); }}
        onCancel={() => setLocation(user?.role === 'admin' ? '/admin' : '/feed')}
      />
    );
  }

  return (
    <div className="min-h-screen bg-background p-4">
      <div className="container max-w-4xl mx-auto py-8">
        {step === 'select' && (
          <SelectStep
            groups={groups}
            unregisteredGroups={unregisteredGroups}
            registeredGroups={registeredGroups}
            selectedGroups={selectedGroups}
            connections={connections}
            selectedConnectionId={selectedConnectionId}
            isRegistering={isRegistering}
            userRole={user?.role}
            onToggleGroup={toggleGroupSelection}
            onSelectAll={selectAllGroups}
            onDeselectAll={deselectAllGroups}
            onConnectionSelect={setSelectedConnectionId}
            onShowTelegramLogin={() => setShowTelegramLogin(true)}
            onNext={handleNext}
            onCancel={() => setLocation(user?.role === 'admin' ? '/admin' : '/groups')}
            onRefreshGroups={loadGroups}
          />
        )}
        {step === 'visibility' && (
          <VisibilityStep
            groups={groups}
            selectedGroups={selectedGroups}
            groupVisibility={groupVisibility}
            isRegistering={isRegistering}
            onVisibilityChange={handleVisibilityChange}
            onSetAllVisibility={setAllVisibility}
            onRegister={handleRegister}
            onBack={() => setStep('select')}
          />
        )}
        {step === 'complete' && (
          <CompleteStep
            crawlInitiated={crawlInitiated}
            crawlProgress={crawlProgress}
            pollError={pollError}
            onContinue={handleContinue}
            onRetryPoll={handleRetryPoll}
          />
        )}
      </div>
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
