/**
 * Design Philosophy: Telegram-Native Brutalism
 * - Thick black borders (4px)
 * - Hard shadows (4px offset, no blur)
 * - Telegram Blue primary color
 * - Space Grotesk for headings
 * - Immediate, clear feedback
 */
import { useState, useRef, useCallback, useEffect } from 'react';
import { useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';
import { Loader2, Send, Lock } from 'lucide-react';
import axios from 'axios';
import { authApi, getApiErrorMessage, AuthResponse } from '@/lib/api';
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

  // Countdown timer for resend code (60 seconds)
  const [resendTimer, setResendTimer] = useState(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  // Ref to prevent double-submit from auto-submit + form submit
  const isSubmitting = useRef(false);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, []);

  // Start countdown timer
  const startResendTimer = useCallback(() => {
    setResendTimer(60);
    if (timerRef.current) {
      clearInterval(timerRef.current);
    }
    timerRef.current = setInterval(() => {
      setResendTimer((prev) => {
        if (prev <= 1) {
          if (timerRef.current) {
            clearInterval(timerRef.current);
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, []);

  const handleLoginSuccess = useCallback((data: AuthResponse) => {
    login(data.access_token, data.refresh_token, data.user);
    toast.success('로그인 성공!');
    // Check for stored redirect (e.g., from invite flow)
    const redirect = sessionStorage.getItem('redirect_after_login');
    if (redirect) {
      sessionStorage.removeItem('redirect_after_login');
      setLocation(redirect);
    } else {
      setLocation(data.user.role === 'admin' ? '/admin' : '/feed');
    }
  }, [login, setLocation]);

  // Auto-format phone number input
  const handlePhoneChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    let value = e.target.value;

    // If user starts typing digits without +, auto-add +
    if (value.length > 0 && /^\d/.test(value) && !value.startsWith('+')) {
      value = '+' + value;
    }

    setPhoneOrUsername(value);
  };

  // Validate phone number or username format
  const validateInput = (input: string): { isValid: boolean; message?: string } => {
    const trimmed = input.trim();

    if (!trimmed) {
      return { isValid: false, message: '전화번호 또는 username을 입력해주세요' };
    }

    // Username format (@username or username)
    if (trimmed.startsWith('@') || /^[a-zA-Z][a-zA-Z0-9_]{4,}$/.test(trimmed)) {
      return { isValid: true };
    }

    // Phone number format (+358... or 358... or starts with +)
    if (trimmed.startsWith('+')) {
      if (!/^\+\d{10,15}$/.test(trimmed)) {
        return { isValid: false, message: '올바른 국제번호 형식이 아닙니다 (예: +358...)'};
      }
      return { isValid: true };
    }

    // If it's all digits but doesn't start with +, suggest adding +
    if (/^\d+$/.test(trimmed)) {
      return { isValid: false, message: '국제번호는 + 기호로 시작해야 합니다 (예: +358...)' };
    }

    return { isValid: false, message: '올바른 전화번호 또는 username 형식이 아닙니다' };
  };

  const handleSendCode = async (e?: React.FormEvent, isResend: boolean = false) => {
    if (e) e.preventDefault();

    const validation = validateInput(phoneOrUsername);
    if (!validation.isValid) {
      toast.error(validation.message || '입력값을 확인해주세요');
      return;
    }

    setIsLoading(true);
    try {
      const response = await authApi.sendCode({ phone_or_username: phoneOrUsername });

      if (response.data.success) {
        setPhoneCodeHash(response.data.phone_code_hash || '');
        setStep('code');
        startResendTimer(); // Start 60s countdown
        toast.success(isResend ? '인증 코드가 재전송되었습니다' : '인증 코드가 텔레그램으로 전송되었습니다');
      } else {
        toast.error(response.data.message || '코드 전송 실패');
      }
    } catch (error) {
      toast.error(getApiErrorMessage(error, '코드 전송 중 오류가 발생했습니다'));
    } finally {
      setIsLoading(false);
    }
  };

  const submitCode = useCallback(async (codeValue: string) => {
    if (isSubmitting.current || isLoading) return;
    isSubmitting.current = true;
    setIsLoading(true);

    try {
      const response = await authApi.verifyCode({
        phone_or_username: phoneOrUsername,
        code: codeValue,
        phone_code_hash: phoneCodeHash,
      });
      handleLoginSuccess(response.data);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 403 && error.response?.data?.detail?.includes('Two-factor')) {
        setStep('2fa');
        toast.info('2단계 인증이 필요합니다');
      } else {
        toast.error(getApiErrorMessage(error, '코드 검증 실패'));
      }
    } finally {
      setIsLoading(false);
      isSubmitting.current = false;
    }
  }, [phoneOrUsername, phoneCodeHash, isLoading, handleLoginSuccess]);

  const handleVerifyCode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) {
      toast.error('인증 코드를 입력해주세요');
      return;
    }
    await submitCode(code);
  };

  // Auto-submit when 5 digits entered
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
      const response = await authApi.verify2FA({
        phone_or_username: phoneOrUsername,
        password,
        phone_code_hash: phoneCodeHash,
      });
      handleLoginSuccess(response.data);
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
          <CardTitle className="text-4xl font-bold text-center">
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
                  onChange={handlePhoneChange}
                  disabled={isLoading}
                  autoFocus
                />
                <p className="text-xs text-muted-foreground">
                  국제번호 형식 (+358...)으로 입력하거나 텔레그램 username을 입력하세요
                </p>
              </div>
              <Button
                type="submit"
                className="w-full btn-pressed"
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
                  inputMode="numeric"
                  placeholder="12345"
                  value={code}
                  onChange={handleCodeChange}
                  className="border-2 border-border font-mono text-center text-2xl tracking-widest"
                  disabled={isLoading}
                  maxLength={5}
                  autoFocus
                />
                <p className="text-xs text-muted-foreground">
                  텔레그램 앱에서 받은 5자리 코드를 입력하세요
                </p>
              </div>

              {/* Resend Code Button with Timer */}
              <div className="flex items-center justify-center">
                {resendTimer > 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {resendTimer}초 후 재전송 가능
                  </p>
                ) : (
                  <Button
                    type="button"
                    variant="link"
                    className="text-sm"
                    onClick={() => handleSendCode(undefined, true)}
                    disabled={isLoading}
                  >
                    코드를 받지 못하셨나요? 재전송
                  </Button>
                )}
              </div>

              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="flex-1"
                  onClick={() => {
                    setStep('phone');
                    setCode('');
                    setResendTimer(0);
                    if (timerRef.current) clearInterval(timerRef.current);
                  }}
                  disabled={isLoading}
                >
                  뒤로
                </Button>
                <Button
                  type="submit"
                  className="flex-1 btn-pressed"
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
