import { Users } from 'lucide-react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { RegisteredGroup } from '@/lib/api';
import { cn } from '@/lib/utils';

interface GroupSidebarProps {
  groups: RegisteredGroup[];
  selectedGroupId: string | null;
  onGroupSelect: (groupId: string | null) => void;
}

export default function GroupSidebar({ groups, selectedGroupId, onGroupSelect }: GroupSidebarProps) {
  return (
    <ScrollArea className="h-full">
      <div className="p-2 space-y-0.5">
        {/* All Groups */}
        <button
          onClick={() => onGroupSelect(null)}
          className={cn(
            'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors',
            selectedGroupId === null
              ? 'bg-primary text-primary-foreground'
              : 'hover:bg-accent',
          )}
        >
          <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
            <Users className="h-4 w-4" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-medium text-sm">전체</div>
            <div className="text-xs opacity-70 truncate">
              {groups.length}개 그룹
            </div>
          </div>
        </button>

        {/* Individual Groups */}
        {groups.filter(g => g.id).map((group, index) => (
          <button
            key={group.id}
            onClick={() => onGroupSelect(group.id)}
            className={cn(
              'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors',
              selectedGroupId === group.id
                ? 'bg-primary text-primary-foreground'
                : 'hover:bg-accent',
            )}
          >
            <div className="w-9 h-9 rounded-full bg-muted flex items-center justify-center shrink-0 text-sm font-semibold">
              {group.title.charAt(0).toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-medium text-sm truncate">{group.title}</div>
              <div className="text-xs opacity-70 truncate">
                {group.group_type === 'channel' ? '채널' : '그룹'}
                {group.member_count ? ` · ${group.member_count}명` : ''}
                {index < 9 && <span className="ml-1 opacity-50">({index + 1})</span>}
              </div>
            </div>
          </button>
        ))}
      </div>
    </ScrollArea>
  );
}
