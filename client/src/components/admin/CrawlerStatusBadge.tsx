/**
 * Crawler status badge — extracted from AdminDashboard.
 * Renders environment-aware crawler health indicator.
 */
import { Badge } from '@/components/ui/badge';
import { Circle } from 'lucide-react';
import { LiveCrawlerStatus, BackendHealth } from '@/lib/api';

interface CrawlerStatusBadgeProps {
  liveCrawlerStatus: LiveCrawlerStatus | null;
  lastCrawlerContact: number | null;
  health: BackendHealth | null;
}

export default function CrawlerStatusBadge({
  liveCrawlerStatus,
  lastCrawlerContact,
  health,
}: CrawlerStatusBadgeProps) {
  if (!liveCrawlerStatus) {
    const timeSinceLastContact = lastCrawlerContact
      ? (Date.now() - lastCrawlerContact) / 1000
      : Infinity;

    if (timeSinceLastContact < 30) {
      return (
        <Badge variant="outline" className="border-yellow-500 text-yellow-600 text-xs py-0.5">
          <Circle className="h-1.5 w-1.5 mr-1 fill-yellow-500 animate-pulse" />
          재시작 중
        </Badge>
      );
    } else if (health?.environment === "development") {
      return (
        <Badge variant="outline" className="border-blue-500 text-blue-600 text-xs py-0.5">
          <Circle className="h-1.5 w-1.5 mr-1 fill-blue-500" />
          개발 모드
        </Badge>
      );
    } else {
      return (
        <Badge variant="outline" className="border-red-500 text-red-600 text-xs py-0.5">
          <Circle className="h-1.5 w-1.5 mr-1 fill-red-500" />
          연결 불가
        </Badge>
      );
    }
  }

  const { health_status } = liveCrawlerStatus;

  switch (health_status) {
    case "healthy":
      return (
        <Badge variant="outline" className="border-green-500 text-green-600 text-xs py-0.5">
          <Circle className="h-1.5 w-1.5 mr-1 fill-green-500" />
          활성
        </Badge>
      );
    case "degraded":
      return (
        <Badge variant="outline" className="border-orange-500 text-orange-600 text-xs py-0.5">
          <Circle className="h-1.5 w-1.5 mr-1 fill-orange-500" />
          성능 저하
        </Badge>
      );
    case "restarting":
      return (
        <Badge variant="outline" className="border-yellow-500 text-yellow-600 text-xs py-0.5">
          <Circle className="h-1.5 w-1.5 mr-1 fill-yellow-500 animate-pulse" />
          재시작 중
        </Badge>
      );
    case "stopped":
      return (
        <Badge variant="outline" className="border-gray-500 text-gray-600 text-xs py-0.5">
          <Circle className="h-1.5 w-1.5 mr-1 fill-gray-500" />
          정지됨
        </Badge>
      );
    default:
      return (
        <Badge variant="destructive" className="text-xs py-0.5">
          <Circle className="h-1.5 w-1.5 mr-1 fill-red-500" />
          오류
        </Badge>
      );
  }
}
