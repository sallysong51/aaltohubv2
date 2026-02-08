/**
 * Email Linking Page - Forces existing users to link email on next login
 * Blocking: User cannot proceed without linking email
 */
import { useState, useEffect } from 'react';
import { useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';
import { Loader2, Mail, Lock, AlertCircle } from 'lucide-react';
import { authApi, getApiErrorMessage } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';

export default function EmailLinking() {
  const [, setLocation] = useLocation();
  const { user, refreshUser } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [checkingStatus, setCheckingStatus] = useState(true);

  // Check if user actually needs linking (prevent direct URL access)
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const response = await authApi.getEmailLinkingStatus();
        if (!response.data.email_link_required) {
          // Already linked, redirect to home
          setLocation('/');
          return;
        }
      } catch (error) {
        toast.error('상태 확인 실패');
        console.error('Email linking status check failed:', error);
      } finally {
        setCheckingStatus(false);
      }
    };
    checkStatus();
  }, [setLocation]);

  const validateEmail = (email: string): boolean => {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validation
    if (!validateEmail(email)) {
      toast.error('올바른 이메일 주소를 입력해주세요');
      return;
    }

    if (password.length < 8) {
      toast.error('비밀번호는 최소 8자 이상이어야 합니다');
      return;
    }

    if (password !== confirmPassword) {
      toast.error('비밀번호가 일치하지 않습니다');
      return;
    }

    setIsLoading(true);
    try {
      await authApi.linkEmail({ email, password });
      toast.success('이메일이 성공적으로 등록되었습니다!');

      // Refresh user data
      await refreshUser();

      // Redirect to home
      setLocation('/');
    } catch (error) {
      toast.error(getApiErrorMessage(error, '이메일 등록 실패'));
    } finally {
      setIsLoading(false);
    }
  };

  if (checkingStatus) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-3xl font-bold text-center">
            이메일 등록 필수
          </CardTitle>
          <CardDescription className="text-center">
            계정 보안을 위해 이메일 주소를 등록해주세요
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-6 p-4 bg-blue-50 dark:bg-blue-950 rounded-md border-2 border-blue-200 dark:border-blue-800">
            <div className="flex items-start gap-2">
              <AlertCircle className="h-5 w-5 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" />
              <div className="text-sm text-blue-800 dark:text-blue-200">
                <p className="font-semibold mb-1">왜 이메일이 필요한가요?</p>
                <ul className="list-disc list-inside space-y-1 text-xs">
                  <li>텔레그램 계정 문제 시 복구 가능</li>
                  <li>다음 로그인부터 이메일 또는 텔레그램 선택 가능</li>
                  <li>보안 강화 및 계정 보호</li>
                </ul>
              </div>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">이메일 주소</Label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  id="email"
                  type="email"
                  placeholder="your.email@aalto.fi"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="pl-10"
                  autoFocus
                  required
                />
              </div>
              <p className="text-xs text-muted-foreground">
                이 이메일로 로그인할 수 있습니다
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">비밀번호</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  id="password"
                  type="password"
                  placeholder="최소 8자"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="pl-10"
                  minLength={8}
                  required
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="confirm-password">비밀번호 확인</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  id="confirm-password"
                  type="password"
                  placeholder="비밀번호 재입력"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="pl-10"
                  minLength={8}
                  required
                />
              </div>
            </div>

            <Button
              type="submit"
              className="w-full"
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  등록 중...
                </>
              ) : (
                '이메일 등록'
              )}
            </Button>
          </form>

          <div className="mt-4 text-center">
            <p className="text-xs text-muted-foreground">
              {user?.telegram_id ? (
                <>
                  현재 텔레그램 계정: <strong>@{user?.username || user?.phone_number}</strong>
                </>
              ) : (
                <>
                  이메일 전용 계정
                </>
              )}
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
