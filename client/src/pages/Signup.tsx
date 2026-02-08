/**
 * Email Signup Page
 * Allows new users to create an account with just email and password (no Telegram required)
 */
import { useState } from 'react';
import { useLocation, Link } from 'wouter';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';
import { Loader2, Mail, Lock, User, ArrowLeft } from 'lucide-react';
import { authApi, getApiErrorMessage } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';

export default function Signup() {
  const [, setLocation] = useLocation();
  const { login } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [isLoading, setIsLoading] = useState(false);

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
      const response = await authApi.signupEmail({
        email,
        password,
        first_name: firstName || undefined,
        last_name: lastName || undefined,
      });

      // Login with returned tokens
      login(
        response.data.access_token,
        response.data.refresh_token,
        response.data.user
      );

      toast.success('회원가입 성공! 환영합니다 🎉');

      // Redirect to home
      setLocation('/');
    } catch (error) {
      toast.error(getApiErrorMessage(error, '회원가입 실패'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="flex items-center gap-2 mb-2">
            <Link href="/login">
              <Button variant="ghost" size="sm" className="gap-1">
                <ArrowLeft className="h-4 w-4" />
                로그인
              </Button>
            </Link>
          </div>
          <CardTitle className="text-3xl font-bold text-center">
            회원가입
          </CardTitle>
          <CardDescription className="text-center">
            이메일로 간편하게 가입하세요
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">이메일 주소 *</Label>
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
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">비밀번호 *</Label>
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
              <p className="text-xs text-muted-foreground">
                8자 이상 입력해주세요
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="confirm-password">비밀번호 확인 *</Label>
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

            <div className="border-t pt-4">
              <p className="text-sm font-medium mb-3 text-muted-foreground">
                선택사항 (나중에 추가 가능)
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="first-name">이름</Label>
                  <div className="relative">
                    <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="first-name"
                      type="text"
                      placeholder="홍"
                      value={firstName}
                      onChange={(e) => setFirstName(e.target.value)}
                      className="pl-10"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="last-name">성</Label>
                  <div className="relative">
                    <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="last-name"
                      type="text"
                      placeholder="길동"
                      value={lastName}
                      onChange={(e) => setLastName(e.target.value)}
                      className="pl-10"
                    />
                  </div>
                </div>
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
                  가입 중...
                </>
              ) : (
                '회원가입'
              )}
            </Button>
          </form>

          <div className="mt-6 text-center">
            <p className="text-sm text-muted-foreground">
              이미 계정이 있으신가요?{' '}
              <Link href="/login" className="text-primary hover:underline font-medium">
                로그인
              </Link>
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
