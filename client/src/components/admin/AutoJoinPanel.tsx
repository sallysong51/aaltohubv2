/**
 * AutoJoinPanel Component (Phase 3)
 *
 * Allows admins to automatically join Telegram groups by entering a link or username.
 * Features:
 * - Real-time input validation (Telegram link or @username format)
 * - Automatic connection selection (smart algorithm avoids FloodWait)
 * - Success/error feedback via toast notifications
 * - Queue status display when all connections busy
 * - Automatic group list refresh on success
 */

import { useState, useMemo } from 'react';
import { UserPlus, Loader2, Clock, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { Alert, AlertDescription, AlertTitle } from '../ui/alert';
import { adminApi, getApiErrorMessage, type AutoJoinResponse } from '../../lib/api';
import { toast } from 'sonner';

interface AutoJoinPanelProps {
  onSuccess?: (response: AutoJoinResponse) => void;
}

export function AutoJoinPanel({ onSuccess }: AutoJoinPanelProps) {
  const [identifier, setIdentifier] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<AutoJoinResponse | null>(null);

  // Real-time validation for Telegram identifiers
  const isValid = useMemo(() => {
    if (!identifier) return false;

    // Telegram invite link: https://t.me/joinchat/ABC or t.me/joinchat/ABC
    const inviteLinkRegex = /^(https?:\/\/)?(t\.me\/joinchat\/[\w-]+)$/i;
    // Telegram username link: https://t.me/username or t.me/username or @username
    const usernameRegex = /^(https?:\/\/)?(t\.me\/[\w]+|@[\w]{5,})$/i;
    // Numeric group ID: -1001234567890
    const groupIdRegex = /^-\d{10,}$/;

    return (
      inviteLinkRegex.test(identifier) ||
      usernameRegex.test(identifier) ||
      groupIdRegex.test(identifier)
    );
  }, [identifier]);

  const handleSubmit = async () => {
    if (!isValid) {
      toast.error('올바른 텔레그램 링크, @username, 또는 그룹 ID를 입력하세요');
      return;
    }

    setIsLoading(true);
    setResult(null);

    try {
      const response = await adminApi.autoJoinGroup({ identifier });
      setResult(response);

      if (response.success) {
        toast.success(`${response.group_title}에 가입했습니다`);
        setIdentifier('');  // Clear input on success
        onSuccess?.(response);
      } else if (response.estimated_wait_seconds) {
        const waitMinutes = Math.ceil(response.estimated_wait_seconds / 60);
        toast.warning(`대기 중... 약 ${waitMinutes}분 후 자동 재시도됩니다`);
      } else {
        toast.error(response.message);
      }
    } catch (error) {
      console.error('Auto-join error:', error);
      toast.error(getApiErrorMessage(error, '가입 요청 실패'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && isValid && !isLoading) {
      handleSubmit();
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <UserPlus className="h-5 w-5" />
          자동 그룹 가입
        </CardTitle>
        <CardDescription>
          텔레그램 링크, @username, 또는 그룹 ID를 입력하면 관리자 계정이 자동으로 가입합니다
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Input
            placeholder="https://t.me/joinchat/... 또는 @username 또는 -1001234567890"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            className={!isValid && identifier ? 'border-red-500' : ''}
          />
          <Button
            onClick={handleSubmit}
            disabled={isLoading || !isValid || !identifier}
          >
            {isLoading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                가입 중...
              </>
            ) : (
              <>
                <UserPlus className="mr-2 h-4 w-4" />
                가입하기
              </>
            )}
          </Button>
        </div>

        {/* Queued (all connections busy) */}
        {result && !result.success && result.estimated_wait_seconds && (
          <Alert>
            <Clock className="h-4 w-4" />
            <AlertTitle>대기열에 추가됨</AlertTitle>
            <AlertDescription>
              모든 계정이 일시적으로 사용 불가합니다.
              약 {Math.ceil(result.estimated_wait_seconds / 60)}분 후 자동으로 가입을 시도합니다.
            </AlertDescription>
          </Alert>
        )}

        {/* Failed (no wait time) */}
        {result && !result.success && !result.estimated_wait_seconds && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{result.message}</AlertDescription>
          </Alert>
        )}

        {/* Input format help */}
        {!identifier && (
          <div className="text-sm text-muted-foreground">
            <p className="font-medium mb-1">지원 형식:</p>
            <ul className="list-disc list-inside space-y-0.5 ml-2">
              <li>초대 링크: <code className="text-xs">https://t.me/joinchat/ABC123</code></li>
              <li>Username: <code className="text-xs">@groupname</code> 또는 <code className="text-xs">https://t.me/groupname</code></li>
              <li>그룹 ID: <code className="text-xs">-1001234567890</code></li>
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
