import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

/**
 * Admin AI Lab Dashboard
 *
 * Prompt experimentation and version management:
 * - Prompt editor (create/edit/test prompts)
 * - Version history (with performance metrics)
 * - A/B testing (compare two prompt versions)
 * - Activation (set active prompt version)
 * - Test playground (test prompts on sample messages)
 */
export default function AdminAILab() {
  const [prompts, setPrompts] = useState<any[]>([]);
  const [selectedType, setSelectedType] = useState<string>('classification');
  const [editorContent, setEditorContent] = useState<string>('');
  const [testMessage, setTestMessage] = useState<string>('');
  const [testResult, setTestResult] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadPrompts();
  }, [selectedType]);

  const loadPrompts = async () => {
    try {
      // TODO: Implement API call
      // const data = await getPrompts(selectedType);
      // setPrompts(data);
      setLoading(false);
    } catch (error) {
      console.error('Error loading prompts:', error);
    }
  };

  const handleSave = async () => {
    try {
      // TODO: Implement API call
      // await createPrompt({
      //   name: `${selectedType}_v${prompts.length + 1}`,
      //   type: selectedType,
      //   content: editorContent
      // });
      await loadPrompts();
    } catch (error) {
      console.error('Error saving prompt:', error);
    }
  };

  const handleActivate = async (promptId: string) => {
    try {
      // TODO: Implement API call
      // await activatePrompt(promptId);
      await loadPrompts();
    } catch (error) {
      console.error('Error activating prompt:', error);
    }
  };

  const handleTest = async () => {
    try {
      // TODO: Implement API call
      // const result = await testPrompt({
      //   prompt_content: editorContent,
      //   test_message: testMessage
      // });
      // setTestResult(result);
    } catch (error) {
      console.error('Error testing prompt:', error);
    }
  };

  if (loading) {
    return <div className="p-8">Loading...</div>;
  }

  return (
    <div className="p-8">
      <h1 className="text-3xl font-bold mb-8">AI Lab</h1>

      <div className="grid grid-cols-2 gap-4">
        {/* Prompt Type Selector */}
        <Card className="col-span-2">
          <CardHeader>
            <CardTitle>Prompt Type</CardTitle>
          </CardHeader>
          <CardContent>
            <select
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value)}
              className="w-full p-2 border rounded"
            >
              <option value="classification">Classification</option>
              <option value="extraction">Event Extraction</option>
              <option value="hidden_cost">Hidden Cost Detection</option>
            </select>
          </CardContent>
        </Card>

        {/* Prompt Editor */}
        <Card>
          <CardHeader>
            <CardTitle>Prompt Editor</CardTitle>
          </CardHeader>
          <CardContent>
            <textarea
              value={editorContent}
              onChange={(e) => setEditorContent(e.target.value)}
              className="w-full h-96 p-4 border rounded font-mono text-sm"
              placeholder="Enter prompt content..."
            />
            <Button onClick={handleSave} className="mt-4">
              Save New Version
            </Button>
          </CardContent>
        </Card>

        {/* Test Playground */}
        <Card>
          <CardHeader>
            <CardTitle>Test Playground</CardTitle>
          </CardHeader>
          <CardContent>
            <textarea
              placeholder="Enter test message..."
              value={testMessage}
              onChange={(e) => setTestMessage(e.target.value)}
              className="w-full h-48 p-4 border rounded text-sm"
            />
            <Button onClick={handleTest} className="mt-4">
              Test Prompt
            </Button>

            {testResult && (
              <div className="mt-4 p-4 bg-gray-100 rounded">
                <h4 className="font-semibold mb-2">Result:</h4>
                <pre className="text-xs overflow-auto">
                  {JSON.stringify(testResult, null, 2)}
                </pre>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Version History */}
        <Card className="col-span-2">
          <CardHeader>
            <CardTitle>Version History</CardTitle>
          </CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left border-b">
                  <th className="pb-2">Version</th>
                  <th className="pb-2">Created</th>
                  <th className="pb-2">Active</th>
                  <th className="pb-2">Avg Confidence</th>
                  <th className="pb-2">Messages Processed</th>
                  <th className="pb-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {prompts.map((prompt) => (
                  <tr key={prompt.id} className="border-b">
                    <td className="py-2">{prompt.version}</td>
                    <td>{new Date(prompt.created_at).toLocaleString()}</td>
                    <td>{prompt.is_active ? '✅' : ''}</td>
                    <td>{prompt.avg_confidence}%</td>
                    <td>{prompt.messages_processed}</td>
                    <td className="space-x-2">
                      <Button
                        size="sm"
                        onClick={() => handleActivate(prompt.id)}
                        disabled={prompt.is_active}
                      >
                        Activate
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setEditorContent(prompt.content)}
                      >
                        Load
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        {/* A/B Test Comparison (Placeholder) */}
        <Card className="col-span-2">
          <CardHeader>
            <CardTitle>A/B Test Comparison</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <h4 className="font-semibold mb-2">Prompt A</h4>
                {/* TODO: Add BarChart for version A stats */}
                <p className="text-sm text-gray-600">Select version to compare</p>
              </div>
              <div>
                <h4 className="font-semibold mb-2">Prompt B</h4>
                {/* TODO: Add BarChart for version B stats */}
                <p className="text-sm text-gray-600">Select version to compare</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
