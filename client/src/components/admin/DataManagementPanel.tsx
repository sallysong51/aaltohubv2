import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { Loader2, Download } from 'lucide-react';
import { adminApi, RegisteredGroup, Message, getApiErrorMessage } from '@/lib/api';

interface DataManagementPanelProps {
  groups: RegisteredGroup[];
}

function calculateDays(start: string, end: string): number {
  const startDate = new Date(start);
  const endDate = new Date(end);
  const diffTime = Math.abs(endDate.getTime() - startDate.getTime());
  return Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1;
}

export function DataManagementPanel({ groups }: DataManagementPanelProps) {
  const [selectedGroupId, setSelectedGroupId] = useState<string>('');
  const [startDate, setStartDate] = useState<string>('');
  const [endDate, setEndDate] = useState<string>(new Date().toISOString().split('T')[0]);
  const [format, setFormat] = useState<'json' | 'csv'>('json');
  const [messageCount, setMessageCount] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [exportProgress, setExportProgress] = useState({ loaded: 0, total: 0 });

  const handleQueryMessages = async () => {
    if (!selectedGroupId || !startDate || !endDate) {
      toast.error('모든 필드를 입력하세요');
      return;
    }

    if (new Date(startDate) > new Date(endDate)) {
      toast.error('시작일이 종료일보다 늦습니다');
      return;
    }

    setIsLoading(true);
    try {
      const days = calculateDays(startDate, endDate);

      // Fetch first page to get total count
      const res = await adminApi.getGroupMessages(selectedGroupId, 1, 1, days, null);
      setMessageCount(res.data.total);

      if (res.data.total === 0) {
        toast.info('선택한 기간에 메시지가 없습니다');
      } else {
        toast.success(`총 ${res.data.total.toLocaleString()}개 메시지를 찾았습니다`);
      }
    } catch (error) {
      toast.error(getApiErrorMessage(error, '조회 실패'));
    } finally {
      setIsLoading(false);
    }
  };

  const fetchAllMessages = async (
    groupId: string,
    days: number,
    onProgress: (loaded: number, total: number) => void
  ): Promise<Message[]> => {
    let allMessages: Message[] = [];
    let page = 1;
    let hasMore = true;
    let total = 0;

    while (hasMore) {
      let retries = 0;
      const MAX_RETRIES = 3;

      while (retries < MAX_RETRIES) {
        try {
          const res = await adminApi.getGroupMessages(groupId, page, 100, days, null);
          allMessages = allMessages.concat(res.data.messages);
          total = res.data.total;
          hasMore = res.data.has_more;
          page++;

          onProgress(allMessages.length, total);
          break; // Exit retry loop on success
        } catch (error) {
          retries++;
          if (retries >= MAX_RETRIES) {
            throw new Error(`페이지 ${page} 로드 실패 (${MAX_RETRIES}회 재시도 후)`);
          }
          console.warn(`페이지 ${page} 로드 실패, 재시도 ${retries}/${MAX_RETRIES}...`);
          await new Promise(resolve => setTimeout(resolve, 1000 * retries));
        }
      }

      // Safety limit: 100k messages
      if (allMessages.length >= 100000) {
        toast.warning('메시지가 10만 개를 초과하여 중단되었습니다. 날짜 범위를 줄여주세요.');
        break;
      }
    }

    return allMessages;
  };

  const generateJSON = (
    messages: Message[],
    groupTitle: string,
    startDate: string,
    endDate: string
  ): string => {
    const output = {
      metadata: {
        group: groupTitle,
        date_range: {
          start: startDate,
          end: endDate,
        },
        exported_at: new Date().toISOString(),
        message_count: messages.length,
      },
      messages: messages.map(m => ({
        telegram_message_id: m.telegram_message_id,
        timestamp: m.sent_at,
        sender_id: m.sender_id,
        sender_name: m.sender_name,
        content: m.content,
        media_type: m.media_type,
        media_url: m.media_url,
        topic_id: m.topic_id,
        reply_to: m.reply_to_message_id,
        links: m.links,
        mentions: m.mentions,
      })),
    };

    return JSON.stringify(output, null, 2);
  };

  const downloadFile = (content: string, filename: string, mimeType: string) => {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const sanitizeFilename = (name: string): string => {
    return name.replace(/[<>:"/\\|?*]/g, '_').substring(0, 200);
  };

  const escapeCSV = (str: string): string => {
    if (!str) return '';
    if (str.includes(',') || str.includes('"') || str.includes('\n')) {
      return `"${str.replace(/"/g, '""')}"`;
    }
    return str;
  };

  const generateCSV = (messages: Message[]): string => {
    const headers = [
      'telegram_message_id',
      'timestamp',
      'sender_id',
      'sender_name',
      'content',
      'media_type',
      'media_url',
      'topic_id',
      'reply_to',
      'links',
      'mentions',
    ];

    const rows = messages.map(m => [
      m.telegram_message_id?.toString() || '',
      m.sent_at || '',
      m.sender_id?.toString() || '',
      escapeCSV(m.sender_name || ''),
      escapeCSV(m.content || ''),
      m.media_type || '',
      m.media_url || '',
      m.topic_id?.toString() || '',
      m.reply_to_message_id?.toString() || '',
      JSON.stringify(m.links || []),
      JSON.stringify(m.mentions || []),
    ].join(','));

    return [headers.join(','), ...rows].join('\n');
  };

  const handleExport = async () => {
    if (!selectedGroupId || messageCount === null) return;

    // Validation
    if (messageCount === 0) {
      toast.error('다운로드할 메시지가 없습니다');
      return;
    }

    if (messageCount > 100000) {
      const confirmed = window.confirm(
        `메시지가 ${messageCount.toLocaleString()}개로 매우 많습니다. 날짜 범위를 줄이는 것을 권장합니다. 계속하시겠습니까?`
      );
      if (!confirmed) return;
    }

    setIsExporting(true);
    try {
      const group = groups.find(g => g.id === selectedGroupId)!;
      const days = calculateDays(startDate, endDate);

      // Fetch all messages
      const messages = await fetchAllMessages(selectedGroupId, days, (loaded, total) => {
        setExportProgress({ loaded, total });
      });

      if (messages.length === 0) {
        toast.error('메시지를 가져오지 못했습니다');
        return;
      }

      // Generate file
      let content: string;
      let filename: string;
      let mimeType: string;

      if (format === 'json') {
        content = generateJSON(messages, group.title, startDate, endDate);
        filename = sanitizeFilename(`${group.title}_${startDate}_${endDate}.json`);
        mimeType = 'application/json;charset=utf-8';
      } else {
        content = generateCSV(messages);
        filename = sanitizeFilename(`${group.title}_${startDate}_${endDate}.csv`);
        mimeType = 'text/csv;charset=utf-8';
      }

      // Download
      downloadFile(content, filename, mimeType);
      toast.success('다운로드 완료');
    } catch (error) {
      toast.error(getApiErrorMessage(error, '다운로드 실패'));
    } finally {
      setIsExporting(false);
      setExportProgress({ loaded: 0, total: 0 });
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h2 className="text-2xl font-bold mb-2">데이터 관리</h2>
        <p className="text-muted-foreground">
          그룹 메시지를 JSON 또는 CSV 파일로 다운로드하세요.
        </p>
      </div>

      {/* Group Selection */}
      <div>
        <label className="block text-sm font-medium mb-2">그룹 선택</label>
        <select
          value={selectedGroupId}
          onChange={(e) => setSelectedGroupId(e.target.value)}
          className="w-full p-2 border rounded bg-background text-foreground"
        >
          <option value="">그룹을 선택하세요...</option>
          {groups.map(g => (
            <option key={g.id} value={g.id}>{g.title}</option>
          ))}
        </select>
      </div>

      {/* Date Range */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-2">시작일</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            max={endDate}
            className="w-full p-2 border rounded bg-background text-foreground"
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-2">종료일</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            min={startDate}
            max={new Date().toISOString().split('T')[0]}
            className="w-full p-2 border rounded bg-background text-foreground"
          />
        </div>
      </div>

      {/* Query Button */}
      <Button
        onClick={handleQueryMessages}
        disabled={!selectedGroupId || !startDate || !endDate || isLoading || isExporting}
      >
        {isLoading ? (
          <>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            조회 중...
          </>
        ) : (
          '조회'
        )}
      </Button>

      {/* Message Count Display */}
      {messageCount !== null && (
        <div className="border rounded p-4 bg-muted/30">
          <p className="font-bold">총 {messageCount.toLocaleString()}개 메시지</p>
        </div>
      )}

      {/* Format Selection */}
      {messageCount !== null && (
        <div>
          <label className="block text-sm font-medium mb-2">다운로드 형식</label>
          <div className="flex gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                checked={format === 'json'}
                onChange={() => setFormat('json')}
                className="cursor-pointer"
              />
              <span>JSON (프로그래밍 친화적)</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                checked={format === 'csv'}
                onChange={() => setFormat('csv')}
                className="cursor-pointer"
              />
              <span>CSV (엑셀)</span>
            </label>
          </div>
        </div>
      )}

      {/* Progress Bar */}
      {isExporting && (
        <div className="border rounded p-4 space-y-2">
          <div className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>메시지 로드 중... ({exportProgress.loaded.toLocaleString()}/{exportProgress.total.toLocaleString()})</span>
          </div>
          <div className="w-full bg-muted rounded h-2">
            <div
              className="bg-primary h-2 rounded transition-all"
              style={{
                width: `${exportProgress.total > 0 ? (exportProgress.loaded / exportProgress.total) * 100 : 0}%`
              }}
            />
          </div>
        </div>
      )}

      {/* Download Button */}
      {messageCount !== null && (
        <Button onClick={handleExport} disabled={isExporting}>
          {isExporting ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              다운로드 중...
            </>
          ) : (
            <>
              <Download className="h-4 w-4 mr-2" />
              다운로드
            </>
          )}
        </Button>
      )}
    </div>
  );
}
