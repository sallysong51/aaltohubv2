/**
 * User Management Page - Admin only
 * Manage user roles and view all registered users
 */
import { useState, useEffect } from 'react';
import { useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { toast } from 'sonner';
import { Loader2, AlertCircle, RefreshCw, ArrowLeft, UserCog } from 'lucide-react';
import ProtectedRoute from '@/components/ProtectedRoute';
import { useAuth } from '@/contexts/AuthContext';
import { adminApi, User, getApiErrorMessage } from '@/lib/api';

function UserManagementContent() {
  const [, setLocation] = useLocation();
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isUpdating, setIsUpdating] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [showRoleDialog, setShowRoleDialog] = useState(false);
  const [newRole, setNewRole] = useState<'admin' | 'user'>('user');

  useEffect(() => {
    loadUsers();
  }, []);

  const loadUsers = async () => {
    setIsLoading(true);
    try {
      const response = await adminApi.getAllUsers();
      setUsers(response.data);
    } catch (error) {
      toast.error(getApiErrorMessage(error, '사용자를 불러오는데 실패했습니다'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleOpenRoleDialog = (user: User) => {
    setSelectedUser(user);
    setNewRole(user.role === 'admin' ? 'user' : 'admin');
    setShowRoleDialog(true);
  };

  const handleConfirmRoleChange = async () => {
    if (!selectedUser) return;

    setIsUpdating(true);
    try {
      await adminApi.updateUserRole(selectedUser.id, newRole);
      toast.success(`${selectedUser.username || '사용자'} 권한이 변경되었습니다`);

      // Update local state
      setUsers(
        users.map((u) =>
          u.id === selectedUser.id ? { ...u, role: newRole } : u
        )
      );

      setShowRoleDialog(false);
      setSelectedUser(null);
    } catch (error) {
      toast.error(getApiErrorMessage(error, '권한 변경에 실패했습니다'));
    } finally {
      setIsUpdating(false);
    }
  };

  const handleCloseDialog = () => {
    setShowRoleDialog(false);
    setSelectedUser(null);
  };

  const isSelfUser = (user: User) => currentUser?.id === user.id;

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('ko-KR', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="container max-w-6xl">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-3 text-sm text-muted-foreground">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setLocation('/admin')}
              className="h-6 w-6 p-0"
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <span>Admin</span>
            <span>/</span>
            <span className="text-foreground font-medium">사용자 관리</span>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-4xl font-bold flex items-center gap-2">
                <UserCog className="h-8 w-8" />
                사용자 관리
              </h1>
              <p className="text-sm text-muted-foreground mt-1">
                {users.length}명의 사용자가 등록되어 있습니다
              </p>
            </div>
            <Button
              variant="outline"
              onClick={loadUsers}
              disabled={isLoading}
            >
              <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>

        {/* User Table */}
        <Card>
          <CardHeader className="border-b border-border">
            <CardTitle>등록된 사용자</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {users.length === 0 ? (
              <div className="p-8 text-center">
                <AlertCircle className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                <p className="text-lg font-medium">등록된 사용자가 없습니다</p>
              </div>
            ) : (
              <ScrollArea className="w-full">
                <Table>
                  <TableHeader>
                    <TableRow className="border-b border-border hover:bg-transparent">
                      <TableHead className="font-bold">사용자명</TableHead>
                      <TableHead className="font-bold">이름</TableHead>
                      <TableHead className="font-bold">전화번호</TableHead>
                      <TableHead className="font-bold">Telegram ID</TableHead>
                      <TableHead className="font-bold">권한</TableHead>
                      <TableHead className="font-bold">가입일</TableHead>
                      <TableHead className="font-bold text-right">작업</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {users.map((user) => (
                      <TableRow
                        key={user.id}
                        className="border-b-2 border-border hover:bg-accent/50"
                      >
                        <TableCell className="font-medium">
                          {user.username ? `@${user.username}` : '-'}
                        </TableCell>
                        <TableCell>
                          {user.first_name || user.last_name
                            ? `${user.first_name || ''} ${user.last_name || ''}`.trim()
                            : '-'}
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {user.phone_number || '-'}
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {user.telegram_id}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={user.role === 'admin' ? 'default' : 'outline'}
                            className="font-semibold"
                          >
                            {user.role === 'admin' ? '관리자' : '사용자'}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-sm">
                          {formatDate(user.created_at)}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant={isSelfUser(user) ? 'outline' : 'default'}
                            size="sm"
                            onClick={() => handleOpenRoleDialog(user)}
                            disabled={isSelfUser(user) || isUpdating}
                            className="border-2 border-border"
                            title={
                              isSelfUser(user)
                                ? '자신의 권한은 변경할 수 없습니다'
                                : undefined
                            }
                          >
                            권한 변경
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </ScrollArea>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Role Change Dialog */}
      <Dialog open={showRoleDialog} onOpenChange={setShowRoleDialog}>
        <DialogContent className="border-2 border-border max-w-md">
          <DialogHeader>
            <DialogTitle>권한 변경</DialogTitle>
            <DialogDescription>
              사용자의 권한을 변경합니다. 이 작업은 되돌릴 수 없습니다.
            </DialogDescription>
          </DialogHeader>

          {selectedUser && (
            <div className="space-y-4 py-4">
              {/* User Info */}
              <div className="space-y-3 p-4 bg-muted rounded-lg border-2 border-border">
                <div>
                  <p className="text-sm text-muted-foreground">사용자명</p>
                  <p className="font-bold">
                    {selectedUser.username ? `@${selectedUser.username}` : '-'}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">이름</p>
                  <p className="font-bold">
                    {selectedUser.first_name || selectedUser.last_name
                      ? `${selectedUser.first_name || ''} ${selectedUser.last_name || ''}`.trim()
                      : '-'}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">전화번호</p>
                  <p className="font-bold font-mono text-xs">
                    {selectedUser.phone_number || '-'}
                  </p>
                </div>
              </div>

              {/* Role Change Info */}
              <div className="space-y-3 p-4 bg-yellow-50 border-2 border-yellow-200 rounded-lg">
                <div className="flex gap-3">
                  <AlertCircle className="h-5 w-5 text-yellow-600 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="font-bold text-yellow-900">권한 변경</p>
                    <p className="text-sm text-yellow-800">
                      {selectedUser.role === 'admin'
                        ? '관리자 권한을 제거하고 일반 사용자로 변경합니다'
                        : '일반 사용자를 관리자로 승격합니다'}
                    </p>
                  </div>
                </div>

                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">현재 권한:</span>
                    <Badge
                      variant={selectedUser.role === 'admin' ? 'default' : 'outline'}
                    >
                      {selectedUser.role === 'admin' ? '관리자' : '사용자'}
                    </Badge>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">변경할 권한:</span>
                    <Badge
                      variant={newRole === 'admin' ? 'default' : 'outline'}
                    >
                      {newRole === 'admin' ? '관리자' : '사용자'}
                    </Badge>
                  </div>
                </div>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button
              variant="outline"
              onClick={handleCloseDialog}
              disabled={isUpdating}
              className="border-2 border-border"
            >
              취소
            </Button>
            <Button
              onClick={handleConfirmRoleChange}
              disabled={isUpdating}
              className="border-2"
            >
              {isUpdating ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  변경 중...
                </>
              ) : (
                '권한 변경'
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function UserManagement() {
  return (
    <ProtectedRoute adminOnly>
      <UserManagementContent />
    </ProtectedRoute>
  );
}
