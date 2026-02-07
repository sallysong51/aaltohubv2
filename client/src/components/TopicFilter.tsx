/**
 * Topic Filter Component
 * For Telegram supergroups with forum/topics enabled
 */
import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Hash } from 'lucide-react';
import apiClient from '@/lib/api';

interface Topic {
  topic_id: number;
  topic_title: string;
  message_count?: number;
}

interface TopicFilterProps {
  groupId: string;
  selectedTopicId: number | null;
  onTopicSelect: (topicId: number | null) => void;
}

export default function TopicFilter({ groupId, selectedTopicId, onTopicSelect }: TopicFilterProps) {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();

    const loadTopics = async () => {
      setIsLoading(true);
      try {
        const response = await apiClient.get(`/groups/${groupId}/topics`, {
          signal: controller.signal,
        });
        setTopics(response.data);
      } catch {
        if (!controller.signal.aborted) {
          setTopics([]);
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    };

    loadTopics();

    return () => controller.abort();
  }, [groupId]);

  if (topics.length === 0) {
    return null; // Don't show topic filter if no topics
  }

  return (
    <div className="border-b-2 border-border p-4">
      <div className="flex items-center gap-2 mb-3">
        <Hash className="h-4 w-4" />
        <span className="font-bold text-sm">토픽</span>
      </div>

      <ScrollArea className="h-32">
        <div className="space-y-1">
          <Button
            variant={selectedTopicId === null ? 'default' : 'ghost'}
            size="sm"
            className="w-full justify-start"
            onClick={() => onTopicSelect(null)}
          >
            전체 메시지
          </Button>

          {topics.map((topic) => (
            <Button
              key={topic.topic_id}
              variant={selectedTopicId === topic.topic_id ? 'default' : 'ghost'}
              size="sm"
              className="w-full justify-between"
              onClick={() => onTopicSelect(topic.topic_id)}
            >
              <span className="truncate">{topic.topic_title}</span>
              {topic.message_count != null && topic.message_count > 0 && (
                <Badge variant="outline" className="ml-2">
                  {topic.message_count}
                </Badge>
              )}
            </Button>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
