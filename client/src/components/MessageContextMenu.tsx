import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
  ContextMenuSeparator,
} from '@/components/ui/context-menu';
import { Copy, Link, User } from 'lucide-react';
import { toast } from 'sonner';
import { Message, RegisteredGroup } from '@/lib/api';

interface MessageContextMenuProps {
  message: Message;
  group?: RegisteredGroup;
  children: React.ReactNode;
}

async function copyToClipboard(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${label} 복사되었습니다`);
  } catch {
    toast.error('복사에 실패했습니다');
  }
}

export default function MessageContextMenu({ message, group, children }: MessageContextMenuProps) {
  const copyText = () => {
    if (message.content) copyToClipboard(message.content, '텍스트가');
  };

  const copyLink = () => {
    let link: string;
    if (group?.username) {
      link = `https://t.me/${group.username}/${message.telegram_message_id}`;
    } else {
      const rawId = String(message.group_id).replace(/^-100/, '');
      link = `https://t.me/c/${rawId}/${message.telegram_message_id}`;
    }
    copyToClipboard(link, '메시지 링크가');
  };

  const copySender = () => {
    copyToClipboard(message.sender_name || 'Unknown', '발신자 이름이');
  };

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        {children}
      </ContextMenuTrigger>
      <ContextMenuContent className="w-48">
        <ContextMenuItem onClick={copyText} disabled={!message.content}>
          <Copy className="mr-2 h-4 w-4" />
          텍스트 복사
        </ContextMenuItem>
        <ContextMenuItem onClick={copyLink}>
          <Link className="mr-2 h-4 w-4" />
          메시지 링크 복사
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem onClick={copySender}>
          <User className="mr-2 h-4 w-4" />
          발신자 이름 복사
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
