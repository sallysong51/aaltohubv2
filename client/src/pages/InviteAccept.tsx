/**
 * Invite Accept Page
 * Accept invite link to join private group
 */
import { useState, useEffect } from 'react';
import { useRoute, useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';
import { Loader2, CheckCircle, XCircle } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { groupsApi, getApiErrorMessage } from '@/lib/api';

export default function InviteAccept() {
  const [, params] = useRoute('/invite/:token');
  const [, setLocation] = useLocation();
  const { user, isAuthenticated } = useAuth();
  
  const [isLoading, setIsLoading] = useState(false);
  const [isAccepted, setIsAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const token = params?.token;

  useEffect(() => {
    if (!token) {
      setError('유효하지 않은 초대 링크입니다');
    }
  }, [token]);

  const handleAcceptInvite = async () => {
    if (!isAuthenticated) {
      toast.info('로그인이 필요합니다');
      // Store invite path so user can return after login
      sessionStorage.setItem('redirect_after_login', `/invite/${token}`);
      setLocation('/login');
      return;
    }

    if (!token) {
      toast.error('유효하지 않은 초대 링크입니다');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await groupsApi.acceptInvite(token);
      setIsAccepted(true);
      toast.success('그룹에 성공적으로 참여했습니다!');
    } catch (error) {
      const errorMessage = getApiErrorMessage(error, '초대 수락에 실패했습니다');
      setError(errorMessage);
      toast.error(errorMessage);
    } finally {
      setIsLoading(false);
    }
  };

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Card className="max-w-md w-full border-2 border-destructive">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <XCircle className="h-5 w-5 text-destructive" />
              유효하지 않은 링크
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground mb-4">
              초대 링크가 올바르지 않습니다.
            </p>
            <Button onClick={() => setLocation('/groups')} className="w-full">
              그룹 목록으로 이동
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (isAccepted) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Card className="max-w-md w-full border-2 border-primary">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CheckCircle className="h-5 w-5 text-green-500" />
              초대 수락 완료
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground mb-4">
              프라이빗 그룹에 성공적으로 참여했습니다!
            </p>
            <Button onClick={() => setLocation('/groups')} className="w-full">
              그룹 목록으로 이동
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Card className="max-w-md w-full border-2 border-destructive">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <XCircle className="h-5 w-5 text-destructive" />
              초대 수락 실패
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground mb-4">{error}</p>
            <div className="space-y-2">
              <Button onClick={handleAcceptInvite} className="w-full" disabled={isLoading}>
                {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                다시 시도
              </Button>
              <Button
                variant="outline"
                onClick={() => setLocation('/groups')}
                className="w-full"
              >
                그룹 목록으로 이동
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="max-w-md w-full border-2 border-primary">
        <CardHeader>
          <CardTitle>프라이빗 그룹 초대</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground mb-6">
            프라이빗 그룹에 초대되었습니다. 수락하시겠습니까?
          </p>
          
          {!isAuthenticated ? (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground mb-4">
                초대를 수락하려면 먼저 로그인해주세요.
              </p>
              <Button onClick={() => {
                sessionStorage.setItem('redirect_after_login', `/invite/${token}`);
                setLocation('/login');
              }} className="w-full">
                로그인
              </Button>
            </div>
          ) : (
            <div className="space-y-2">
              <Button
                onClick={handleAcceptInvite}
                className="w-full"
                disabled={isLoading}
              >
                {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                초대 수락
              </Button>
              <Button
                variant="outline"
                onClick={() => setLocation('/groups')}
                className="w-full"
              >
                취소
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
