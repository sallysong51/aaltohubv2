import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Users, ChevronRight, AlertCircle, Info } from 'lucide-react';
import type { TelegramGroup, TelegramConnection } from '@/lib/api';

interface SelectStepProps {
  groups: TelegramGroup[];
  unregisteredGroups: TelegramGroup[];
  registeredGroups: TelegramGroup[];
  selectedGroups: Set<number>;
  connections: TelegramConnection[];
  selectedConnectionId: string | null;
  isRegistering: boolean;
  userRole?: string;
  onToggleGroup: (telegramId: number) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  onConnectionSelect: (connId: string) => void;
  onShowTelegramLogin: () => void;
  onNext: () => void;
  onCancel: () => void;
  onRefreshGroups: (connId: string) => void;
}

export default function SelectStep({
  unregisteredGroups,
  registeredGroups,
  selectedGroups,
  connections,
  selectedConnectionId,
  isRegistering,
  userRole,
  onToggleGroup,
  onSelectAll,
  onDeselectAll,
  onConnectionSelect,
  onShowTelegramLogin,
  onNext,
  onCancel,
  onRefreshGroups,
}: SelectStepProps) {
  return (
    <>
      <div className="mb-8">
        <h1 className="text-4xl font-bold mb-2">그룹 선택</h1>
        <p className="text-muted-foreground">등록할 텔레그램 그룹을 선택하세요</p>

        {connections.length > 1 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {connections.map(conn => (
              <Button
                key={conn.id}
                variant={selectedConnectionId === conn.id ? 'default' : 'outline'}
                size="sm"
                onClick={() => onConnectionSelect(conn.id)}
                className="border-2"
              >
                {conn.first_name || conn.username || conn.phone_masked || '텔레그램'}
                {conn.username && <span className="ml-1 text-xs opacity-70">@{conn.username}</span>}
              </Button>
            ))}
            <Button variant="outline" size="sm" onClick={onShowTelegramLogin} className="border-2 border-dashed">
              + 계정 추가
            </Button>
          </div>
        )}
        {connections.length === 1 && (
          <div className="mt-4 flex items-center gap-2">
            <Badge variant="outline" className="border-2">
              {connections[0].first_name || connections[0].username || '텔레그램'} 계정
            </Badge>
            <Button variant="ghost" size="sm" onClick={onShowTelegramLogin} className="text-xs">
              + 다른 계정 추가
            </Button>
          </div>
        )}
        {unregisteredGroups.length > 0 && (
          <div className="mt-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Badge variant={selectedGroups.size > 0 ? "default" : "outline"} className="border-2">
                {selectedGroups.size}개 선택됨
              </Badge>
              <span className="text-sm text-muted-foreground">/ 총 {unregisteredGroups.length}개 그룹</span>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={onSelectAll} disabled={selectedGroups.size === unregisteredGroups.length} className="border-2">
                모두 선택
              </Button>
              <Button variant="outline" size="sm" onClick={onDeselectAll} disabled={selectedGroups.size === 0} className="border-2">
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
                  <Button onClick={onCancel} className="border-2 border-border btn-pressed">
                    {userRole === 'admin' ? '관리자 대시보드로 이동' : '그룹 관리로 이동'}
                  </Button>
                </>
              ) : (
                <>
                  <AlertCircle className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                  <p className="text-lg font-medium mb-2">가입된 그룹이 없습니다</p>
                  <p className="text-sm text-muted-foreground mb-4">
                    텔레그램에서 그룹이나 채널에 가입한 후 아래 새로고침을 눌러주세요
                  </p>
                  <Button onClick={() => selectedConnectionId && onRefreshGroups(selectedConnectionId)} variant="outline" className="border-2 border-border">
                    새로고침
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
                className={`refined-card cursor-pointer transition-all ${selectedGroups.has(group.telegram_id) ? 'border-primary' : 'border-border'}`}
                onClick={() => onToggleGroup(group.telegram_id)}
              >
                <CardContent className="p-4">
                  <div className="flex items-start gap-4">
                    <Checkbox checked={selectedGroups.has(group.telegram_id)} onCheckedChange={() => onToggleGroup(group.telegram_id)} className="mt-1" />
                    <Avatar className="size-14 rounded-lg border-2 border-border shrink-0">
                      {group.photo_url && <AvatarImage src={group.photo_url} alt={group.title} />}
                      <AvatarFallback className="rounded-lg font-bold text-lg bg-accent">{group.title.charAt(0).toUpperCase()}</AvatarFallback>
                    </Avatar>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-bold text-lg truncate">{group.title}</h3>
                      {group.username && <p className="text-sm text-muted-foreground truncate">@{group.username}</p>}
                      <div className="flex items-center gap-4 mt-2">
                        {group.member_count && (
                          <div className="flex items-center gap-1 text-sm text-muted-foreground">
                            <Users className="h-4 w-4" />
                            {group.member_count.toLocaleString()}명
                          </div>
                        )}
                        <Badge variant="outline" className="border-2">
                          {group.group_type === 'channel' ? '채널' : group.group_type === 'supergroup' ? '슈퍼그룹' : '그룹'}
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
                        <Card className="refined-card opacity-50 cursor-not-allowed">
                          <CardContent className="p-4">
                            <div className="flex items-start gap-4">
                              <Checkbox checked={false} disabled className="mt-1" />
                              <Avatar className="size-14 rounded-lg border-2 border-border shrink-0 opacity-50">
                                {group.photo_url && <AvatarImage src={group.photo_url} alt={group.title} />}
                                <AvatarFallback className="rounded-lg font-bold text-lg bg-accent">{group.title.charAt(0).toUpperCase()}</AvatarFallback>
                              </Avatar>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <h3 className="font-bold text-lg truncate">{group.title}</h3>
                                  <Info className="h-4 w-4 text-muted-foreground shrink-0" />
                                </div>
                                {group.username && <p className="text-sm text-muted-foreground truncate">@{group.username}</p>}
                                <Badge variant="secondary" className="mt-2">이미 등록됨</Badge>
                              </div>
                            </div>
                          </CardContent>
                        </Card>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="border-2 border-border">
                        <p className="font-medium">이미 등록된 그룹입니다</p>
                        <p className="text-xs text-muted-foreground mt-1">이 그룹은 이미 AaltoHub에 등록되어 있어 선택할 수 없습니다</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                ))}
              </div>
            </div>
          )}

          <div className="flex gap-4">
            <Button variant="outline" onClick={onCancel} disabled={isRegistering} className="border-2 border-border" size="lg">
              취소
            </Button>
            <Button onClick={onNext} disabled={selectedGroups.size === 0 || isRegistering} className="flex-1 border-2 border-border btn-pressed" size="lg">
              다음
              <ChevronRight className="ml-2 h-5 w-5" />
            </Button>
          </div>
        </>
      )}
    </>
  );
}
