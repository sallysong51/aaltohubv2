const BACKEND_URL = 'http://63.180.156.219:8000';

export default async function handler(req, res) {
  try {
    const { path } = req.query;
    
    // Build the path from the catch-all parameter
    const apiPath = Array.isArray(path) ? `/${path.join('/')}` : `/${path}`;
    
    // Build query string excluding the 'path' parameter
    const queryParams = { ...req.query };
    delete queryParams.path;
    const queryString = new URLSearchParams(queryParams).toString();
    
    // Construct target URL
    const targetUrl = `${BACKEND_URL}/api${apiPath}${queryString ? '?' + queryString : ''}`;
    console.log(`[Proxy] ${req.method} ${targetUrl}`);
    
    // Prepare headers
    const headers = {
      'Content-Type': 'application/json',
    };
    
    // Copy authorization header if present
    if (req.headers.authorization) {
      headers['Authorization'] = req.headers.authorization;
    }
    
    // Handle OPTIONS preflight
    if (req.method === 'OPTIONS') {
      res.setHeader('Access-Control-Allow-Origin', '*');
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
      return res.status(200).end();
    }
    
    // Forward request to backend
    const response = await fetch(targetUrl, {
      method: req.method,
      headers,
      body: req.method !== 'GET' && req.method !== 'HEAD' ? JSON.stringify(req.body) : undefined,
    });
    
    // Set CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    
    // Get response data
    const contentType = response.headers.get('content-type');
    
    if (contentType && contentType.includes('application/json')) {
      const data = await response.json();
      res.status(response.status).json(data);
    } else {
      const text = await response.text();
      res.status(response.status).send(text);
    }
  } catch (error) {
    console.error('[Proxy Error]:', error);
    res.status(500).json({
      error: 'Proxy error',
      message: error.message,
    });
  }
}
