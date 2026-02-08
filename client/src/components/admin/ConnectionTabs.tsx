/**
 * Telegram connection tabs — extracted from AdminDashboard sidebar.
 * Allows filtering groups by which Telegram account they belong to.
 */
import { Smartphone } from 'lucide-react';
import { TelegramConnection } from '@/lib/api';

interface ConnectionTabsProps {
  connections: TelegramConnection[];
  activeConnectionTab: string | null;
  setActiveConnectionTab: (tab: string | null) => void;
  totalGroupCount: number;
  groupCountByConnection: (connId: string) => number;
  unlinkedGroupCount: number;
}

export default function ConnectionTabs({
  connections,
  activeConnectionTab,
  setActiveConnectionTab,
  totalGroupCount,
  groupCountByConnection,
  unlinkedGroupCount,
}: ConnectionTabsProps) {
  if (connections.length === 0) return null;

  return (
    <div className="border-b border-sidebar-border flex-shrink-0">
      <div className="flex overflow-x-auto px-1 py-1 gap-0.5 no-scrollbar">
        <button
          onClick={() => setActiveConnectionTab(null)}
          className={`flex-shrink-0 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
            activeConnectionTab === null
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-accent'
          }`}
        >
          전체 ({totalGroupCount})
        </button>
        {connections.map((conn) => (
          <button
            key={conn.id}
            onClick={() => setActiveConnectionTab(conn.id)}
            className={`flex-shrink-0 px-3 py-1.5 rounded text-xs font-medium transition-colors flex items-center gap-1 ${
              activeConnectionTab === conn.id
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent'
            }`}
          >
            <Smartphone className="h-3 w-3" />
            {conn.username ? `@${conn.username}` : conn.first_name || conn.phone_masked || '계정'}
            <span className="opacity-70">({groupCountByConnection(conn.id)})</span>
          </button>
        ))}
        {unlinkedGroupCount > 0 && (
          <button
            onClick={() => setActiveConnectionTab('__unlinked__')}
            className={`flex-shrink-0 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              activeConnectionTab === '__unlinked__'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent'
            }`}
          >
            기타 ({unlinkedGroupCount})
          </button>
        )}
      </div>
    </div>
  );
}
