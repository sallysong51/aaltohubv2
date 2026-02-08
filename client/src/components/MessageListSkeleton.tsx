import { Skeleton } from '@/components/ui/skeleton';

export default function MessageListSkeleton() {
  return (
    <div className="space-y-0 bg-card border border-border rounded-lg overflow-hidden divide-y divide-border">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="p-2 space-y-2">
          <div className="flex items-center gap-2">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-4 w-16 rounded-full" />
          </div>
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-3/4" />
        </div>
      ))}
    </div>
  );
}
