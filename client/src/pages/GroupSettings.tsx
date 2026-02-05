/**
 * Group Settings Page
 * Manage group visibility, invite links, and deletion
 */
import { useState, useEffect } from 'react';
import { useRoute, useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import { Loader2, Link as LinkIcon, Trash2, Copy, XCircle } from 'lucide-react';
import ProtectedRoute from '@/components/ProtectedRoute';
import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface InviteLink {
  id: string;
  token: string;
  expires_at?: string;
  is_revoked: boolean;
  used_count: number;
  max_uses?: number;
  created_at: string;
}

function GroupSettingsContent() {
  const [, params] = useRoute('/groups/:groupId/settings');
  const [, setLocation] = useLocation();
  
  const groupId = params?.groupId;
  
  const [group, setGroup] = useState<any>(null);
  const [inviteLinks, setInviteLinks] = useState<InviteLink[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  useEffect(() => {
    if (groupId) {
      loadGroupDetails();
      loadInviteLinks();
    }
  }, [groupId]);

  const loadGroupDetails = async () => {
    try {
      const token = localStorage.getItem('access_token');
      const response = await axios.get(`${API_BASE_URL}/api/groups/${groupId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setGroup(response.data);
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '그룹 정보를 불러오는데 실패했습니다');
    } finally {
      setIsLoading(false);
    }
  };

  const loadInviteLinks = async () => {
    try {
      const token = localStorage.getItem('access_token');
      const response = await axios.get(`${API_BASE_URL}/api/groups/${groupId}/invite-links`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setInviteLinks(response.data);
    } catch (error) {
      // Ignore error if endpoint doesn't exist yet
    }
  };

  const handleVisibilityChange = async (isPublic: boolean) => {
    try {
      const token = localStorage.getItem('access_token');
      await axios.patch(
        `${API_BASE_URL}/api/groups/${groupId}/visibility`,
        null,
        {
          params: { visibility: isPublic ? 'public' : 'private' },
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      toast.success('공개 설정이 변경되었습니다');
      loadGroupDetails();
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '공개 설정 변경에 실패했습니다');
    }
  };

  const handleCreateInviteLink = async () => {
    try {
      const token = localStorage.getItem('access_token');
      const response = await axios.post(
        `${API_BASE_URL}/api/groups/${groupId}/invite-link`,
        {},
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      
      const inviteUrl = `${window.location.origin}/invite/${response.data.token}`;
      await navigator.clipboard.writeText(inviteUrl);
      toast.success('초대 링크가 생성되고 클립보드에 복사되었습니다');
      loadInviteLinks();
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '초대 링크 생성에 실패했습니다');
    }
  };

  const handleCopyInviteLink = async (token: string) => {
    const inviteUrl = `${window.location.origin}/invite/${token}`;
    await navigator.clipboard.writeText(inviteUrl);
    toast.success('초대 링크가 클립보드에 복사되었습니다');
  };

  const handleRevokeInviteLink = async (inviteId: string) => {
    try {
      const token = localStorage.getItem('access_token');
      await axios.post(
        `${API_BASE_URL}/api/groups/${groupId}/invite-link/${inviteId}/revoke`,
        {},
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      toast.success('초대 링크가 무효화되었습니다');
      loadInviteLinks();
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '초대 링크 무효화에 실패했습니다');
    }
  };

  const handleDeleteGroup = async () => {
    setIsDeleting(true);
    try {
      const token = localStorage.getItem('access_token');
      await axios.delete(`${API_BASE_URL}/api/groups/${groupId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success('그룹이 삭제되었습니다');
      setLocation('/groups');
    } catch (error: any) {
      toast.error(error.response?.data?.detail || '그룹 삭제에 실패했습니다');
    } finally {
      setIsDeleting(false);
      setShowDeleteDialog(false);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!group) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Card className="max-w-md w-full border-2 border-destructive">
          <CardHeader>
            <CardTitle>그룹을 찾을 수 없습니다</CardTitle>
          </CardHeader>
          <CardContent>
            <Button onClick={() => setLocation('/groups')} className="w-full">
              그룹 목록으로 이동
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background p-4">
      <div className="container max-w-4xl">
        <div className="mb-6">
          <h1 className="text-3xl font-bold mb-2">{group.title}</h1>
          <p className="text-muted-foreground">그룹 설정</p>
        </div>

        {/* Visibility Settings */}
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>공개 설정</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium">퍼블릭 그룹</p>
                <p className="text-sm text-muted-foreground">
                  모든 사용자가 이 그룹의 이벤트를 볼 수 있습니다
                </p>
              </div>
              <Switch
                checked={group.visibility === 'public'}
                onCheckedChange={handleVisibilityChange}
              />
            </div>
            
            {group.visibility === 'public' && group.admin_invite_error && (
              <div className="mt-4 p-3 bg-destructive/10 border border-destructive/20 rounded">
                <p className="text-sm text-destructive">
                  관리자 초대 실패: {group.admin_invite_error}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  @chaeyeonsally를 그룹에 직접 초대해주세요.
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Invite Links (Private Groups Only) */}
        {group.visibility === 'private' && (
          <Card className="mb-6">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>초대 링크</CardTitle>
                <Button onClick={handleCreateInviteLink} size="sm">
                  <LinkIcon className="mr-2 h-4 w-4" />
                  새 링크 생성
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {inviteLinks.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">
                  생성된 초대 링크가 없습니다
                </p>
              ) : (
                <div className="space-y-3">
                  {inviteLinks.map((invite) => (
                    <div
                      key={invite.id}
                      className="flex items-center justify-between p-3 border-2 rounded"
                    >
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <code className="text-xs bg-muted px-2 py-1 rounded">
                            {invite.token.substring(0, 16)}...
                          </code>
                          {invite.is_revoked && (
                            <Badge variant="destructive">무효화됨</Badge>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          사용 횟수: {invite.used_count}
                          {invite.max_uses && ` / ${invite.max_uses}`}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        {!invite.is_revoked && (
                          <>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleCopyInviteLink(invite.token)}
                            >
                              <Copy className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => handleRevokeInviteLink(invite.id)}
                            >
                              <XCircle className="h-4 w-4" />
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Delete Group */}
        <Card className="border-2 border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">위험 구역</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium">그룹 삭제</p>
                <p className="text-sm text-muted-foreground">
                  이 작업은 되돌릴 수 없습니다
                </p>
              </div>
              <Button
                variant="destructive"
                onClick={() => setShowDeleteDialog(true)}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                삭제
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Delete Confirmation Dialog */}
        <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>그룹 삭제 확인</DialogTitle>
              <DialogDescription>
                정말로 이 그룹을 삭제하시겠습니까? 이 작업은 되돌릴 수 없으며, 모든 이벤트
                정보도 함께 삭제됩니다.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setShowDeleteDialog(false)}
                disabled={isDeleting}
              >
                취소
              </Button>
              <Button
                variant="destructive"
                onClick={handleDeleteGroup}
                disabled={isDeleting}
              >
                {isDeleting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                삭제
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}

export default function GroupSettings() {
  return (
    <ProtectedRoute>
      <GroupSettingsContent />
    </ProtectedRoute>
  );
}
