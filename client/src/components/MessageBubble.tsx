/**
 * Message Bubble Component
 * Telegram-style message display with media support
 */
import { Badge } from '@/components/ui/badge';
import { Image, File, Video, Music, Sticker, Mic, Reply } from 'lucide-react';
import { Message } from '@/lib/api';

interface MessageBubbleProps {
  message: Message;
  onReplyClick?: (messageId: number) => void;
}

export default function MessageBubble({ message, onReplyClick }: MessageBubbleProps) {
  const formatTime = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
  };

  const getMediaIcon = (mediaType: string) => {
    switch (mediaType) {
      case 'photo':
        return <Image className="h-4 w-4" />;
      case 'video':
        return <Video className="h-4 w-4" />;
      case 'document':
        return <File className="h-4 w-4" />;
      case 'audio':
        return <Music className="h-4 w-4" />;
      case 'sticker':
        return <Sticker className="h-4 w-4" />;
      case 'voice':
        return <Mic className="h-4 w-4" />;
      default:
        return null;
    }
  };

  const getSenderColor = (senderName: string) => {
    // Generate consistent color based on sender name
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
      <div className="py-2 px-4 my-1">
        <div className="text-sm text-muted-foreground italic">
          이 메시지는 삭제되었습니다
        </div>
      </div>
    );
  }

  return (
    <div className="py-2 px-4 hover:bg-accent/30 transition-colors group">
      {/* Sender name */}
      <div className={`font-bold text-sm mb-1 ${getSenderColor(message.sender_name || 'Unknown')}`}>
        {message.sender_name || 'Unknown'}
        {message.sender_username && (
          <span className="text-muted-foreground font-normal ml-2">
            @{message.sender_username}
          </span>
        )}
      </div>

      {/* Reply reference */}
      {message.reply_to_message_id && (
        <div
          className="border-l-2 border-primary pl-2 mb-2 text-sm text-muted-foreground cursor-pointer hover:bg-accent/50 py-1"
          onClick={() => onReplyClick?.(message.reply_to_message_id!)}
        >
          <Reply className="h-3 w-3 inline mr-1" />
          답장
        </div>
      )}

      {/* Media preview */}
      {message.media_type !== 'text' && (
        <div className="mb-2">
          {message.media_thumbnail_url && message.media_type === 'photo' && (
            <img
              src={message.media_thumbnail_url}
              alt="Media"
              className="max-w-sm rounded border-2 border-border"
            />
          )}
          
          {message.media_type !== 'photo' && (
            <div className="flex items-center gap-2 p-2 bg-muted rounded border-2 border-border max-w-sm">
              {getMediaIcon(message.media_type)}
              <div className="flex-1 truncate">
                <div className="font-medium text-sm">
                  {message.media_type === 'document' ? '문서' :
                   message.media_type === 'video' ? '비디오' :
                   message.media_type === 'audio' ? '오디오' :
                   message.media_type === 'voice' ? '음성 메시지' :
                   message.media_type === 'sticker' ? '스티커' : '미디어'}
                </div>
                {message.media_url && (
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
        <div className="text-sm whitespace-pre-wrap break-words">
          {message.content}
        </div>
      )}

      {/* Message footer */}
      <div className="flex items-center gap-2 mt-1">
        <span className="text-xs text-muted-foreground timestamp">
          {formatTime(message.sent_at)}
        </span>
        
        {message.edited_at && (
          <Badge variant="outline" className="text-xs">
            수정됨
          </Badge>
        )}
        
        {message.topic_title && (
          <Badge variant="secondary" className="text-xs">
            #{message.topic_title}
          </Badge>
        )}
      </div>
    </div>
  );
}
