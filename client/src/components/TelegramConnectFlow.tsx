/**
 * Telegram Connect Flow Component
 * Phone/code/2FA auth flow for connecting a Telegram account.
 * Extracted from GroupSelection.tsx
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import { Loader2, Lock, Send } from 'lucide-react';
import { telegramApi, getApiErrorMessage } from '@/lib/api';

export interface TelegramConnectFlowProps {
  onConnectSuccess: () => void;
  onCancel: () => void;
}

export default function TelegramConnectFlow({ onConnectSuccess, onCancel }: TelegramConnectFlowProps) {
  const [step, setStep] = useState<'phone' | 'code' | '2fa'>('phone');
  const [phoneOrUsername, setPhoneOrUsername] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [phoneCodeHash, setPhoneCodeHash] = useState('');
  const [sendStatus, setSendStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [isLoading, setIsLoading] = useState(false);
  const [resendTimer, setResendTimer] = useState(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const phoneCodeHashRef = useRef('');
  const pendingCodeRef = useRef<string | null>(null);
  const isSubmitting = useRef(false);

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

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const doVerifyCode = useCallback(async (codeValue: string, hash: string) => {
    if (isSubmitting.current) return;
    isSubmitting.current = true;
    setIsLoading(true);
    try {
      await telegramApi.verifyCode({
        phone_or_username: phoneOrUsername,
        code: codeValue,
        phone_code_hash: hash,
      });
      onConnectSuccess();
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 403) {
        setStep('2fa');
        toast.info('2단계 인증이 필요합니다');
      } else if (axios.isAxiosError(error) && error.response?.status === 408) {
        setStep('phone');
        setCode('');
        setPhoneCodeHash('');
        phoneCodeHashRef.current = '';
        setSendStatus('idle');
        toast.error('세션이 만료되었습니다. 다시 시도해주세요');
      } else {
        toast.error(getApiErrorMessage(error, '코드 검증 실패'));
      }
    } finally {
      setIsLoading(false);
      isSubmitting.current = false;
    }
  }, [phoneOrUsername, onConnectSuccess]);

  const submitCode = useCallback(async (codeValue: string) => {
    const hash = phoneCodeHashRef.current;
    if (!hash) {
      pendingCodeRef.current = codeValue;
      return;
    }
    await doVerifyCode(codeValue, hash);
  }, [doVerifyCode]);

  const handleSendCode = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!phoneOrUsername.trim()) {
      toast.error('전화번호 또는 username을 입력해주세요');
      return;
    }

    setSendStatus('sending');
    setCode('');
    setStep('code');

    try {
      const response = await telegramApi.sendCode({ phone_or_username: phoneOrUsername });
      if (response.data.success) {
        const hash = response.data.phone_code_hash || '';
        phoneCodeHashRef.current = hash;
        setPhoneCodeHash(hash);
        setSendStatus('sent');
        startResendTimer();

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
      setSendStatus('error');
      toast.error(getApiErrorMessage(error, '코드 전송 중 오류가 발생했습니다'));
    }
  };

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
      await telegramApi.verify2FA({
        phone_or_username: phoneOrUsername,
        password,
        phone_code_hash: phoneCodeHash,
      });
      onConnectSuccess();
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
          <CardTitle className="text-2xl font-bold text-center">
            텔레그램 연결
          </CardTitle>
          <CardDescription className="text-center">
            그룹을 추가하기 위해 텔레그램 계정을 연결하세요
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
                  autoFocus
                />
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={onCancel}
                  disabled={isLoading}
                  className="flex-1 border-2 border-border"
                >
                  취소
                </Button>
                <Button
                  type="submit"
                  className="flex-1 border-2 border-border btn-pressed"
                  disabled={isLoading}
                >
                  {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                  코드 받기
                </Button>
              </div>
            </form>
          )}

          {step === 'code' && (
            <form onSubmit={(e) => { e.preventDefault(); submitCode(code); }} className="space-y-4">
              <div className="flex items-center gap-2 px-3 py-2 bg-muted rounded-md text-sm">
                <span className="font-medium flex-1 truncate">{phoneOrUsername}</span>
              </div>
              <div className="space-y-2">
                <Label htmlFor="code">인증 코드</Label>
                <Input
                  id="code"
                  type="text"
                  inputMode="numeric"
                  placeholder="12345"
                  value={code}
                  onChange={handleCodeChange}
                  className="border-2 border-border font-mono text-center text-2xl"
                  disabled={isLoading}
                  maxLength={5}
                  autoFocus
                />
              </div>
              {resendTimer > 0 && (
                <p className="text-xs text-center text-muted-foreground">
                  {resendTimer}초 후 재전송 가능
                </p>
              )}
              <Button
                type="submit"
                className="w-full border-2 border-border btn-pressed"
                disabled={isLoading || code.length < 5}
              >
                {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                확인
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
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={onCancel}
                  disabled={isLoading}
                  className="flex-1 border-2 border-border"
                >
                  취소
                </Button>
                <Button
                  type="submit"
                  className="flex-1 border-2 border-border btn-pressed"
                  disabled={isLoading}
                >
                  {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Lock className="mr-2 h-4 w-4" />}
                  확인
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
