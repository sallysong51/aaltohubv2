/**
 * Message Bubble Component
 * Telegram-style message display with media support
 */
import { Badge } from '@/components/ui/badge';
import { Image, File, Video, Music, Sticker, Mic, Reply } from 'lucide-react';
import { Message } from '@/lib/api';
import { formatTime } from '@/lib/dateFormat';
import { getMediaLabel, isValidMediaUrl } from '@/lib/mediaHelpers';

interface MessageBubbleProps {
  message: Message;
  onReplyClick?: (messageId: number) => void;
  onPhotoClick?: (messageId: number) => void;
}

export default function MessageBubble({ message, onReplyClick, onPhotoClick }: MessageBubbleProps) {
  const getMediaIcon = (mediaType: string) => {
    switch (mediaType) {
      case 'photo': return <Image className="h-3 w-3" />;
      case 'video': return <Video className="h-3 w-3" />;
      case 'document': return <File className="h-3 w-3" />;
      case 'audio': return <Music className="h-3 w-3" />;
      case 'sticker': return <Sticker className="h-3 w-3" />;
      case 'voice': return <Mic className="h-3 w-3" />;
      default: return null;
    }
  };

  const getSenderColor = (senderName: string) => {
    const colors = [
      'text-red-600',
      'text-blue-600',
      'text-green-600',
      'text-purple-600',
      'text-orange-600',
      'text-pink-600',
      'text-teal-600',
      'text-indigo-600',
    ];
    const hash = senderName.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
    return colors[hash % colors.length];
  };

  if (message.is_deleted) {
    return (
      <div className="py-1 px-3">
        <div className="text-xs text-muted-foreground italic">
          이 메시지는 삭제되었습니다
        </div>
      </div>
    );
  }

  return (
    <div className="py-1 px-3 hover:bg-accent/50 transition-colors group text-sm">
      {/* Sender name */}
      <div className={`font-semibold text-xs mb-0.5 ${getSenderColor(message.sender_name || 'Unknown')}`}>
        {message.sender_name || 'Unknown'}
      </div>

      {/* Reply reference */}
      {message.reply_to_message_id && (
        <div
          className="border-l-2 border-primary pl-2 mb-1 text-xs text-muted-foreground cursor-pointer hover:bg-accent/50 py-0.5"
          onClick={() => onReplyClick?.(message.reply_to_message_id!)}
        >
          <Reply className="h-2.5 w-2.5 inline mr-1" />
          답장
        </div>
      )}

      {/* Media preview */}
      {message.media_type && (
        <div className="mb-1">
          {message.media_type === 'photo' && isValidMediaUrl(message.media_url) && (
            <img
              src={message.media_url}
              alt="Media"
              className={`max-w-xs rounded border border-border mt-0.5 ${onPhotoClick ? 'cursor-pointer hover:opacity-80 transition-opacity' : ''}`}
              loading="lazy"
              onClick={onPhotoClick ? () => onPhotoClick(message.telegram_message_id) : undefined}
            />
          )}

          {message.media_type !== 'photo' && (
            <div className="flex items-center gap-1 p-1 bg-muted rounded border border-border max-w-xs">
              {getMediaIcon(message.media_type)}
              <div className="flex-1 truncate">
                <div className="font-medium text-xs">
                  {getMediaLabel(message.media_type)}
                </div>
                {isValidMediaUrl(message.media_url) && (
                  <a
                    href={message.media_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-primary hover:underline"
                  >
                    원본 보기
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Message content */}
      {message.content && (
        <div className="whitespace-pre-wrap break-words text-xs leading-relaxed">
          {message.content}
        </div>
      )}

      {/* Message footer */}
      <div className="flex items-center gap-1 mt-0.5">
        <span className="text-xs text-muted-foreground timestamp">
          {formatTime(message.sent_at)}
        </span>
      </div>
    </div>
  );
}
