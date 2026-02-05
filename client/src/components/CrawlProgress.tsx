/**
 * Crawl Progress Component
 * Shows progress when initially loading 30 days of message history
 */
import { Progress } from '@/components/ui/progress';
import { Card, CardContent } from '@/components/ui/card';
import { Loader2 } from 'lucide-react';

interface CrawlProgressProps {
  groupTitle: string;
  progress: number;
  total: number;
}

export default function CrawlProgress({ groupTitle, progress, total }: CrawlProgressProps) {
  const percentage = total > 0 ? Math.round((progress / total) * 100) : 0;

  return (
    <Card className="border-2 border-primary">
      <CardContent className="p-6">
        <div className="flex items-center gap-3 mb-4">
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
          <div>
            <h3 className="font-bold">{groupTitle}</h3>
            <p className="text-sm text-muted-foreground">
              메시지를 불러오는 중입니다...
            </p>
          </div>
        </div>
        
        <Progress value={percentage} className="mb-2" />
        
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">
            {progress.toLocaleString()} / {total.toLocaleString()} 메시지
          </span>
          <span className="font-mono font-bold">{percentage}%</span>
        </div>
        
        {total > 0 && (
          <p className="text-xs text-muted-foreground mt-2">
            예상 소요 시간: 약 {Math.ceil((total - progress) / 100)} 분
          </p>
        )}
      </CardContent>
    </Card>
  );
}
