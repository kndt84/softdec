#!/usr/bin/env python3
"""
HTTP/1.1 Frontend server for RTP stream processing
Serves static files (HTML, JS, CSS) with HTTP/1.1
"""
import http.server
import socketserver
import os
import sys

# Configuration
FRONTEND_PORT = 8080  # HTTP port for frontend
STATIC_FILES = {
    '/': 'index.html',
    '/index.html': 'index.html'
}

class FrontendServerHandler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        # Handle CORS preflight requests
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def do_GET(self):
        # Serve static files
        if self.path == '/' or self.path == '/index.html':
            self.serve_file('index.html', 'text/html')
        else:
            self.send_error(404, f"File not found: {self.path}")
    
    def serve_file(self, filename, content_type):
        """Serve a static file"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
            
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Length', str(len(content.encode('utf-8'))))
            self.end_headers()
            
            self.wfile.write(content.encode('utf-8'))
            
        except FileNotFoundError:
            self.send_error(404, f"File not found: {filename}")
        except Exception as e:
            self.send_error(500, f"Error serving {filename}: {e}")
    
    def log_message(self, format, *args):
        """Override to reduce log noise"""
        pass

class ThreadingHTTPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

def run_server():
    """Run the HTTP/1.1 frontend server"""
    print(f"HTTP/1.1 Frontend server starting on port {FRONTEND_PORT}")
    print(f"Main page: http://localhost:{FRONTEND_PORT}/")
    print(f"Protocol: HTTP/1.1 (no SSL)")
    
    handler = FrontendServerHandler
    try:
        with ThreadingHTTPServer(("", FRONTEND_PORT), handler) as httpd:
            print(f"✓ HTTP/1.1 Frontend server running on port {FRONTEND_PORT}")
            print("✓ No SSL certificates required")
            print("✓ Stable HTTP/1.1 protocol")
            sys.stdout.flush()
            
            httpd.serve_forever()
            
    except KeyboardInterrupt:
        print("\nStopping frontend server...")
        httpd.shutdown()
        httpd.server_close()
        sys.exit(0)
    except Exception as e:
        print(f"Frontend server error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    # Check if required files exist
    required_files = ['index.html']
    missing_files = [f for f in required_files if not os.path.exists(f)]
    
    if missing_files:
        print(f"ERROR: Missing required files: {', '.join(missing_files)}")
        sys.exit(1)
    
    run_server()