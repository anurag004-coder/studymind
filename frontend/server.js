/**
 * StudyMind Frontend Development Server
 * Ultra-fast zero-dependency Node HTTP server with static serving & API proxying.
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const PORT = process.env.PORT || 3000;
const BACKEND_URL = process.env.API_URL || 'http://127.0.0.1:8000';

const MIME_TYPES = {
  '.html': 'text/html',
  '.css': 'text/css',
  '.js': 'application/javascript',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

const server = http.createServer((req, res) => {
  const parsedUrl = url.parse(req.url);
  const pathname = parsedUrl.pathname;

  // 1. Proxy API requests to FastAPI backend
  if (pathname.startsWith('/api/v1')) {
    const backendTarget = new URL(pathname + (parsedUrl.search || ''), BACKEND_URL);
    const proxyReq = http.request(
      backendTarget,
      {
        method: req.method,
        headers: {
          ...req.headers,
          host: backendTarget.host,
        },
      },
      (proxyRes) => {
        res.writeHead(proxyRes.statusCode, proxyRes.headers);
        proxyRes.pipe(res);
      }
    );

    proxyReq.on('error', (err) => {
      console.error('API Proxy error:', err.message);
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: { message: 'Failed to connect to backend server' } }));
    });

    req.pipe(proxyReq);
    return;
  }

  // 2. Static File Serving
  let relativePath = pathname === '/' || pathname === '/app' ? '/index.html' : pathname;
  if (relativePath.startsWith('/static/')) {
    relativePath = relativePath.replace('/static/', '/');
  }

  const filePath = path.join(__dirname, relativePath);
  const ext = path.extname(filePath).toLowerCase();
  const contentType = MIME_TYPES[ext] || 'application/octet-stream';

  fs.readFile(filePath, (err, content) => {
    if (err) {
      if (err.code === 'ENOENT') {
        // Fallback to index.html for SPA routing
        fs.readFile(path.join(__dirname, 'index.html'), (spaErr, spaContent) => {
          if (spaErr) {
            res.writeHead(404, { 'Content-Type': 'text/plain' });
            res.end('404 Not Found');
          } else {
            res.writeHead(200, { 'Content-Type': 'text/html' });
            res.end(spaContent, 'utf-8');
          }
        });
      } else {
        res.writeHead(500, { 'Content-Type': 'text/plain' });
        res.end(`Server Error: ${err.code}`);
      }
    } else {
      res.writeHead(200, { 'Content-Type': contentType });
      res.end(content, 'utf-8');
    }
  });
});

server.listen(PORT, () => {
  console.log(`StudyMind frontend server running at http://localhost:${PORT}`);
  console.log(`Proxying API requests to ${BACKEND_URL}`);
});
