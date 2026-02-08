/**
 * Admin message viewer panel — extracted from AdminDashboard.
 * Displays chat header, topic filter, and message list with pagination.
 */
import { RefObject } from 'react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Loader2, Users, AlertCircle, RefreshCw } from 'lucide-react';
import { RegisteredGroup, Message } from '@/lib/api';
import MessageBubble from '@/components/MessageBubble';
import { formatDateShort } from '@/lib/dateFormat';
import TopicFilter from '@/components/TopicFilter';

interface AdminMessageViewerProps {
  selectedGroup: RegisteredGroup | null;
  messages: Message[];
  isLoadingMessages: boolean;
  page: number;
  hasMore: boolean;
  groupedMessages: { [key: string]: Message[] };
  selectedTopicId: number | null;
  setSelectedTopicId: (id: number | null) => void;
  onRefresh: () => void;
  onLoadMore: () => void;
  messagesEndRef: RefObject<HTMLDivElement | null>;
  scrollAreaRef: RefObject<HTMLDivElement | null>;
}

export default function AdminMessageViewer({
  selectedGroup,
  messages,
  isLoadingMessages,
  page,
  hasMore,
  groupedMessages,
  selectedTopicId,
  setSelectedTopicId,
  onRefresh,
  onLoadMore,
  messagesEndRef,
  scrollAreaRef,
}: AdminMessageViewerProps) {
  if (!selectedGroup) {
    return (
      <div className="flex-1 flex flex-col bg-background overflow-hidden">
        <div className="flex items-center justify-center h-full">
          <div className="text-center">
            <Users className="h-12 w-12 mx-auto mb-2 text-muted-foreground" />
            <p className="text-sm font-medium">그룹 선택</p>
            <p className="text-xs text-muted-foreground">
              왼쪽에서 그룹을 선택하세요
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-background overflow-hidden">
      {/* Chat Header */}
      <div className="p-2 border-b border-border bg-card flex-shrink-0">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <h2 className="font-bold text-sm truncate">{selectedGroup.title}</h2>
            {selectedGroup.username && (
              <p className="text-xs text-muted-foreground truncate">@{selectedGroup.username}</p>
            )}
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onRefresh}
            disabled={isLoadingMessages}
            className="h-7 px-2"
            title="새로고침"
          >
            <RefreshCw className={`h-3 w-3 mr-1 ${isLoadingMessages ? 'animate-spin' : ''}`} />
            <span className="text-xs">새로고침</span>
          </Button>
        </div>
        <div className="mt-1">
          <TopicFilter
            groupId={selectedGroup.id}
            selectedTopicId={selectedTopicId}
            onTopicSelect={(topicId: number | null) => {
              setSelectedTopicId(topicId);
              onRefresh();
            }}
          />
        </div>
      </div>

      {/* Messages Area */}
      <ScrollArea className="flex-1 min-h-0 px-2 py-1" ref={scrollAreaRef}>
        {isLoadingMessages && page === 1 ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <AlertCircle className="h-10 w-10 mx-auto mb-2 text-muted-foreground" />
              <p className="text-sm font-medium">메시지 없음</p>
              <p className="text-xs text-muted-foreground">
                이 그룹에 메시지가 없습니다
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-0.5">
            {hasMore && (
              <div className="text-center py-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={onLoadMore}
                  disabled={isLoadingMessages}
                  className="h-6 text-xs border border-border"
                >
                  {isLoadingMessages ? (
                    <>
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                      로딩
                    </>
                  ) : (
                    '이전 메시지'
                  )}
                </Button>
              </div>
            )}

            {Object.entries(groupedMessages).map(([dateKey, msgs]) => (
              <div key={dateKey}>
                <div className="flex items-center justify-center py-2">
                  <div className="px-2 py-0.5 bg-muted rounded text-xs text-muted-foreground font-medium">
                    {formatDateShort(msgs[0].sent_at)}
                  </div>
                </div>

                <div className="border border-border rounded divide-y divide-border">
                  {msgs.map((message) => (
                    <MessageBubble
                      key={message.id ?? `${message.telegram_message_id}-${message.group_id}`}
                      message={message}
                      onReplyClick={(replyId) => {
                        const element = document.querySelector(`[data-message-id="${replyId}"]`);
                        element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                      }}
                    />
                  ))}
                </div>
              </div>
            ))}

            <div ref={messagesEndRef} />
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
