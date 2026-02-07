/**
 * Design Philosophy: Telegram-Native Brutalism
 * - Group cards with thick borders
 * - Clear disabled state for registered groups
 * - Public/Private toggle with visual hierarchy
 */
import { useState, useEffect } from 'react';
import { useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Badge } from '@/components/ui/badge';
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { toast } from 'sonner';
import { Loader2, Users, Lock, Globe, ChevronRight, AlertCircle, Info } from 'lucide-react';
import { groupsApi, TelegramGroup, getApiErrorMessage } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import ProtectedRoute from '@/components/ProtectedRoute';

function GroupSelectionContent() {
  const [, setLocation] = useLocation();
  const { user } = useAuth();
  
  const [step, setStep] = useState<'select' | 'visibility'>('select');
  const [groups, setGroups] = useState<TelegramGroup[]>([]);
  const [selectedGroups, setSelectedGroups] = useState<Set<number>>(new Set());
  const [groupVisibility, setGroupVisibility] = useState<Map<number, 'public' | 'private'>>(new Map());
  const [isLoading, setIsLoading] = useState(true);
  const [isRegistering, setIsRegistering] = useState(false);

  useEffect(() => {
    loadGroups();
  }, []);

  const loadGroups = async () => {
    setIsLoading(true);
    try {
      const response = await groupsApi.getMyTelegramGroups();
      setGroups(response.data);
      
      // Initialize all groups as public by default
      const visibilityMap = new Map<number, 'public' | 'private'>();
      response.data.forEach(group => {
        if (!group.is_registered) {
          visibilityMap.set(group.telegram_id, 'public');
        }
      });
      setGroupVisibility(visibilityMap);
    } catch (error) {
      toast.error(getApiErrorMessage(error, '그룹 목록을 불러오는데 실패했습니다'));
    } finally {
      setIsLoading(false);
    }
  };

  const toggleGroupSelection = (telegramId: number) => {
    const newSelected = new Set(selectedGroups);
    if (newSelected.has(telegramId)) {
      newSelected.delete(telegramId);
    } else {
      newSelected.add(telegramId);
    }
    setSelectedGroups(newSelected);
  };

  const selectAllGroups = () => {
    const allUnregisteredIds = unregisteredGroups.map(g => g.telegram_id);
    setSelectedGroups(new Set(allUnregisteredIds));
    toast.success(`${allUnregisteredIds.length}개 그룹이 모두 선택되었습니다`);
  };

  const deselectAllGroups = () => {
    setSelectedGroups(new Set());
    toast.info('선택이 모두 해제되었습니다');
  };

  const setAllVisibility = (visibility: 'public' | 'private') => {
    const newMap = new Map(groupVisibility);
    selectedGroups.forEach(groupId => {
      newMap.set(groupId, visibility);
    });
    setGroupVisibility(newMap);
    toast.success(`모든 그룹이 ${visibility === 'public' ? '공개' : '비공개'}로 설정되었습니다`);
  };

  const handleNext = () => {
    if (selectedGroups.size === 0) {
      toast.error('최소 하나의 그룹을 선택해주세요');
      return;
    }
    setStep('visibility');
  };

  const handleRegister = async () => {
    setIsRegistering(true);
    try {
      const groupsToRegister = groups
        .filter(g => selectedGroups.has(g.telegram_id))
        .map(g => ({
          telegram_id: g.telegram_id,
          title: g.title,
          username: g.username,
          member_count: g.member_count,
          group_type: g.group_type,
          visibility: groupVisibility.get(g.telegram_id) || 'public',
        }));

      const response = await groupsApi.registerGroups({ groups: groupsToRegister });

      if (response.data.success) {
        const publicCount = groupsToRegister.filter(g => g.visibility === 'public').length;
        const privateCount = groupsToRegister.filter(g => g.visibility === 'private').length;

        toast.success(
          `${response.data.registered_groups.length}개 그룹 등록 완료`,
          {
            description: publicCount > 0 && privateCount > 0
              ? `공개: ${publicCount}개, 비공개: ${privateCount}개`
              : publicCount > 0
              ? `모두 공개로 등록되었습니다`
              : `모두 비공개로 등록되었습니다`,
          }
        );

        // Redirect based on role
        setTimeout(() => {
          if (user?.role === 'admin') {
            setLocation('/admin');
          } else {
            setLocation('/groups');
          }
        }, 1500);
      }
    } catch (error) {
      toast.error(getApiErrorMessage(error, '그룹 등록에 실패했습니다'));
    } finally {
      setIsRegistering(false);
    }
  };

  const unregisteredGroups = groups.filter(g => !g.is_registered);
  const registeredGroups = groups.filter(g => g.is_registered);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background p-4">
      <div className="container max-w-4xl mx-auto py-8">
        {step === 'select' && (
          <>
            <div className="mb-8">
              <h1 className="text-4xl font-bold mb-2">그룹 선택</h1>
              <p className="text-muted-foreground">
                등록할 텔레그램 그룹을 선택하세요
              </p>
              {unregisteredGroups.length > 0 && (
                <div className="mt-4 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Badge variant={selectedGroups.size > 0 ? "default" : "outline"} className="border-2">
                      {selectedGroups.size}개 선택됨
                    </Badge>
                    <span className="text-sm text-muted-foreground">
                      / 총 {unregisteredGroups.length}개 그룹
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={selectAllGroups}
                      disabled={selectedGroups.size === unregisteredGroups.length}
                      className="border-2"
                    >
                      모두 선택
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={deselectAllGroups}
                      disabled={selectedGroups.size === 0}
                      className="border-2"
                    >
                      선택 해제
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {unregisteredGroups.length === 0 ? (
              <Card className="refined-card">
                <CardContent className="pt-6">
                  <div className="text-center py-8">
                    {registeredGroups.length > 0 ? (
                      <>
                        <Users className="h-12 w-12 mx-auto mb-4 text-primary" />
                        <p className="text-lg font-medium mb-2">모든 그룹이 등록되었습니다</p>
                        <p className="text-sm text-muted-foreground mb-4">
                          텔레그램 그룹 {registeredGroups.length}개가 모두 AaltoHub에 등록되어 있습니다
                        </p>
                        <Button
                          onClick={() => setLocation(user?.role === 'admin' ? '/admin' : '/groups')}
                          className="border-2 border-border btn-pressed"
                        >
                          그룹 관리로 이동
                        </Button>
                      </>
                    ) : (
                      <>
                        <AlertCircle className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                        <p className="text-lg font-medium mb-2">가입된 그룹이 없습니다</p>
                        <p className="text-sm text-muted-foreground mb-4">
                          텔레그램에서 그룹에 가입한 후 다시 시도해주세요
                        </p>
                        <Button
                          onClick={loadGroups}
                          variant="outline"
                          className="border-2 border-border mr-2"
                        >
                          새로고침
                        </Button>
                        <Button
                          onClick={() => setLocation(user?.role === 'admin' ? '/admin' : '/groups')}
                          className="border-2 border-border btn-pressed"
                        >
                          계속하기
                        </Button>
                      </>
                    )}
                  </div>
                </CardContent>
              </Card>
            ) : (
              <>
                <div className="space-y-4 mb-6">
                  {unregisteredGroups.map((group) => (
                    <Card
                      key={group.telegram_id}
                      className={`refined-card cursor-pointer transition-all ${
                        selectedGroups.has(group.telegram_id)
                          ? 'border-primary'
                          : 'border-border'
                      }`}
                      onClick={() => toggleGroupSelection(group.telegram_id)}
                    >
                      <CardContent className="p-4">
                        <div className="flex items-start gap-4">
                          <Checkbox
                            checked={selectedGroups.has(group.telegram_id)}
                            onCheckedChange={() => toggleGroupSelection(group.telegram_id)}
                            className="mt-1"
                          />
                          <Avatar className="size-14 rounded-lg border-2 border-border shrink-0">
                            {group.photo_url && (
                              <AvatarImage src={group.photo_url} alt={group.title} />
                            )}
                            <AvatarFallback className="rounded-lg font-bold text-lg bg-accent">
                              {group.title.charAt(0).toUpperCase()}
                            </AvatarFallback>
                          </Avatar>
                          <div className="flex-1 min-w-0">
                            <h3 className="font-bold text-lg truncate">{group.title}</h3>
                            {group.username && (
                              <p className="text-sm text-muted-foreground truncate">@{group.username}</p>
                            )}
                            <div className="flex items-center gap-4 mt-2">
                              {group.member_count && (
                                <div className="flex items-center gap-1 text-sm text-muted-foreground">
                                  <Users className="h-4 w-4" />
                                  {group.member_count.toLocaleString()}명
                                </div>
                              )}
                              <Badge variant="outline" className="border-2">
                                {group.group_type === 'channel' ? '채널' :
                                 group.group_type === 'supergroup' ? '슈퍼그룹' : '그룹'}
                              </Badge>
                            </div>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>

                {registeredGroups.length > 0 && (
                  <div className="mb-6">
                    <h2 className="text-xl font-bold mb-4">이미 등록된 그룹</h2>
                    <div className="space-y-4">
                      {registeredGroups.map((group) => (
                        <TooltipProvider key={group.telegram_id}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Card
                                className="refined-card opacity-50 cursor-not-allowed"
                              >
                                <CardContent className="p-4">
                                  <div className="flex items-start gap-4">
                                    <Checkbox checked={false} disabled className="mt-1" />
                                    <Avatar className="size-14 rounded-lg border-2 border-border shrink-0 opacity-50">
                                      {group.photo_url && (
                                        <AvatarImage src={group.photo_url} alt={group.title} />
                                      )}
                                      <AvatarFallback className="rounded-lg font-bold text-lg bg-accent">
                                        {group.title.charAt(0).toUpperCase()}
                                      </AvatarFallback>
                                    </Avatar>
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center gap-2">
                                        <h3 className="font-bold text-lg truncate">{group.title}</h3>
                                        <Info className="h-4 w-4 text-muted-foreground shrink-0" />
                                      </div>
                                      {group.username && (
                                        <p className="text-sm text-muted-foreground truncate">@{group.username}</p>
                                      )}
                                      <Badge variant="secondary" className="mt-2">
                                        이미 등록됨
                                      </Badge>
                                    </div>
                                  </div>
                                </CardContent>
                              </Card>
                            </TooltipTrigger>
                            <TooltipContent side="top" className="border-2 border-border">
                              <p className="font-medium">이미 등록된 그룹입니다</p>
                              <p className="text-xs text-muted-foreground mt-1">
                                이 그룹은 이미 AaltoHub에 등록되어 있어 선택할 수 없습니다
                              </p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex gap-4">
                  <Button
                    variant="outline"
                    onClick={() => setLocation('/groups')}
                    disabled={isRegistering}
                    className="border-2 border-border"
                    size="lg"
                  >
                    취소
                  </Button>
                  <Button
                    onClick={handleNext}
                    disabled={selectedGroups.size === 0 || isRegistering}
                    className="flex-1 border-2 border-border btn-pressed"
                    size="lg"
                  >
                    다음
                    <ChevronRight className="ml-2 h-5 w-5" />
                  </Button>
                </div>
              </>
            )}
          </>
        )}

        {step === 'visibility' && (
          <>
            <div className="mb-8">
              <h1 className="text-4xl font-bold mb-2">공개 여부 설정</h1>
              <p className="text-muted-foreground">
                각 그룹의 공개 여부를 선택하세요 (기본값: 공개)
              </p>
              {selectedGroups.size > 1 && (
                <div className="mt-4 flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setAllVisibility('public')}
                    className="border-2"
                  >
                    <Globe className="mr-2 h-4 w-4" />
                    모두 공개로 설정
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setAllVisibility('private')}
                    className="border-2"
                  >
                    <Lock className="mr-2 h-4 w-4" />
                    모두 비공개로 설정
                  </Button>
                </div>
              )}
            </div>

            <Card className="refined-card mb-6">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <AlertCircle className="h-5 w-5" />
                  안내사항
                </CardTitle>
                <CardDescription>
                  선택한 그룹은 기본적으로 공개(Public)로 설정됩니다. 다른 학생들이 이벤트 정보를 볼 수 있도록 공개를 권장합니다. 
                  비공개로 변경하려면 각 그룹의 설정을 개별적으로 변경해주세요.
                </CardDescription>
              </CardHeader>
            </Card>

            <div className="space-y-4 mb-6">
              {groups
                .filter(g => selectedGroups.has(g.telegram_id))
                .map((group) => (
                  <Card key={group.telegram_id} className="refined-card">
                    <CardContent className="p-6">
                      <h3 className="font-bold text-lg mb-4">{group.title}</h3>
                      <RadioGroup
                        value={groupVisibility.get(group.telegram_id)}
                        onValueChange={(value: 'public' | 'private') => {
                          const newMap = new Map(groupVisibility);
                          newMap.set(group.telegram_id, value);
                          setGroupVisibility(newMap);
                        }}
                      >
                        <div className="space-y-4">
                          <div className="flex items-start space-x-3 p-4 border-2 border-border rounded-lg bg-accent/10">
                            <RadioGroupItem value="public" id={`public-${group.telegram_id}`} />
                            <div className="flex-1">
                              <Label
                                htmlFor={`public-${group.telegram_id}`}
                                className="flex items-center gap-2 font-bold cursor-pointer"
                              >
                                <Globe className="h-4 w-4" />
                                퍼블릭 (Public)
                                <Badge variant="default" className="ml-2">권장</Badge>
                              </Label>
                              <p className="text-sm text-muted-foreground mt-1">
                                이 그룹의 이벤트 정보가 다른 사용자들에게도 공개됩니다. 
                                다른 학생들의 정보 접근을 위해 공개를 권장합니다.
                              </p>
                            </div>
                          </div>

                          <div className="flex items-start space-x-3 p-4 border-2 border-border rounded-lg">
                            <RadioGroupItem value="private" id={`private-${group.telegram_id}`} />
                            <div className="flex-1">
                              <Label
                                htmlFor={`private-${group.telegram_id}`}
                                className="flex items-center gap-2 font-bold cursor-pointer"
                              >
                                <Lock className="h-4 w-4" />
                                프라이빗 (Private)
                              </Label>
                              <p className="text-sm text-muted-foreground mt-1">
                                직접 친구를 초대하거나, 공유 링크를 클릭한 사람만 이 그룹의 이벤트 정보를 볼 수 있습니다.
                              </p>
                            </div>
                          </div>
                        </div>
                      </RadioGroup>
                    </CardContent>
                  </Card>
                ))}
            </div>

            <div className="flex gap-4">
              <Button
                variant="outline"
                onClick={() => setStep('select')}
                disabled={isRegistering}
                className="border-2 border-border"
                size="lg"
              >
                뒤로
              </Button>
              <Button
                onClick={handleRegister}
                disabled={isRegistering}
                className="flex-1 border-2 border-border btn-pressed"
                size="lg"
              >
                {isRegistering ? (
                  <>
                    <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                    등록 중...
                  </>
                ) : (
                  '등록'
                )}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function GroupSelection() {
  return (
    <ProtectedRoute>
      <GroupSelectionContent />
    </ProtectedRoute>
  );
}
