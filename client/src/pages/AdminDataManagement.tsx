import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

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
  const [blacklistItems, setBlacklistItems] = useState<any[]>([]);

  const handleBulkRetry = async () => {
    try {
      // TODO: Implement API call
      // const result = await bulkRetryClassification({ confidence_threshold: 0.7 });
      // setRetryCount(result.requeued_count);
    } catch (error) {
      console.error('Error retrying classification:', error);
    }
  };

  const handleAddBlacklist = async () => {
    try {
      // TODO: Implement API call
      // await manageBlacklist({ action: 'add', pattern: blacklistUrl });
      setBlacklistUrl('');
      // Reload blacklist
    } catch (error) {
      console.error('Error adding to blacklist:', error);
    }
  };

  const handleExport = async () => {
    try {
      // TODO: Implement API call
      // const data = await exportData({ format: exportFormat });
      // Trigger download
      // const blob = new Blob([data], { type: 'text/csv' });
      // const url = window.URL.createObjectURL(blob);
      // const a = document.createElement('a');
      // a.href = url;
      // a.download = `export.${exportFormat}`;
      // a.click();
    } catch (error) {
      console.error('Error exporting data:', error);
    }
  };

  const handleCleanup = async (action: string) => {
    try {
      // TODO: Implement API call
      // await cleanupData({ action });
      alert(`Cleanup action "${action}" completed`);
    } catch (error) {
      console.error('Error cleaning up data:', error);
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
                      <Button size="sm" variant="destructive">
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
            <div className="flex gap-2">
              <select
                value={exportFormat}
                onChange={(e) => setExportFormat(e.target.value)}
                className="p-2 border rounded"
              >
                <option value="csv">CSV</option>
                <option value="json">JSON</option>
              </select>
              <Button onClick={handleExport}>Export All Data</Button>
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
              <Button
                variant="outline"
                onClick={() => handleCleanup('delete_old_messages')}
              >
                Delete Messages Older Than 90 Days
              </Button>
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
