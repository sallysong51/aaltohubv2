/**
 * Admin group management table — extracted from AdminDashboard.
 * Displays a table of all groups with crawler status, toggle, and actions.
 */
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { Loader2, Circle, Power, PowerOff, Download, Trash2 } from 'lucide-react';
import { adminApi, RegisteredGroup, getApiErrorMessage } from '@/lib/api';

interface GroupManagementTableProps {
  groups: RegisteredGroup[];
  selectedGroup: RegisteredGroup | null;
  setSelectedGroup: (g: RegisteredGroup | null) => void;
  setGroups: React.Dispatch<React.SetStateAction<RegisteredGroup[]>>;
  getCrawlerStatus: (group: RegisteredGroup) => 'active' | 'inactive' | 'error' | 'initializing';
  onTriggerCrawl: (groupId: string) => void;
}

export default function GroupManagementTable({
  groups,
  selectedGroup,
  setSelectedGroup,
  setGroups,
  getCrawlerStatus,
  onTriggerCrawl,
}: GroupManagementTableProps) {
  return (
    <div className="flex-1 overflow-auto p-4">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold">그룹 관리</h2>
          <p className="text-xs text-muted-foreground">{groups.length}개 그룹</p>
        </div>
        <div className="border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="text-left px-3 py-2 font-medium">그룹명</th>
                <th className="text-center px-3 py-2 font-medium w-20">멤버</th>
                <th className="text-center px-3 py-2 font-medium w-24">공개여부</th>
                <th className="text-center px-3 py-2 font-medium w-24">크롤링</th>
                <th className="text-center px-3 py-2 font-medium w-20">상태</th>
                <th className="text-center px-3 py-2 font-medium w-28">액션</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {groups.map((group) => {
                const crawlerStatus = getCrawlerStatus(group);
                const isEnabled = group.crawl_enabled !== false;
                return (
                  <tr key={group.id} className="hover:bg-muted/30">
                    <td className="px-3 py-2">
                      <div className="font-medium truncate max-w-[200px]">{group.title}</div>
                      {group.username && (
                        <span className="text-xs text-muted-foreground">@{group.username}</span>
                      )}
                    </td>
                    <td className="text-center px-3 py-2 text-xs text-muted-foreground">
                      {group.member_count?.toLocaleString() || '-'}
                    </td>
                    <td className="text-center px-3 py-2">
                      <Badge
                        variant={group.visibility === 'public' ? 'default' : 'secondary'}
                        className="text-[10px]"
                      >
                        {group.visibility === 'public' ? '🌐 공개' : '🔒 개인'}
                      </Badge>
                    </td>
                    <td className="text-center px-3 py-2">
                      <button
                        onClick={async () => {
                          try {
                            await adminApi.updateGroupCrawl(group.id, !isEnabled);
                            setGroups(prev => prev.map(g =>
                              g.id === group.id ? { ...g, crawl_enabled: !isEnabled } : g
                            ));
                            toast.success(isEnabled ? '크롤링 비활성화됨' : '크롤링 활성화됨');
                          } catch (err) {
                            toast.error(getApiErrorMessage(err, '설정 변경 실패'));
                          }
                        }}
                        className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors ${
                          isEnabled
                            ? 'bg-green-100 text-green-700 hover:bg-green-200 dark:bg-green-900/30 dark:text-green-400'
                            : 'bg-gray-100 text-gray-500 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400'
                        }`}
                      >
                        {isEnabled ? <Power className="h-3 w-3" /> : <PowerOff className="h-3 w-3" />}
                        {isEnabled ? 'ON' : 'OFF'}
                      </button>
                    </td>
                    <td className="text-center px-3 py-2">
                      <div className="flex items-center justify-center gap-1">
                        {crawlerStatus === 'initializing' ? (
                          <Loader2 className="h-3 w-3 animate-spin text-primary" />
                        ) : (
                          <Circle className={`h-2 w-2 ${
                            crawlerStatus === 'active' ? 'fill-green-500 text-green-500' :
                            crawlerStatus === 'error' ? 'fill-yellow-500 text-yellow-500' :
                            'fill-gray-400 text-gray-400'
                          }`} />
                        )}
                        <span className="text-[10px] text-muted-foreground">
                          {crawlerStatus === 'active' ? '활성' :
                           crawlerStatus === 'initializing' ? '수집중' :
                           crawlerStatus === 'error' ? '오류' : '대기'}
                        </span>
                      </div>
                    </td>
                    <td className="text-center px-3 py-2">
                      <div className="flex items-center justify-center gap-1">
                        <button
                          onClick={() => onTriggerCrawl(group.id)}
                          className="p-1 rounded hover:bg-accent text-primary"
                          title="역사 크롤링"
                        >
                          <Download className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={async () => {
                            if (!confirm(`"${group.title}" 그룹을 삭제하시겠습니까?\n\n⚠️ 다음 데이터가 영구 삭제됩니다:\n- 모든 메시지\n- 크롤링 상태\n- 그룹 설정\n- 초대 링크\n\n이 작업은 되돌릴 수 없습니다.`)) return;
                            try {
                              const response = await adminApi.deleteGroup(group.id);
                              console.log('Delete response:', response);
                              setGroups(prev => prev.filter(g => g.id !== group.id));
                              if (selectedGroup?.id === group.id) setSelectedGroup(null);
                              toast.success(`✓ "${group.title}" 그룹이 삭제되었습니다`);
                            } catch (err: any) {
                              console.error('Delete error:', err);
                              const errorMsg = getApiErrorMessage(err, '그룹 삭제에 실패했습니다');
                              toast.error(`❌ ${errorMsg}`, { duration: 5000 });
                            }
                          }}
                          className="p-1 rounded hover:bg-red-100 text-red-500 dark:hover:bg-red-900/30"
                          title="그룹 삭제 (영구 삭제)"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
