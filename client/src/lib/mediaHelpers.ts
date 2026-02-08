/**
 * Shared media type helpers
 * Single source of truth for media icons and labels
 */

/** Korean labels for media types */
export function getMediaLabel(mediaType: string): string {
  switch (mediaType) {
    case 'document': return '문서';
    case 'video': return '비디오';
    case 'audio': return '오디오';
    case 'voice': return '음성 메시지';
    case 'sticker': return '스티커';
    case 'photo': return '이미지';
    default: return '미디어';
  }
}

/** Check if a URL is a valid HTTP(S) media URL */
export function isValidMediaUrl(url: string | null | undefined): boolean {
  return !!url && /^https?:\/\//i.test(url);
}
