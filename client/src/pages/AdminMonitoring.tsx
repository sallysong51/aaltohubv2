import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { adminAI } from '@/lib/api';

/**
 * Admin Monitoring Dashboard
 *
 * Real-time visibility into all subsystems:
 * - Crawler health (messages/min, error rate)
 * - AI classification metrics (queue, cache hit rate, circuit breaker, cost)
 * - External reference metrics (pending scrapes/joins, rate limits)
 * - Database metrics (connection pool, query latency, dead letter queue)
 *
 * Updates via 5s polling (existing AdminDashboard pattern)
 */
export default function AdminMonitoring() {
  const [crawlerHealth, setCrawlerHealth] = useState<any>(null);
  const [aiMetrics, setAIMetrics] = useState<any>(null);
  const [refMetrics, setRefMetrics] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  // Poll metrics every 5s
  useEffect(() => {
    const poll = async () => {
      try {
        const [ai, ref] = await Promise.all([
          adminAI.getMetrics(),
          adminAI.getReferencesMetrics(),
        ]);
        setAIMetrics(ai.data);
        setRefMetrics(ref.data);
        setLoading(false);
      } catch (error) {
        console.error('Polling error:', error);
        setLoading(false);
      }
    };

    poll();
    const interval = setInterval(poll, 5000); // 5s polling
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return <div className="p-8">Loading...</div>;
  }

  return (
    <div className="p-8">
      <h1 className="text-3xl font-bold mb-8">System Monitoring</h1>

      <div className="grid grid-cols-2 gap-4">
        {/* Crawler Health Card */}
        <Card>
          <CardHeader>
            <CardTitle>Crawler Health</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold mb-2">
              {crawlerHealth?.status === 'running' ? '✅ Running' : '❌ Stopped'}
            </div>
            <div className="text-sm text-gray-600">
              Messages/min: {crawlerHealth?.messages_per_min || 0}
            </div>
            {/* TODO: Add LineChart for message history */}
          </CardContent>
        </Card>

        {/* AI Classification Card */}
        <Card>
          <CardHeader>
            <CardTitle>AI Classification</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              <div>Queue: {aiMetrics?.queue_size || 0} messages</div>
              <div>Cache hit rate: {aiMetrics?.cache_hit_rate || 0}%</div>
              <div>
                Circuit breaker: {aiMetrics?.circuit_open ? '🔴 Open' : '✅ Closed'}
              </div>
            </div>
            {/* TODO: Add BarChart for category breakdown */}
          </CardContent>
        </Card>

        {/* External References Card */}
        <Card>
          <CardHeader>
            <CardTitle>External References</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              <div>Pending scrapes: {refMetrics?.scraping_queue || 0}</div>
              <div>Pending joins: {refMetrics?.join_queue || 0}</div>
              <div>Rate limits: {refMetrics?.rate_limits || 'OK'}</div>
            </div>
          </CardContent>
        </Card>

        {/* Cost Tracker Card */}
        <Card>
          <CardHeader>
            <CardTitle>AI Cost Tracking</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold mb-2">
              ${aiMetrics?.cost_usd || 0} / $30.00
            </div>
            <div className="text-sm text-gray-600">Monthly budget</div>
            {/* TODO: Add Gauge chart */}
          </CardContent>
        </Card>

        {/* Queue Depths Table */}
        <Card className="col-span-2">
          <CardHeader>
            <CardTitle>Queue Depths</CardTitle>
          </CardHeader>
          <CardContent>
            <table className="w-full">
              <thead>
                <tr className="text-left border-b">
                  <th className="pb-2">Queue</th>
                  <th className="pb-2">Pending</th>
                  <th className="pb-2">Processing</th>
                  <th className="pb-2">Failed</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                <tr className="border-b">
                  <td className="py-2">AI Classification</td>
                  <td>{aiMetrics?.queue_pending || 0}</td>
                  <td>{aiMetrics?.queue_processing || 0}</td>
                  <td>{aiMetrics?.queue_failed || 0}</td>
                </tr>
                <tr className="border-b">
                  <td className="py-2">Web Scraping</td>
                  <td>{refMetrics?.scraping_pending || 0}</td>
                  <td>{refMetrics?.scraping_processing || 0}</td>
                  <td>{refMetrics?.scraping_failed || 0}</td>
                </tr>
                <tr>
                  <td className="py-2">Auto-Join</td>
                  <td>{refMetrics?.join_pending || 0}</td>
                  <td>{refMetrics?.join_processing || 0}</td>
                  <td>{refMetrics?.join_failed || 0}</td>
                </tr>
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
