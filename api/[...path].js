// Vercel Serverless Function - API Proxy
// Catches all /api/* routes and proxies to backend

const BACKEND_URL = 'http://63.180.156.219:8000';

export default async function handler(req, res) {
  // Enable CORS
  res.setHeader('Access-Control-Allow-Credentials', 'true');
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS,PATCH,DELETE,POST,PUT');
  res.setHeader(
    'Access-Control-Allow-Headers',
    'X-CSRF-Token, X-Requested-With, Accept, Accept-Version, Content-Length, Content-MD5, Content-Type, Date, X-Api-Version, Authorization'
  );

  // Handle preflight
  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  try {
    // Get path from query parameters (Vercel dynamic route)
    const pathArray = req.query.path || [];
    const path = Array.isArray(pathArray) ? `/${pathArray.join('/')}` : `/${pathArray}`;
    
    // Construct target URL with query string
    const queryString = new URLSearchParams(req.query).toString();
    const targetUrl = `${BACKEND_URL}${path}${queryString ? `?${queryString}` : ''}`;

    console.log(`[Proxy] ${req.method} ${targetUrl}`);

    // Prepare headers
    const headers = {
      'Content-Type': 'application/json',
    };

    // Copy authorization header if present
    if (req.headers.authorization) {
      headers['Authorization'] = req.headers.authorization;
    }

    // Forward request to backend
    const response = await fetch(targetUrl, {
      method: req.method,
      headers,
      body: req.method !== 'GET' && req.method !== 'HEAD' ? JSON.stringify(req.body) : undefined,
    });

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
