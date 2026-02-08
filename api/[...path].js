const BACKEND_URL = process.env.BACKEND_URL || '';

if (!BACKEND_URL) {
  console.error('[Proxy] BACKEND_URL environment variable is not set');
}

const ALLOWED_ORIGINS = [
  'https://aaltohub.vercel.app',
  'https://aaltohub.com',
  'http://localhost:5173',
  'http://localhost:3000',
];

function getCorsOrigin(req) {
  const origin = req.headers.origin;
  if (origin && ALLOWED_ORIGINS.includes(origin)) return origin;
  return ALLOWED_ORIGINS[0];
}

function setCorsHeaders(req, res) {
  res.setHeader('Access-Control-Allow-Origin', getCorsOrigin(req));
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  res.setHeader('Vary', 'Origin');
}

export default async function handler(req, res) {
  if (!BACKEND_URL) {
    return res.status(503).json({ error: 'Backend URL not configured' });
  }

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
      setCorsHeaders(req, res);
      return res.status(200).end();
    }

    // Forward request to backend (25s timeout — must exceed DB command_timeout of 10s)
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25000);
    const response = await fetch(targetUrl, {
      method: req.method,
      headers,
      body: req.method !== 'GET' && req.method !== 'HEAD' ? JSON.stringify(req.body) : undefined,
      signal: controller.signal,
    });
    clearTimeout(timeout);

    // Set CORS headers
    setCorsHeaders(req, res);

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
    console.error('[Proxy Error]:', error.message);
    res.status(502).json({
      error: 'Service unavailable',
    });
  }
}
