/**
 * User Groups Page
 * Shows registered groups for regular users
 */
import { useState, useEffect } from 'react';
import { useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { Loader2, Users, Globe, Lock, Plus, Settings, ArrowLeft } from 'lucide-react';
import { groupsApi, RegisteredGroup, getApiErrorMessage } from '@/lib/api';
import ProtectedRoute from '@/components/ProtectedRoute';

function UserGroupsContent() {
  const [, setLocation] = useLocation();
  const [groups, setGroups] = useState<RegisteredGroup[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    loadGroups();
  }, []);

  const loadGroups = async () => {
    setIsLoading(true);
    try {
      const response = await groupsApi.getRegisteredGroups();
      setGroups(response.data);
    } catch (error) {
      toast.error(getApiErrorMessage(error, '그룹 목록을 불러오는데 실패했습니다'));
    } finally {
      setIsLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b border-border bg-card">
        <div className="container py-6">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <Button
                  variant="outline"
                  onClick={() => setLocation('/feed')}
                  size="sm"
                >
                  <ArrowLeft className="h-4 w-4 mr-2" />
                  피드로
                </Button>
                <h1 className="text-4xl font-bold">내 그룹</h1>
              </div>
              <p className="text-muted-foreground">
                등록된 텔레그램 그룹 목록
              </p>
            </div>
            <Button
              onClick={() => setLocation('/groups/select')}
              className="btn-pressed"
            >
              <Plus className="mr-2 h-4 w-4" />
              그룹 추가
            </Button>
          </div>
        </div>
      </div>

      {/* Groups List */}
      <div className="container py-8">
        {groups.length === 0 ? (
          <Card className="refined-card">
            <CardContent className="pt-6">
              <div className="text-center py-12">
                <Users className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
                <h2 className="text-2xl font-bold mb-2">등록된 그룹이 없습니다</h2>
                <p className="text-muted-foreground mb-6">
                  텔레그램 그룹을 등록하여 이벤트 정보를 받아보세요
                </p>
                <Button
                  onClick={() => setLocation('/groups/select')}
                  className="btn-pressed"
                  size="lg"
                >
                  <Plus className="mr-2 h-5 w-5" />
                  그룹 등록하기
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {groups.map((group) => (
              <Card key={group.id} className="refined-card">
                <CardContent className="p-6">
                  <div className="mb-4">
                    <h3 className="font-bold text-xl mb-2">{group.title}</h3>
                    {group.username && (
                      <p className="text-sm text-muted-foreground">@{group.username}</p>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-2 mb-4">
                    <Badge
                      key="visibility"
                      variant={group.visibility === 'public' ? 'default' : 'secondary'}
                    >
                      {group.visibility === 'public' ? (
                        <>
                          <Globe className="mr-1 h-3 w-3" />
                          퍼블릭
                        </>
                      ) : (
                        <>
                          <Lock className="mr-1 h-3 w-3" />
                          프라이빗
                        </>
                      )}
                    </Badge>

                    {group.member_count && (
                      <Badge key="member-count" variant="outline" className="border-2">
                        <Users className="mr-1 h-3 w-3" />
                        {group.member_count.toLocaleString()}명
                      </Badge>
                    )}

                    <Badge key="group-type" variant="outline" className="border-2">
                      {group.group_type === 'channel' ? '채널' :
                       group.group_type === 'supergroup' ? '슈퍼그룹' : '그룹'}
                    </Badge>
                  </div>

                  <div className="mt-4 flex items-center justify-between">
                    <span className="text-xs text-muted-foreground timestamp">
                      등록일: {new Date(group.created_at).toLocaleDateString('ko-KR')}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setLocation(`/groups/${group.id}/settings`)}
                      className="border-2"
                    >
                      <Settings className="h-4 w-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function UserGroups() {
  return (
    <ProtectedRoute>
      <UserGroupsContent />
    </ProtectedRoute>
  );
}
