import { Button } from '@/components/ui/button';
import { Loader2, Download, ChevronRight, AlertCircle } from 'lucide-react';
import type { CrawlProgressItem } from '@/lib/api';
import CrawlProgressDisplay from './CrawlProgressDisplay';

interface CompleteStepProps {
  crawlInitiated: boolean;
  crawlProgress: CrawlProgressItem[];
  pollError: boolean;
  onContinue: () => void;
  onRetryPoll: () => void;
}

export default function CompleteStep({
  crawlInitiated,
  crawlProgress,
  pollError,
  onContinue,
  onRetryPoll,
}: CompleteStepProps) {
  const allDone = crawlProgress.length > 0 && crawlProgress.every(
    p => p.status === 'active' || p.status === 'error'
  );

  return (
    <div className="py-8">
      <div className="text-center mb-8">
        <Download className="h-16 w-16 mx-auto mb-4 text-primary" />
        <h2 className="text-2xl font-bold mb-2">등록 완료!</h2>
        <p className="text-muted-foreground">
          {crawlInitiated ? '과거 2주간의 메시지를 수집하고 있습니다' : '그룹이 성공적으로 등록되었습니다.'}
        </p>
      </div>

      {crawlInitiated && <CrawlProgressDisplay crawlProgress={crawlProgress} />}

      {crawlInitiated && crawlProgress.length === 0 && !pollError && (
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground mb-8">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>크롤러에 연결 중...</span>
        </div>
      )}

      {pollError && (
        <div className="text-center text-sm text-red-500 mb-8">
          <AlertCircle className="h-4 w-4 inline mr-1" />
          진행 상태를 가져올 수 없습니다.{' '}
          <button className="underline ml-1" onClick={onRetryPoll}>
            다시 시도
          </button>
        </div>
      )}

      <div className="flex justify-center gap-4">
        <Button onClick={onContinue} className="border-2 border-border btn-pressed" size="lg">
          {allDone || !crawlInitiated ? '계속하기' : '건너뛰기'}
          <ChevronRight className="ml-2 h-5 w-5" />
        </Button>
      </div>
    </div>
  );
}
