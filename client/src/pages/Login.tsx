/**
 * Design Philosophy: Telegram-Native Brutalism
 * - Thick black borders (4px)
 * - Hard shadows (4px offset, no blur)
 * - Telegram Blue primary color
 * - Space Grotesk for headings
 * - Optimistic UI: code input appears immediately (#1, #8, #9, #10)
 */
import { useState, useRef, useCallback, useEffect } from 'react';
import { useLocation, Link } from 'wouter';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';
import { Loader2, Send, Lock, Check, AlertCircle } from 'lucide-react';
import axios from 'axios';
import { authApi, getApiErrorMessage, AuthResponse } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';

export default function Login() {
  const [, setLocation] = useLocation();
  const { login } = useAuth();

  // Login mode: email or telegram
  const [loginMode, setLoginMode] = useState<'email' | 'telegram'>('email');

  // Email login state
  const [emailInput, setEmailInput] = useState('');
  const [emailPassword, setEmailPassword] = useState('');

  // Telegram login state
  const [step, setStep] = useState<'phone' | 'code' | '2fa'>('phone');
  const [phoneOrUsername, setPhoneOrUsername] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [phoneCodeHash, setPhoneCodeHash] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // Optimistic UI: track code send status separately from isLoading (#1, #9)
  const [sendStatus, setSendStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');

  // Countdown timer for resend code (60 seconds)
  const [resendTimer, setResendTimer] = useState(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  // Refs for cross-async-boundary communication (#8)
  const phoneCodeHashRef = useRef('');
  const pendingCodeRef = useRef<string | null>(null);
  const sendCancelledRef = useRef(false);
  const isSubmitting = useRef(false);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  // Start countdown timer
  const startResendTimer = useCallback(() => {
    setResendTimer(60);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setResendTimer((prev) => {
        if (prev <= 1) {
          if (timerRef.current) clearInterval(timerRef.current);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, []);

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

  // Email login handler
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
        toast.error('계정을 찾을 수 없습니다. 먼저 텔레그램으로 로그인해주세요');
      } else {
        toast.error(getApiErrorMessage(error, '로그인 실패'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  // Auto-format phone number input
  const handlePhoneChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    let value = e.target.value;
    if (value.length > 0 && /^\d/.test(value) && !value.startsWith('+')) {
      value = '+' + value;
    }
    setPhoneOrUsername(value);
  };

  // Validate phone number or username format
  const validateInput = (input: string): { isValid: boolean; message?: string } => {
    const trimmed = input.trim();
    if (!trimmed) return { isValid: false, message: '전화번호 또는 username을 입력해주세요' };
    if (trimmed.startsWith('@') || /^[a-zA-Z][a-zA-Z0-9_]{4,}$/.test(trimmed)) return { isValid: true };
    if (trimmed.startsWith('+')) {
      if (!/^\+\d{10,15}$/.test(trimmed)) return { isValid: false, message: '올바른 국제번호 형식이 아닙니다 (예: +358...)' };
      return { isValid: true };
    }
    if (/^\d+$/.test(trimmed)) return { isValid: false, message: '국제번호는 + 기호로 시작해야 합니다 (예: +358...)' };
    return { isValid: false, message: '올바른 전화번호 또는 username 형식이 아닙니다' };
  };

  // Core verify function — takes hash explicitly to avoid stale closure issues
  const doVerifyCode = useCallback(async (codeValue: string, hash: string) => {
    if (isSubmitting.current) return;
    isSubmitting.current = true;
    setIsLoading(true);
    try {
      const response = await authApi.verifyCode({
        phone_or_username: phoneOrUsername,
        code: codeValue,
        phone_code_hash: hash,
      });
      handleLoginSuccess(response.data);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 403 && error.response?.data?.detail?.includes('Two-factor')) {
        setStep('2fa');
        toast.info('2단계 인증이 필요합니다');
      } else if (axios.isAxiosError(error) && error.response?.status === 408) {
        setStep('phone');
        setCode('');
        setPhoneCodeHash('');
        phoneCodeHashRef.current = '';
        setSendStatus('idle');
        pendingCodeRef.current = null;
        setResendTimer(0);
        if (timerRef.current) clearInterval(timerRef.current);
        toast.error(getApiErrorMessage(error, '세션이 만료되었습니다. 다시 시도해주세요'));
      } else if (axios.isAxiosError(error) && error.response?.status === 503) {
        // DB down / degraded mode — do NOT reset auth flow, user can retry
        toast.error('서버 점검 중입니다. 잠시 후 다시 시도해주세요.');
      } else if (axios.isAxiosError(error) && error.response?.status === 429) {
        // Rate limited — show backend's detail message (includes wait time)
        toast.error(error.response?.data?.detail || '너무 많은 시도입니다. 잠시 후 다시 시도해주세요.');
      } else {
        toast.error(getApiErrorMessage(error, '코드 검증 실패'));
      }
    } finally {
      setIsLoading(false);
      isSubmitting.current = false;
    }
  }, [phoneOrUsername, handleLoginSuccess]);

  // Submit code — queues if hash not yet available (#8)
  const submitCode = useCallback(async (codeValue: string) => {
    const hash = phoneCodeHashRef.current;
    if (!hash) {
      pendingCodeRef.current = codeValue;
      return;
    }
    await doVerifyCode(codeValue, hash);
  }, [doVerifyCode]);

  // Send code with optimistic UI transition (#1)
  const handleSendCode = async (e?: React.FormEvent, isResend: boolean = false) => {
    if (e) e.preventDefault();
    const validation = validateInput(phoneOrUsername);
    if (!validation.isValid) {
      toast.error(validation.message || '입력값을 확인해주세요');
      return;
    }

    // OPTIMISTIC: transition to code step immediately — don't wait for API
    sendCancelledRef.current = false;
    setSendStatus('sending');
    setCode('');
    pendingCodeRef.current = null;
    phoneCodeHashRef.current = '';
    setPhoneCodeHash('');
    if (!isResend) {
      setStep('code');
    }

    try {
      const response = await authApi.sendCode({ phone_or_username: phoneOrUsername });
      if (sendCancelledRef.current) return;

      if (response.data.success) {
        const hash = response.data.phone_code_hash || '';
        phoneCodeHashRef.current = hash;
        setPhoneCodeHash(hash);
        setSendStatus('sent');
        startResendTimer();

        // Auto-submit pending code if user already typed it (#8)
        if (pendingCodeRef.current) {
          const pending = pendingCodeRef.current;
          pendingCodeRef.current = null;
          await doVerifyCode(pending, hash);
        }
      } else {
        setSendStatus('error');
        toast.error(response.data.message || '코드 전송 실패');
      }
    } catch (error) {
      if (sendCancelledRef.current) return;
      setSendStatus('error');
      toast.error(getApiErrorMessage(error, '코드 전송 중 오류가 발생했습니다'));
    }
  };

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

  const resetToPhone = () => {
    sendCancelledRef.current = true;
    setStep('phone');
    setCode('');
    setSendStatus('idle');
    setPhoneCodeHash('');
    phoneCodeHashRef.current = '';
    pendingCodeRef.current = null;
    setResendTimer(0);
    if (timerRef.current) clearInterval(timerRef.current);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md refined-card">
        {/* Login mode tabs */}
        <div className="flex border-b-2 border-border">
          <button
            type="button"
            className={`flex-1 py-3 font-semibold transition-colors ${
              loginMode === 'email'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-muted/80'
            }`}
            onClick={() => setLoginMode('email')}
          >
            이메일 로그인
          </button>
          <button
            type="button"
            className={`flex-1 py-3 font-semibold transition-colors ${
              loginMode === 'telegram'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-muted/80'
            }`}
            onClick={() => setLoginMode('telegram')}
          >
            텔레그램 로그인
          </button>
        </div>

        <CardHeader>
          <CardTitle className="text-4xl font-bold text-center">
            AaltoHub v2
          </CardTitle>
          <CardDescription className="text-center">
            {loginMode === 'email' ? '이메일로 로그인하세요' : '텔레그램으로 로그인하세요'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loginMode === 'email' ? (
            // Email login form
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
          ) : (
            // Telegram login flow (existing)
            <>
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
                  autoFocus
                />
                <p className="text-xs text-muted-foreground">
                  국제번호 형식 (+358...)으로 입력하거나 텔레그램 username을 입력하세요
                </p>
              </div>
              <Button
                type="submit"
                className="w-full btn-pressed"
              >
                <Send className="mr-2 h-4 w-4" />
                인증 코드 받기
              </Button>
            </form>
          )}

          {step === 'code' && (
            <form onSubmit={handleVerifyCode} className="space-y-4">
              {/* Locked phone display */}
              <div className="flex items-center gap-2 px-3 py-2 bg-muted rounded-md text-sm">
                <span className="font-medium flex-1 truncate">{phoneOrUsername}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs shrink-0"
                  onClick={resetToPhone}
                  disabled={isLoading}
                >
                  변경
                </Button>
              </div>

              {/* Send status indicator (#9) */}
              <div className="flex items-center justify-center gap-2 min-h-[28px]">
                {sendStatus === 'sending' && (
                  <div className="flex items-center gap-2 text-sm text-blue-600 dark:text-blue-400">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span>텔레그램으로 인증 코드를 보내는 중...</span>
                  </div>
                )}
                {sendStatus === 'sent' && (
                  <div className="flex items-center gap-2 text-sm text-green-600 dark:text-green-400">
                    <Check className="h-4 w-4" />
                    <span>인증 코드가 전송되었습니다</span>
                  </div>
                )}
                {sendStatus === 'error' && (
                  <div className="flex items-center gap-2 text-sm text-destructive">
                    <AlertCircle className="h-4 w-4" />
                    <span>코드 전송 실패</span>
                    <Button
                      type="button"
                      variant="link"
                      size="sm"
                      className="h-auto p-0 text-sm"
                      onClick={() => handleSendCode(undefined, true)}
                    >
                      재시도
                    </Button>
                  </div>
                )}
              </div>

              {/* Code input — visible immediately (#1, #10) */}
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
                  {sendStatus === 'sending'
                    ? '코드가 곧 도착합니다 — 미리 입력할 수 있습니다'
                    : '텔레그램 앱에서 받은 5자리 코드를 입력하세요'}
                </p>
              </div>

              {/* Resend */}
              {sendStatus !== 'sending' && (
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
              )}

              <Button
                type="submit"
                className="w-full btn-pressed"
                disabled={isLoading || code.length < 5}
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
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
