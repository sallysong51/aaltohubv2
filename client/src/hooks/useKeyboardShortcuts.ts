import { useEffect, useRef } from 'react';

export interface ShortcutAction {
  key: string;
  description: string;
  handler: () => void;
  ctrl?: boolean;
  shift?: boolean;
}

interface UseKeyboardShortcutsOptions {
  shortcuts: ShortcutAction[];
  enabled?: boolean;
}

export function useKeyboardShortcuts({ shortcuts, enabled = true }: UseKeyboardShortcutsOptions) {
  const shortcutsRef = useRef(shortcuts);
  shortcutsRef.current = shortcuts;

  useEffect(() => {
    if (!enabled) return;

    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      const tag = target.tagName.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable) {
        if (e.key !== 'Escape') return;
      }
      if (e.isComposing) return;

      for (const s of shortcutsRef.current) {
        if (e.key !== s.key) continue;
        if (s.ctrl && !(e.ctrlKey || e.metaKey)) continue;
        if (!s.ctrl && (e.ctrlKey || e.metaKey)) continue;
        if (s.shift && !e.shiftKey) continue;
        if (!s.shift && e.shiftKey && e.key !== '?') continue;

        e.preventDefault();
        s.handler();
        return;
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [enabled]);
}
