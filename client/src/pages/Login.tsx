import { useState, useCallback } from 'react';
import { useLocation, Link } from 'wouter';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import axios from 'axios';
import { authApi, getApiErrorMessage, AuthResponse } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';

export default function Login() {
  const [, setLocation] = useLocation();
  const { login } = useAuth();

  const [emailInput, setEmailInput] = useState('');
  const [emailPassword, setEmailPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleLoginSuccess = useCallback((data: AuthResponse) => {
    login(data.access_token, data.refresh_token, data.user);
    toast.success('로그인 성공!');
    const redirect = sessionStorage.getItem('redirect_after_login');
    if (redirect) {
      sessionStorage.removeItem('redirect_after_login');
      setLocation(redirect);
    } else {
      setLocation('/');
    }
  }, [login, setLocation]);

  const handleEmailLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      const response = await authApi.loginEmail({
        email: emailInput,
        password: emailPassword,
      });
      handleLoginSuccess(response.data);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        toast.error('이메일 또는 비밀번호가 올바르지 않습니다');
      } else if (axios.isAxiosError(error) && error.response?.status === 404) {
        toast.error('계정을 찾을 수 없습니다. 회원가입을 먼저 해주세요');
      } else {
        toast.error(getApiErrorMessage(error, '로그인 실패'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md refined-card">
        <CardHeader>
          <CardTitle className="text-4xl font-bold text-center">
            AaltoHub v2
          </CardTitle>
          <CardDescription className="text-center">
            이메일로 로그인하세요
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleEmailLogin} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email-input">이메일</Label>
              <Input
                id="email-input"
                type="email"
                placeholder="your.email@aalto.fi"
                value={emailInput}
                onChange={(e) => setEmailInput(e.target.value)}
                autoFocus
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password-input">비밀번호</Label>
              <Input
                id="password-input"
                type="password"
                placeholder="••••••••"
                value={emailPassword}
                onChange={(e) => setEmailPassword(e.target.value)}
                required
              />
            </div>
            <Button
              type="submit"
              className="w-full btn-pressed"
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  로그인 중...
                </>
              ) : (
                '로그인'
              )}
            </Button>
            <p className="text-xs text-center text-muted-foreground mt-4">
              계정이 없으신가요?{' '}
              <Link href="/signup" className="text-primary hover:underline font-medium">
                회원가입
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
