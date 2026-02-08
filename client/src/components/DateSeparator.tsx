import { formatDateLabel } from '@/lib/dateFormat';

export default function DateSeparator({ date }: { date: string }) {
  return (
    <div className="flex items-center justify-center py-2">
      <div className="px-3 py-0.5 bg-muted rounded-full text-xs text-muted-foreground font-medium">
        {formatDateLabel(date)}
      </div>
    </div>
  );
}
