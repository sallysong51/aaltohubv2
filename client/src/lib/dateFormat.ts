/**
 * Shared date formatting utilities
 * Single source of truth for all date display across the app
 */

/** "오늘" / "어제" / full Korean date (year, month, day) */
export function formatDateLabel(dateStr: string): string {
  const date = new Date(dateStr);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  if (date.toDateString() === today.toDateString()) return '오늘';
  if (date.toDateString() === yesterday.toDateString()) return '어제';
  return date.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' });
}

/** "오늘" / "어제" / short Korean date (month, day only) */
export function formatDateShort(dateStr: string): string {
  const date = new Date(dateStr);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  if (date.toDateString() === today.toDateString()) return '오늘';
  if (date.toDateString() === yesterday.toDateString()) return '어제';
  return date.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' });
}

/** Full Korean locale string (used in CrawlerManagement) */
export function formatDateFull(dateStr: string): string {
  return new Date(dateStr).toLocaleString('ko-KR');
}

/** HH:mm time display */
export function formatTime(dateStr: string): string {
  return new Date(dateStr).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
}
