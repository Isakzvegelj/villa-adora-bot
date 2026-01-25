import http.server
import socketserver
import os
from datetime import datetime

PORT = 8080
CLAW_DIR = "/Users/isakzvegelj/clawd"
INBOX_PATH = os.path.join(CLAW_DIR, "INBOX.md")
STATUS_PATH = os.path.join(CLAW_DIR, "STATUS.md")

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            status_content = "Status file not found."
            if os.path.exists(STATUS_PATH):
                with open(STATUS_PATH, 'r') as f:
                    status_content = f.read()
            
            inbox_content = "Inbox file not found."
            if os.path.exists(INBOX_PATH):
                with open(INBOX_PATH, 'r') as f:
                    inbox_content = f.read()

            import markdown
            try:
                # Basic conversion if markdown library is available, 
                # otherwise just wrap in pre tags
                status_html = f"<pre>{status_content}</pre>"
                inbox_html = f"<pre>{inbox_content}</pre>"
            except:
                status_html = f"<pre>{status_content}</pre>"
                inbox_html = f"<pre>{inbox_content}</pre>"

            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Ralph & Clawd Dashboard</title>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; background: #f4f7f9; }}
                    .card {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; shadow: 0 2px 4px rgba(0,0,0,0.1); border: 1px solid #e1e4e8; }}
                    h1, h2 {{ color: #24292e; }}
                    pre {{ white-space: pre-wrap; word-wrap: break-word; background: #f6f8fa; padding: 16px; border-radius: 6px; font-size: 85%; }}
                    .status-idle {{ color: #28a745; }}
                    .status-busy {{ color: #ffd33d; }}
                    .refresh {{ font-size: 0.8em; color: #586069; }}
                </style>
                <script>
                    setTimeout(function() {{ location.reload(); }}, 30000);
                </script>
            </head>
            <body>
                <h1>🦞 Ralph & Clawd Dashboard</h1>
                <p class="refresh">Auto-refreshing every 30s. Last updated: {datetime.now().strftime('%H:%M:%S')}</p>
                
                <div class="card">
                    <h2>📊 System Status</h2>
                    {status_html}
                </div>
                
                <div class="card">
                    <h2>📋 Task Queue (INBOX)</h2>
                    {inbox_html}
                </div>
            </body>
            </html>
            """
            self.wfile.write(html.encode('utf-8'))
        else:
            super().do_GET()

if __name__ == "__main__":
    handler = DashboardHandler
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print(f"Serving dashboard at http://localhost:{PORT}")
        httpd.serve_forever()
