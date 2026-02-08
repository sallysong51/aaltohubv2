import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';

interface KeyboardShortcutsHelpProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  shortcuts: Array<{ key: string; description: string }>;
}

function formatKey(key: string): string {
  switch (key) {
    case 'Escape': return 'Esc';
    case '/': return '/';
    case '?': return '?';
    default: return key.toUpperCase();
  }
}

export default function KeyboardShortcutsHelp({ open, onOpenChange, shortcuts }: KeyboardShortcutsHelpProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>키보드 단축키</DialogTitle>
          <DialogDescription>이벤트 피드에서 사용할 수 있는 단축키입니다.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-1.5">
          {shortcuts.map(({ key, description }) => (
            <div key={key} className="flex items-center justify-between py-1.5 px-1">
              <span className="text-sm">{description}</span>
              <kbd className="px-2 py-0.5 text-xs font-mono bg-muted border border-border rounded">
                {formatKey(key)}
              </kbd>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
