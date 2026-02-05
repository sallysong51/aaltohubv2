/**
 * Design Philosophy: Telegram-Native Brutalism
 * - Thick black borders (4px)
 * - Hard shadows (4px offset, no blur)
 * - Telegram Blue primary color
 * - Space Grotesk for headings
 * - Immediate, clear feedback
 */
import { useState } from 'react';
import { useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';
import { Loader2, Send, Lock } from 'lucide-react';
import { authApi } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';

export default function Login() {
  const [, setLocation] = useLocation();
  const { login } = useAuth();
  
  const [step, setStep] = useState<'phone' | 'code' | '2fa'>('phone');
  const [phoneOrUsername, setPhoneOrUsername] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [phoneCodeHash, setPhoneCodeHash] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSendCode = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!phoneOrUsername.trim()) {
      toast.error('전화번호 또는 username을 입력해주세요');
      return;
    }

    setIsLoading(true);
    try {
      const response = await authApi.sendCode({ phone_or_username: phoneOrUsername });
      
      if (response.data.success) {
        setPhoneCodeHash(response.data.phone_code_hash || '');
        setStep('code');
        toast.success('인증 코드가 텔레그램으로 전송되었습니다');
      } else {
        toast.error(response.data.message || '코드 전송 실패');
      }
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '코드 전송 중 오류가 발생했습니다');
    } finally {
      setIsLoading(false);
    }
  };

  const handleVerifyCode = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!code.trim()) {
      toast.error('인증 코드를 입력해주세요');
      return;
    }

    setIsLoading(true);
    try {
      const response = await authApi.verifyCode({
        phone_or_username: phoneOrUsername,
        code,
        phone_code_hash: phoneCodeHash,
      });

      // Login successful
      login(response.data.access_token, response.data.refresh_token, response.data.user);
      toast.success('로그인 성공!');
      
      // Redirect based on role
      if (response.data.user.role === 'admin') {
        setLocation('/admin');
      } else {
        setLocation('/groups');
      }
    } catch (error: any) {
      if (error.response?.status === 403 && error.response?.data?.detail?.includes('Two-factor')) {
        setStep('2fa');
        toast.info('2단계 인증이 필요합니다');
      } else {
        toast.error(error.response?.data?.detail || '코드 검증 실패');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleVerify2FA = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!password.trim()) {
      toast.error('2FA 비밀번호를 입력해주세요');
      return;
    }

    setIsLoading(true);
    try {
      const response = await authApi.verify2FA({
        phone_or_username: phoneOrUsername,
        password,
        phone_code_hash: phoneCodeHash,
      });

      // Login successful
      login(response.data.access_token, response.data.refresh_token, response.data.user);
      toast.success('로그인 성공!');
      
      // Redirect based on role
      if (response.data.user.role === 'admin') {
        setLocation('/admin');
      } else {
        setLocation('/groups');
      }
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '2FA 검증 실패');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md brutalist-card border-4">
        <CardHeader>
          <CardTitle className="text-3xl font-bold text-center">
            AaltoHub v2
          </CardTitle>
          <CardDescription className="text-center">
            텔레그램으로 로그인하세요
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
                  className="border-2 border-border"
                  disabled={isLoading}
                />
                <p className="text-xs text-muted-foreground">
                  국제번호 형식 (+358...)으로 입력하거나 텔레그램 username을 입력하세요
                </p>
              </div>
              <Button
                type="submit"
                className="w-full border-2 border-border btn-pressed"
                disabled={isLoading}
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    전송 중...
                  </>
                ) : (
                  <>
                    <Send className="mr-2 h-4 w-4" />
                    인증 코드 받기
                  </>
                )}
              </Button>
            </form>
          )}

          {step === 'code' && (
            <form onSubmit={handleVerifyCode} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="code">인증 코드</Label>
                <Input
                  id="code"
                  type="text"
                  placeholder="12345"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  className="border-2 border-border font-mono text-center text-2xl tracking-widest"
                  disabled={isLoading}
                  maxLength={5}
                  autoFocus
                />
                <p className="text-xs text-muted-foreground">
                  텔레그램 앱에서 받은 5자리 코드를 입력하세요
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="flex-1 border-2 border-border"
                  onClick={() => {
                    setStep('phone');
                    setCode('');
                  }}
                  disabled={isLoading}
                >
                  뒤로
                </Button>
                <Button
                  type="submit"
                  className="flex-1 border-2 border-border btn-pressed"
                  disabled={isLoading}
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      확인 중...
                    </>
                  ) : (
                    '확인'
                  )}
                </Button>
              </div>
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
                  className="border-2 border-border"
                  disabled={isLoading}
                  autoFocus
                />
                <p className="text-xs text-muted-foreground">
                  텔레그램 2단계 인증 비밀번호를 입력하세요
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="flex-1 border-2 border-border"
                  onClick={() => {
                    setStep('code');
                    setPassword('');
                  }}
                  disabled={isLoading}
                >
                  뒤로
                </Button>
                <Button
                  type="submit"
                  className="flex-1 border-2 border-border btn-pressed"
                  disabled={isLoading}
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      확인 중...
                    </>
                  ) : (
                    <>
                      <Lock className="mr-2 h-4 w-4" />
                      확인
                    </>
                  )}
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
