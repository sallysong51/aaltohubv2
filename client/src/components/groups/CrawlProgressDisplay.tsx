/**
 * Crawl progress display — extracted from GroupSelection.
 * Shows per-group crawl progress bars during initial data collection.
 */
import { Card, CardContent } from '@/components/ui/card';
import { Loader2, CheckCircle2, XCircle, Download } from 'lucide-react';
import { CrawlProgressItem } from '@/lib/api';

interface CrawlProgressDisplayProps {
  crawlProgress: CrawlProgressItem[];
}

export default function CrawlProgressDisplay({ crawlProgress }: CrawlProgressDisplayProps) {
  if (crawlProgress.length === 0) return null;

  return (
    <div className="space-y-4 mb-8 max-w-xl mx-auto">
      {crawlProgress.map((p) => {
        const pct = p.initial_crawl_total > 0
          ? Math.min(100, Math.round((p.initial_crawl_progress / p.initial_crawl_total) * 100))
          : 0;
        const isDone = p.status === 'active';
        const isError = p.status === 'error';
        const isInitializing = p.status === 'initializing' || p.status === 'inactive';
        const isCrawling = isInitializing && !!p.is_currently_crawling;
        const isQueued = isInitializing && !p.is_currently_crawling;

        return (
          <Card key={p.group_id} className="refined-card">
            <CardContent className="p-4">
              <div className="flex items-center gap-3 mb-2">
                {isDone && <CheckCircle2 className="h-5 w-5 text-green-500 shrink-0" />}
                {isError && <XCircle className="h-5 w-5 text-red-500 shrink-0" />}
                {isCrawling && <Loader2 className="h-5 w-5 animate-spin text-primary shrink-0" />}
                {isQueued && <Download className="h-5 w-5 text-muted-foreground shrink-0" />}
                <span className="font-bold truncate">{p.group_name}</span>
                <span className="ml-auto text-sm text-muted-foreground shrink-0">
                  {isDone && '수집 완료'}
                  {isError && '오류'}
                  {isCrawling && p.initial_crawl_total > 0 && `수집 중: ${p.initial_crawl_progress.toLocaleString()} / ${p.initial_crawl_total.toLocaleString()}`}
                  {isCrawling && p.initial_crawl_total === 0 && '수집 시작 중...'}
                  {isQueued && '대기 중...'}
                </span>
              </div>
              {isCrawling && (
                <div className="w-full bg-muted rounded-full h-2 overflow-hidden">
                  <div
                    className="bg-primary h-2 rounded-full transition-all duration-500"
                    style={{ width: `${p.initial_crawl_total > 0 ? pct : 10}%` }}
                  />
                </div>
              )}
              {isQueued && (
                <div className="w-full bg-muted rounded-full h-2 overflow-hidden">
                  <div className="bg-muted-foreground/30 h-2 rounded-full w-[5%]" />
                </div>
              )}
              {isDone && (
                <div className="w-full bg-green-100 dark:bg-green-950 rounded-full h-2">
                  <div className="bg-green-500 h-2 rounded-full w-full" />
                </div>
              )}
              {isError && p.last_error && (
                <p className="text-xs text-red-500 mt-1 truncate">{p.last_error}</p>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
