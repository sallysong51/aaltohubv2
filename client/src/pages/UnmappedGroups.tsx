/**
 * Unmapped Groups Page
 * Shows groups registered by users that admin accounts haven't joined yet.
 * Admin can trigger auto-join to start crawling these groups.
 */
import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { toast } from 'sonner';
import {
  Loader2, ArrowLeft, Users, AlertCircle, RefreshCw,
  LinkIcon, ExternalLink, UserPlus, CheckCircle2, XCircle,
} from 'lucide-react';
import { adminApi, getApiErrorMessage } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import ProtectedRoute from '@/components/ProtectedRoute';
import { useLocation } from 'wouter';

interface UnmappedGroup {
  group_id: number;
  name: string;
  username: string | null;
  invite_link: string | null;
  type: string;
  member_count: number;
  visibility: string;
  crawl_status: string | null;
  registered_by: number | null;
  registrant_name: string;
}

interface JoinResult {
  group_id: number;
  group_name: string;
  success: boolean;
  method?: string;
  error?: string;
}

function UnmappedGroupsContent() {
  const [, setLocation] = useLocation();
  const [groups, setGroups] = useState<UnmappedGroup[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isJoining, setIsJoining] = useState(false);
  const [joinResults, setJoinResults] = useState<JoinResult[] | null>(null);

  useEffect(() => {
    loadGroups();
  }, []);

  const loadGroups = async () => {
    setIsLoading(true);
    try {
      const res = await adminApi.getUnmappedGroups();
      setGroups(res.data.groups);
    } catch (error) {
      toast.error(getApiErrorMessage(error, '미등록 그룹 목록을 불러오는데 실패했습니다'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleAutoJoin = async () => {
    setIsJoining(true);
    setJoinResults(null);
    try {
      const res = await adminApi.autoJoinGroups();
      setJoinResults(res.data.results);
      toast.success(`${res.data.joined}/${res.data.total}개 그룹에 참여했습니다`);
      // Reload to reflect changes
      await loadGroups();
    } catch (error) {
      toast.error(getApiErrorMessage(error, '자동 참여에 실패했습니다'));
    } finally {
      setIsJoining(false);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b border-border bg-card">
        <div className="container py-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setLocation('/admin')}
                className="h-8 px-3 text-xs"
              >
                <ArrowLeft className="h-3.5 w-3.5 mr-1.5" />
                관리자
              </Button>
              <div>
                <h1 className="text-xl font-bold flex items-center gap-2">
                  <LinkIcon className="h-5 w-5" />
                  미등록 그룹
                </h1>
                <p className="text-xs text-muted-foreground mt-0.5">
                  사용자가 등록했지만 관리자 계정이 아직 참여하지 않은 그룹
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={loadGroups}
                disabled={isLoading}
                className="h-8 px-3 text-xs"
              >
                <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${isLoading ? 'animate-spin' : ''}`} />
                새로고침
              </Button>
              <Button
                size="sm"
                onClick={handleAutoJoin}
                disabled={isJoining || groups.length === 0}
                className="h-8 px-3 text-xs"
              >
                {isJoining ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                    참여 중...
                  </>
                ) : (
                  <>
                    <UserPlus className="h-3.5 w-3.5 mr-1.5" />
                    자동 참여
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="container py-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : groups.length === 0 ? (
          <div className="flex items-center justify-center py-20">
            <div className="text-center">
              <CheckCircle2 className="h-16 w-16 mx-auto mb-4 text-green-500" />
              <h2 className="text-lg font-bold mb-1">모든 그룹이 연결되었습니다</h2>
              <p className="text-sm text-muted-foreground">미등록 그룹이 없습니다</p>
            </div>
          </div>
        ) : (
          <>
            <div className="mb-4 flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                총 <strong>{groups.length}</strong>개의 미등록 그룹
              </p>
            </div>

            {/* Join Results */}
            {joinResults && joinResults.length > 0 && (
              <div className="mb-4 p-3 rounded-lg border border-border bg-card">
                <h3 className="font-semibold text-sm mb-2">참여 결과</h3>
                <div className="space-y-1">
                  {joinResults.map((r, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      {r.success ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-green-500 flex-shrink-0" />
                      ) : (
                        <XCircle className="h-3.5 w-3.5 text-red-500 flex-shrink-0" />
                      )}
                      <span className="font-medium">{r.group_name}</span>
                      {r.success && r.method && (
                        <Badge variant="outline" className="text-[10px] py-0">
                          {r.method}
                        </Badge>
                      )}
                      {!r.success && r.error && (
                        <span className="text-muted-foreground">{r.error}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Groups Table */}
            <div className="border border-border rounded-lg overflow-hidden">
              <div className="grid grid-cols-[1fr_auto_auto_auto] gap-0 text-xs font-semibold bg-muted px-4 py-2">
                <div>그룹</div>
                <div className="w-24 text-center">멤버</div>
                <div className="w-28 text-center">공개 설정</div>
                <div className="w-32 text-center">등록자</div>
              </div>
              <ScrollArea className="max-h-[calc(100vh-300px)]">
                {groups.map((group) => (
                  <div
                    key={group.group_id}
                    className="grid grid-cols-[1fr_auto_auto_auto] gap-0 items-center text-xs px-4 py-3 border-t border-border hover:bg-accent/30 transition-colors"
                  >
                    <div className="min-w-0">
                      <div className="font-medium truncate">{group.name}</div>
                      <div className="flex items-center gap-2 mt-0.5">
                        {group.username && (
                          <a
                            href={`https://t.me/${group.username}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary hover:underline flex items-center gap-0.5"
                          >
                            <ExternalLink className="h-2.5 w-2.5" />
                            @{group.username}
                          </a>
                        )}
                        {group.invite_link && (
                          <a
                            href={group.invite_link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary hover:underline flex items-center gap-0.5"
                          >
                            <LinkIcon className="h-2.5 w-2.5" />
                            초대 링크
                          </a>
                        )}
                        <Badge variant="outline" className="text-[10px] py-0">
                          {group.type}
                        </Badge>
                      </div>
                    </div>
                    <div className="w-24 text-center text-muted-foreground">
                      <Users className="h-3 w-3 inline mr-1" />
                      {group.member_count.toLocaleString()}
                    </div>
                    <div className="w-28 text-center">
                      <Badge
                        variant={group.visibility === 'public' ? 'default' : 'secondary'}
                        className="text-[10px] py-0"
                      >
                        {group.visibility === 'public' ? '공개' : '비공개'}
                      </Badge>
                    </div>
                    <div className="w-32 text-center text-muted-foreground truncate">
                      {group.registrant_name}
                    </div>
                  </div>
                ))}
              </ScrollArea>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function UnmappedGroups() {
  return (
    <ProtectedRoute adminOnly>
      <UnmappedGroupsContent />
    </ProtectedRoute>
  );
}
