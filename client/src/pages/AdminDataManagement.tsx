import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { adminAI } from '@/lib/api';

/**
 * Admin Data Management Dashboard
 *
 * Bulk operations and data cleanup:
 * - Bulk classification retry (re-run AI on failed/low-confidence messages)
 * - Blacklist management (add/remove URLs/groups from crawl blacklist)
 * - Queue management (clear/reset scraping/join queues)
 * - Export (export messages, classifications, contexts to CSV/JSON)
 * - Cleanup (delete old messages, trim queues, vacuum tables)
 */
export default function AdminDataManagement() {
  const [retryCount, setRetryCount] = useState<number>(0);
  const [blacklistUrl, setBlacklistUrl] = useState<string>('');
  const [exportFormat, setExportFormat] = useState<string>('csv');
  const [exportDays, setExportDays] = useState<number>(30);
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [blacklistItems, setBlacklistItems] = useState<any[]>([]);

  // Load blacklist on mount
  useEffect(() => {
    loadBlacklist();
  }, []);

  const loadBlacklist = async () => {
    try {
      const response = await adminAI.listBlacklist();
      setBlacklistItems(response.data);
    } catch (error) {
      console.error('Error loading blacklist:', error);
    }
  };

  const handleBulkRetry = async () => {
    try {
      const result = await adminAI.bulkRetryClassification({ confidence_threshold: 0.7 });
      setRetryCount(result.data.requeued_count);
    } catch (error) {
      console.error('Error retrying classification:', error);
      alert('Failed to retry classification');
    }
  };

  const handleAddBlacklist = async () => {
    try {
      if (!blacklistUrl.trim()) return;
      await adminAI.addBlacklist({ pattern: blacklistUrl });
      setBlacklistUrl('');
      await loadBlacklist();
    } catch (error) {
      console.error('Error adding to blacklist:', error);
      alert('Failed to add to blacklist');
    }
  };

  const handleRemoveBlacklist = async (blacklistId: string) => {
    try {
      await adminAI.removeBlacklist(blacklistId);
      await loadBlacklist();
    } catch (error) {
      console.error('Error removing from blacklist:', error);
      alert('Failed to remove from blacklist');
    }
  };

  const handleExport = async () => {
    try {
      setIsExporting(true);

      const response = await adminAI.exportData({
        format: exportFormat as 'csv' | 'json',
        days: exportDays,
      });

      // Create blob and trigger download
      const blob = new Blob([response.data], { type: 'text/csv' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `messages_${exportDays}days.${exportFormat}`;
      document.body.appendChild(a);  // Firefox requires DOM append
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

      alert('Export completed successfully');
    } catch (error) {
      console.error('Error exporting data:', error);
      alert('Failed to export data. Please try again.');
    } finally {
      setIsExporting(false);
    }
  };

  const handleCleanup = async (action: string) => {
    try {
      const result = await adminAI.cleanupData({ action: action as any });
      const message = result.data.message ||
        `Cleanup completed: ${result.data.deleted || result.data.deleted_scraping || 0} items`;
      alert(message);
    } catch (error) {
      console.error('Error cleaning up data:', error);
      alert('Failed to cleanup data');
    }
  };

  return (
    <div className="p-8">
      <h1 className="text-3xl font-bold mb-8">Data Management</h1>

      <div className="grid gap-4">
        {/* Bulk Retry Card */}
        <Card>
          <CardHeader>
            <CardTitle>Bulk Classification Retry</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-gray-600 mb-4">
              Re-run AI classification on messages with confidence &lt; 70%
            </p>
            <Button onClick={handleBulkRetry}>
              Retry Low-Confidence Messages
            </Button>
            {retryCount > 0 && (
              <div className="mt-2 text-green-600">
                Requeued {retryCount} messages
              </div>
            )}
          </CardContent>
        </Card>

        {/* Blacklist Management Card */}
        <Card>
          <CardHeader>
            <CardTitle>Crawl Blacklist</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex gap-2 mb-4">
              <input
                type="text"
                placeholder="URL or pattern to blacklist..."
                value={blacklistUrl}
                onChange={(e) => setBlacklistUrl(e.target.value)}
                className="flex-1 p-2 border rounded"
              />
              <Button onClick={handleAddBlacklist}>Add</Button>
            </div>

            <table className="w-full text-sm">
              <thead>
                <tr className="text-left border-b">
                  <th className="pb-2">Pattern</th>
                  <th className="pb-2">Reason</th>
                  <th className="pb-2">Added</th>
                  <th className="pb-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {blacklistItems.map((item) => (
                  <tr key={item.id} className="border-b">
                    <td className="py-2">{item.pattern}</td>
                    <td>{item.reason}</td>
                    <td>{new Date(item.added_at).toLocaleDateString()}</td>
                    <td>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => handleRemoveBlacklist(item.id)}
                      >
                        Remove
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        {/* Export Card */}
        <Card>
          <CardHeader>
            <CardTitle>Data Export</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-gray-600 mb-4">
              Export messages to CSV (gzip compressed by server)
            </p>
            <div className="flex flex-col gap-3">
              <div className="flex gap-2">
                <select
                  value={exportFormat}
                  onChange={(e) => setExportFormat(e.target.value)}
                  className="p-2 border rounded"
                  disabled={isExporting}
                >
                  <option value="csv">CSV</option>
                  <option value="json">JSON (not supported yet)</option>
                </select>
                <select
                  value={exportDays}
                  onChange={(e) => setExportDays(Number(e.target.value))}
                  className="p-2 border rounded"
                  disabled={isExporting}
                >
                  <option value={7}>최근 7일</option>
                  <option value={30}>최근 30일</option>
                  <option value={90}>최근 90일</option>
                  <option value={365}>최근 1년</option>
                </select>
                <Button onClick={handleExport} disabled={isExporting}>
                  {isExporting ? 'Exporting...' : 'Export Data'}
                </Button>
              </div>
              {isExporting && (
                <div className="text-sm text-blue-600">
                  Exporting... This may take a few minutes for large datasets.
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Cleanup Card */}
        <Card>
          <CardHeader>
            <CardTitle>Database Cleanup</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-2">
              {/* DISABLED: Message deletion disabled - messages kept permanently
              <Button
                variant="outline"
                onClick={() => handleCleanup('delete_old_messages')}
              >
                Delete Messages Older Than 90 Days
              </Button>
              */}
              <Button
                variant="outline"
                onClick={() => handleCleanup('clear_failed_queues')}
              >
                Clear Failed Queue Items
              </Button>
              <Button
                variant="outline"
                onClick={() => handleCleanup('vacuum')}
              >
                Vacuum Database Tables
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
