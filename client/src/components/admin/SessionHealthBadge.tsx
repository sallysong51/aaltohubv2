/**
 * Session Health Badge - Displays telegram session status on AdminDashboard
 * Polls /api/telegram/connections/health every 30s to check session validity
 * Shows aggregate status: "세션: X/Y" with color indicator
 */

import { useEffect, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Loader2 } from 'lucide-react';
import { telegramApi, ConnectionsHealthResponse } from '@/lib/api';

export default function SessionHealthBadge() {
  const [healthData, setHealthData] = useState<ConnectionsHealthResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    const loadHealth = async () => {
      setIsLoading(true);
      try {
        const response = await telegramApi.getConnectionsHealth();
        setHealthData(response.data);
      } catch (error) {
        // Silently fail (no network error spam in console)
        console.debug('Failed to load telegram health:', error);
      } finally {
        setIsLoading(false);
      }
    };

    // Initial load
    loadHealth();

    // Poll every 30s
    const interval = setInterval(loadHealth, 30000);

    return () => clearInterval(interval);
  }, []);

  if (!healthData || healthData.connections.length === 0) {
    return null; // Hide if no connections
  }

  // Count healthy vs total
  const healthyCount = healthData.connections.filter(c => c.status === 'healthy').length;
  const totalCount = healthData.connections.length;

  // Determine status and color
  let variant: 'default' | 'secondary' | 'destructive' = 'secondary';
  let label = `세션: ${healthyCount}/${totalCount}`;

  if (healthyCount === totalCount) {
    // All healthy
    variant = 'default';
  } else if (healthyCount === 0) {
    // All expired/invalid
    variant = 'destructive';
    label = `세션 오류: ${healthyCount}/${totalCount}`;
  } else {
    // Some expired
    variant = 'secondary';
  }

  if (isLoading && totalCount === 0) {
    return (
      <Badge variant="secondary" className="gap-2">
        <Loader2 className="w-3 h-3 animate-spin" />
        세션 확인 중
      </Badge>
    );
  }

  return <Badge variant={variant}>{label}</Badge>;
}
