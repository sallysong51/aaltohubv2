/**
 * User Management Page - Admin only
 * Manage user roles and view all registered users
 * Manage telegram accounts and re-authenticate expired sessions
 */
import { useState, useEffect } from 'react';
import { useLocation } from 'wouter';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
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
import { Loader2, AlertCircle, RefreshCw, ArrowLeft, UserCog, Trash2, Plus } from 'lucide-react';
import ProtectedRoute from '@/components/ProtectedRoute';
import TelegramConnectFlow from '@/components/TelegramConnectFlow';
import { useAuth } from '@/contexts/AuthContext';
import { adminApi, User, getApiErrorMessage, telegramApi, TelegramConnection, ConnectionHealthStatus } from '@/lib/api';

function UserManagementContent() {
  const [, setLocation] = useLocation();
  const { user: currentUser } = useAuth();

  // User Management Tab
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isUpdating, setIsUpdating] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [showRoleDialog, setShowRoleDialog] = useState(false);
  const [newRole, setNewRole] = useState<'admin' | 'user'>('user');

  // Telegram Accounts Tab
  const [connections, setConnections] = useState<TelegramConnection[]>([]);
  const [healthMap, setHealthMap] = useState<Map<string, ConnectionHealthStatus>>(new Map());
  const [isLoadingTelegram, setIsLoadingTelegram] = useState(false);
  const [isLoadingHealth, setIsLoadingHealth] = useState(false);
  const [healthLoadFailed, setHealthLoadFailed] = useState(false);
  const [showReauthDialog, setShowReauthDialog] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [selectedConnection, setSelectedConnection] = useState<TelegramConnection | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

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

  const loadConnections = async () => {
    setIsLoadingTelegram(true);
    try {
      const response = await telegramApi.getConnections();
      setConnections(response.data);
    } catch (error) {
      toast.error(getApiErrorMessage(error, '텔레그램 계정을 불러오는데 실패했습니다'));
    } finally {
      setIsLoadingTelegram(false);
    }
  };

  const loadHealth = async () => {
    setIsLoadingHealth(true);
    setHealthLoadFailed(false);

    try {
      // Add 5s timeout for health check
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);

      const response = await telegramApi.getConnectionsHealth();
      clearTimeout(timeoutId);

      const map = new Map<string, ConnectionHealthStatus>();
      response.data.connections.forEach(h => map.set(h.connection_id, h));
      setHealthMap(map);
      setHealthLoadFailed(false);
    } catch (error) {
      console.error('Failed to load telegram health:', error);
      setHealthLoadFailed(true);

      // Show error toast only if it's not an abort (timeout)
      if (error instanceof Error && error.name !== 'AbortError') {
        toast.error('세션 상태 확인에 실패했습니다. 잠시 후 다시 시도해주세요.');
      } else {
        toast.error('세션 상태 확인 시간 초과. 네트워크를 확인해주세요.');
      }
    } finally {
      setIsLoadingHealth(false);
    }
  };

  // Load connections and health when telegram tab is opened
  const handleTelegramTabOpen = async () => {
    await Promise.all([loadConnections(), loadHealth()]);
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

  // Telegram account handlers
  const getStatusBadge = (connectionId: string) => {
    // Show loading state only if actively loading
    if (isLoadingHealth) {
      return <Badge variant="secondary"><Loader2 className="w-3 h-3 animate-spin mr-1" />확인 중</Badge>;
    }

    // If load failed and no cached health data, show error state
    if (healthLoadFailed && !healthMap.has(connectionId)) {
      return <Badge variant="secondary" className="border-yellow-500">⚠ 확인 실패</Badge>;
    }

    const health = healthMap.get(connectionId);
    if (!health) {
      return <Badge variant="secondary">? 미확인</Badge>;
    }

    switch (health.status) {
      case 'healthy':
        return <Badge variant="default" className="bg-green-600">✓ 정상</Badge>;
      case 'expired':
        return <Badge variant="destructive">⚠ 만료됨</Badge>;
      case 'invalid':
        return <Badge variant="destructive">✗ 오류</Badge>;
      case 'unreachable':
        return <Badge variant="secondary">! 연결 불가</Badge>;
      default:
        return <Badge variant="secondary">? 알 수 없음</Badge>;
    }
  };

  const shouldShowReauth = (connectionId: string): boolean => {
    const health = healthMap.get(connectionId);
    return health?.status === 'expired' || health?.status === 'invalid';
  };

  const handleReauthClick = (connection: TelegramConnection) => {
    setSelectedConnection(connection);
    setShowReauthDialog(true);
  };

  const handleReauthSuccess = () => {
    toast.success('계정이 재인증되었습니다');
    setShowReauthDialog(false);
    loadConnections();
    loadHealth();
  };

  const handleAddClick = () => {
    setSelectedConnection(null);
    setShowAddDialog(true);
  };

  const handleAddSuccess = () => {
    toast.success('새 계정이 추가되었습니다');
    setShowAddDialog(false);
    loadConnections();
    loadHealth();
  };

  const handleDeleteClick = (connection: TelegramConnection) => {
    setSelectedConnection(connection);
    setShowDeleteDialog(true);
  };

  const handleConfirmDelete = async () => {
    if (!selectedConnection) return;

    setIsDeleting(true);
    try {
      await telegramApi.deleteConnection(selectedConnection.id);
      toast.success('연결이 해제되었습니다');
      setConnections(connections.filter(c => c.id !== selectedConnection.id));
      setShowDeleteDialog(false);
      setSelectedConnection(null);
    } catch (error) {
      toast.error(getApiErrorMessage(error, '연결 해제에 실패했습니다'));
    } finally {
      setIsDeleting(false);
    }
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
            <span className="text-foreground font-medium">관리자 권한</span>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-4xl font-bold flex items-center gap-2">
                <UserCog className="h-8 w-8" />
                관리자 권한
              </h1>
              <p className="text-sm text-muted-foreground mt-1">
                사용자 권한 및 텔레그램 계정 관리
              </p>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <Tabs defaultValue="users" className="w-full">
          <TabsList className="grid w-full grid-cols-2 mb-6">
            <TabsTrigger value="users">사용자 관리</TabsTrigger>
            <TabsTrigger value="telegram" onClick={handleTelegramTabOpen}>텔레그램 계정</TabsTrigger>
          </TabsList>

          {/* Users Tab */}
          <TabsContent value="users" className="space-y-4">
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
          </TabsContent>

          {/* Telegram Accounts Tab */}
          <TabsContent value="telegram" className="space-y-4">
            <Card>
              <CardHeader className="border-b border-border">
                <div className="flex items-center justify-between">
                  <CardTitle>연결된 계정 ({connections.length})</CardTitle>
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleTelegramTabOpen}
                      disabled={isLoadingTelegram}
                    >
                      <RefreshCw className={`h-4 w-4 ${isLoadingTelegram ? 'animate-spin' : ''}`} />
                    </Button>
                    <Button
                      size="sm"
                      onClick={handleAddClick}
                      className="gap-2"
                    >
                      <Plus className="h-4 w-4" />
                      계정 추가
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                {connections.length === 0 ? (
                  <div className="p-8 text-center">
                    <AlertCircle className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                    <p className="text-lg font-medium mb-4">연결된 계정이 없습니다</p>
                    <Button onClick={handleAddClick} className="gap-2">
                      <Plus className="h-4 w-4" />
                      첫 계정 추가하기
                    </Button>
                  </div>
                ) : (
                  <ScrollArea className="w-full">
                    <Table>
                      <TableHeader>
                        <TableRow className="border-b border-border hover:bg-transparent">
                          <TableHead className="font-bold">상태</TableHead>
                          <TableHead className="font-bold">계정</TableHead>
                          <TableHead className="font-bold">전화번호</TableHead>
                          <TableHead className="font-bold">연결일</TableHead>
                          <TableHead className="font-bold text-right">작업</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {connections.map((connection) => (
                          <TableRow
                            key={connection.id}
                            className="border-b-2 border-border hover:bg-accent/50"
                          >
                            <TableCell>
                              {getStatusBadge(connection.id)}
                            </TableCell>
                            <TableCell className="font-medium">
                              <div>
                                {connection.username && <span>@{connection.username}</span>}
                                {connection.first_name && (
                                  <p className="text-xs text-muted-foreground">
                                    {connection.first_name} {connection.last_name || ''}
                                  </p>
                                )}
                              </div>
                            </TableCell>
                            <TableCell className="font-mono text-xs">
                              {connection.phone_masked || '-'}
                            </TableCell>
                            <TableCell className="text-sm">
                              {connection.connected_at
                                ? new Date(connection.connected_at).toLocaleDateString('ko-KR', {
                                  year: 'numeric',
                                  month: 'short',
                                  day: 'numeric',
                                })
                                : '-'}
                            </TableCell>
                            <TableCell className="text-right">
                              <div className="flex items-center justify-end gap-2">
                                {shouldShowReauth(connection.id) && (
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => handleReauthClick(connection)}
                                    className="border-orange-500 text-orange-600 hover:bg-orange-50"
                                  >
                                    재인증
                                  </Button>
                                )}
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => handleDeleteClick(connection)}
                                  disabled={isDeleting}
                                  className="border-red-500 text-red-600 hover:bg-red-50"
                                >
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </ScrollArea>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
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

      {/* Re-authenticate Dialog */}
      <Dialog open={showReauthDialog} onOpenChange={setShowReauthDialog}>
        <DialogContent className="border-2 border-border">
          <DialogHeader>
            <DialogTitle>계정 재인증</DialogTitle>
            <DialogDescription>
              {selectedConnection?.username ? `@${selectedConnection.username}` : '텔레그램 계정'}을(를) 재인증합니다
            </DialogDescription>
          </DialogHeader>

          <div className="py-4">
            <TelegramConnectFlow
              onConnectSuccess={handleReauthSuccess}
              onCancel={() => setShowReauthDialog(false)}
            />
          </div>
        </DialogContent>
      </Dialog>

      {/* Add Account Dialog */}
      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent className="border-2 border-border">
          <DialogHeader>
            <DialogTitle>텔레그램 계정 추가</DialogTitle>
            <DialogDescription>
              새로운 텔레그램 계정을 추가합니다
            </DialogDescription>
          </DialogHeader>

          <div className="py-4">
            <TelegramConnectFlow
              onConnectSuccess={handleAddSuccess}
              onCancel={() => setShowAddDialog(false)}
            />
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent className="border-2 border-border max-w-md">
          <DialogHeader>
            <DialogTitle>계정 연결 해제</DialogTitle>
            <DialogDescription>
              이 작업은 되돌릴 수 없습니다
            </DialogDescription>
          </DialogHeader>

          {selectedConnection && (
            <div className="space-y-4 py-4">
              <div className="space-y-3 p-4 bg-red-50 border-2 border-red-200 rounded-lg">
                <div className="flex gap-3">
                  <AlertCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="font-bold text-red-900">계정 연결 해제</p>
                    <p className="text-sm text-red-800">
                      이 계정으로 등록한 그룹의 크롤링이 중단될 수 있습니다
                    </p>
                  </div>
                </div>

                <div className="space-y-2 text-sm">
                  <div>
                    <p className="text-muted-foreground">계정:</p>
                    <p className="font-bold">
                      {selectedConnection.username ? `@${selectedConnection.username}` : '-'}
                    </p>
                  </div>
                  {selectedConnection.first_name && (
                    <div>
                      <p className="text-muted-foreground">이름:</p>
                      <p className="font-bold">
                        {selectedConnection.first_name} {selectedConnection.last_name || ''}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

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
              onClick={handleConfirmDelete}
              disabled={isDeleting}
            >
              {isDeleting ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  해제 중
                </>
              ) : (
                '연결 해제'
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
