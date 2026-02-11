import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Badge } from '@/components/ui/badge';
import { Loader2, Lock, Globe, AlertCircle } from 'lucide-react';
import type { TelegramGroup } from '@/lib/api';

interface VisibilityStepProps {
  groups: TelegramGroup[];
  selectedGroups: Set<number>;
  groupVisibility: Map<number, 'public' | 'private'>;
  isRegistering: boolean;
  onVisibilityChange: (groupId: number, visibility: 'public' | 'private') => void;
  onSetAllVisibility: (visibility: 'public' | 'private') => void;
  onRegister: () => void;
  onBack: () => void;
}

export default function VisibilityStep({
  groups,
  selectedGroups,
  groupVisibility,
  isRegistering,
  onVisibilityChange,
  onSetAllVisibility,
  onRegister,
  onBack,
}: VisibilityStepProps) {
  const selectedGroupsList = groups.filter(g => selectedGroups.has(g.telegram_id));

  return (
    <>
      <div className="mb-8">
        <h1 className="text-4xl font-bold mb-2">공개 여부 설정</h1>
        <p className="text-muted-foreground">각 그룹의 공개 여부를 선택하세요 (기본값: 공개)</p>
        {selectedGroups.size > 1 && (
          <div className="mt-4 flex gap-2">
            <Button variant="outline" size="sm" onClick={() => onSetAllVisibility('public')} className="border-2">
              <Globe className="mr-2 h-4 w-4" />
              모두 공개로 설정
            </Button>
            <Button variant="outline" size="sm" onClick={() => onSetAllVisibility('private')} className="border-2">
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
        {selectedGroupsList.map((group) => (
          <Card key={group.telegram_id} className="refined-card">
            <CardContent className="p-6">
              <h3 className="font-bold text-lg mb-4">{group.title}</h3>
              <RadioGroup
                value={groupVisibility.get(group.telegram_id)}
                onValueChange={(value: string) => onVisibilityChange(group.telegram_id, value as 'public' | 'private')}
              >
                <div className="space-y-4">
                  <div className="flex items-start space-x-3 p-4 border-2 border-border rounded-lg bg-accent/10">
                    <RadioGroupItem value="public" id={`public-${group.telegram_id}`} />
                    <div className="flex-1">
                      <Label htmlFor={`public-${group.telegram_id}`} className="flex items-center gap-2 font-bold cursor-pointer">
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
                      <Label htmlFor={`private-${group.telegram_id}`} className="flex items-center gap-2 font-bold cursor-pointer">
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
        <Button variant="outline" onClick={onBack} disabled={isRegistering} className="border-2 border-border" size="lg">
          뒤로
        </Button>
        <Button onClick={onRegister} disabled={isRegistering} className="flex-1 border-2 border-border btn-pressed" size="lg">
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
  );
}
