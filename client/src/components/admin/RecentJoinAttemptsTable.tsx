/**
 * RecentJoinAttemptsTable Component (Phase 3)
 *
 * Displays recent auto-join attempts with success/failure status.
 * Features:
 * - Real-time polling (every 10 seconds)
 * - Success/failure badges with color coding
 * - Connection name display
 * - Relative time formatting ("2분 전")
 * - Error type display for failed attempts
 */

import { useState, useEffect, useCallback } from 'react';
import { Loader2, CheckCircle, XCircle } from 'lucide-react';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../ui/table';
import { Badge } from '../ui/badge';
import { adminApi, type JoinAttempt } from '../../lib/api';

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffSec < 60) return `${diffSec}초 전`;
  if (diffMin < 60) return `${diffMin}분 전`;
  if (diffHour < 24) return `${diffHour}시간 전`;
  return `${diffDay}일 전`;
}

function getErrorDisplayText(errorType: string | null | undefined): string {
  if (!errorType) return '알 수 없음';

  const errorMap: Record<string, string> = {
    'flood_wait': 'FloodWait',
    'invite_expired': '초대 링크 만료',
    'privacy': '권한 오류',
    'channel_private': '비공개 그룹',
    'invite_hash_invalid': '잘못된 초대 링크',
    'invite_hash_expired': '만료된 초대 링크',
    'unknown': '알 수 없는 오류',
  };

  return errorMap[errorType] || errorType;
}

export function RecentJoinAttemptsTable() {
  const [attempts, setAttempts] = useState<JoinAttempt[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAttempts = useCallback(async () => {
    try {
      const response = await adminApi.getRecentJoinAttempts(20);
      setAttempts(response.data);
      setError(null);
    } catch (err) {
      console.error('Failed to load join attempts:', err);
      setError('가입 시도 기록을 불러올 수 없습니다');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAttempts();

    // Poll every 10 seconds for real-time updates
    const interval = setInterval(loadAttempts, 10000);
    return () => clearInterval(interval);
  }, [loadAttempts]);

  if (isLoading) {
    return (
      <div className="flex justify-center items-center p-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex justify-center items-center p-8 text-muted-foreground">
        <p>{error}</p>
      </div>
    );
  }

  if (attempts.length === 0) {
    return (
      <div className="flex justify-center items-center p-8 text-muted-foreground">
        <p>아직 가입 시도 기록이 없습니다</p>
      </div>
    );
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[140px]">시간</TableHead>
            <TableHead>그룹</TableHead>
            <TableHead className="w-[200px]">계정</TableHead>
            <TableHead className="w-[120px]">상태</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {attempts.map((attempt) => (
            <TableRow key={attempt.id}>
              <TableCell className="text-muted-foreground text-sm">
                {formatRelativeTime(attempt.attempted_at)}
              </TableCell>
              <TableCell className="font-mono text-sm max-w-[300px] truncate">
                {attempt.group_link || (attempt.group_username ? `@${attempt.group_username}` : `그룹 ID: ${attempt.group_id || '알 수 없음'}`)}
              </TableCell>
              <TableCell className="text-sm truncate">
                {attempt.connection_name}
              </TableCell>
              <TableCell>
                {attempt.success ? (
                  <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200">
                    <CheckCircle className="h-3 w-3 mr-1" />
                    성공
                  </Badge>
                ) : (
                  <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200">
                    <XCircle className="h-3 w-3 mr-1" />
                    실패 ({getErrorDisplayText(attempt.error_type)})
                  </Badge>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
