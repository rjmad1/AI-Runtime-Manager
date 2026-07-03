# core/prompt_server.py
# Lightweight Python standard library HTTP server for non-technical user credential setup.

import os
import sys
import json
import webbrowser
import urllib.parse
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8500
server_running = True

# Helper to save environment variables persistently on Windows
def set_windows_env(name, value):
    try:
        cmd = f"[System.Environment]::SetEnvironmentVariable('{name}', '{value}', 'User')"
        subprocess.run(["powershell", "-Command", cmd], capture_output=True, check=True)
        return True
    except Exception as e:
        print(f"Error setting env {name}: {e}")
        return False

# Visual template for the form using premium dark mode styling
HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenClaw Workstation Configuration</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --card-border: #334155;
            --accent: #3b82f6;
            --accent-hover: #2563eb;
            --success: #10b981;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --input-bg: #0f172a;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 2rem 1rem;
        }
        .setup-card {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            width: 100%;
            max-width: 580px;
            padding: 2.5rem;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3);
        }
        header {
            margin-bottom: 2rem;
            text-align: center;
        }
        h1 {
            font-size: 1.85rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            background: linear-gradient(to right, #60a5fa, #3b82f6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        p.subtitle {
            color: var(--text-muted);
            font-size: 0.95rem;
            line-height: 1.5;
        }
        .form-group {
            margin-bottom: 1.5rem;
        }
        label {
            display: block;
            font-size: 0.9rem;
            font-weight: 600;
            margin-bottom: 0.4rem;
            color: var(--text-main);
        }
        input[type="text"] {
            width: 100%;
            padding: 0.75rem 1rem;
            background-color: var(--input-bg);
            border: 1px solid var(--card-border);
            border-radius: 8px;
            color: var(--text-main);
            font-family: monospace;
            font-size: 0.9rem;
            transition: border-color 0.2s;
        }
        input[type="text"]:focus {
            outline: none;
            border-color: var(--accent);
        }
        .help-text {
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-top: 0.3rem;
            display: flex;
            justify-content: space-between;
        }
        .help-text a {
            color: var(--accent);
            text-decoration: none;
        }
        .help-text a:hover {
            text-decoration: underline;
        }
        .btn-container {
            display: flex;
            gap: 1rem;
            margin-top: 2rem;
        }
        .btn {
            flex: 1;
            padding: 0.85rem;
            border: none;
            border-radius: 8px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            transition: background-color 0.2s, transform 0.1s;
            text-align: center;
        }
        .btn:active {
            transform: scale(0.98);
        }
        .btn-primary {
            background-color: var(--accent);
            color: #fff;
        }
        .btn-primary:hover {
            background-color: var(--accent-hover);
        }
        .btn-secondary {
            background-color: transparent;
            border: 1px solid var(--card-border);
            color: var(--text-muted);
        }
        .btn-secondary:hover {
            background-color: rgba(255, 255, 255, 0.05);
            color: var(--text-main);
        }
        .info-box {
            background-color: rgba(59, 130, 246, 0.08);
            border: 1px solid rgba(59, 130, 246, 0.2);
            padding: 0.85rem;
            border-radius: 8px;
            font-size: 0.8rem;
            color: #93c5fd;
            margin-bottom: 1.5rem;
            line-height: 1.4;
        }
    </style>
</head>
<body>
    <div class="setup-card">
        <header>
            <h1>Workstation API Keys Setup</h1>
            <p class="subtitle">Enter credentials for your enabled AI providers to activate models. Unentered keys will be skipped safely.</p>
        </header>

        <div class="info-box">
            🛡️ <strong>Privacy Info</strong>: Your keys are stored securely as persistent Windows User Environment Variables on your local machine. They are never written to plain-text settings files or sent to external servers.
        </div>

        <form method="POST" action="/submit">
            <div class="form-group">
                <label for="GEMINI_API_KEY">Google Gemini API Key</label>
                <input type="text" id="GEMINI_API_KEY" name="GEMINI_API_KEY" placeholder="AIzaSy...">
                <div class="help-text">
                    <span>Exposes Gemini 2.5 Flash</span>
                    <a href="https://aistudio.google.com/" target="_blank">Get key at AI Studio</a>
                </div>
            </div>

            <div class="form-group">
                <label for="GROQ_API_KEY">Groq API Key</label>
                <input type="text" id="GROQ_API_KEY" name="GROQ_API_KEY" placeholder="gsk_...">
                <div class="help-text">
                    <span>Exposes Llama 3.3 70B (Groq)</span>
                    <a href="https://console.groq.com/" target="_blank">Get key at Groq Console</a>
                </div>
            </div>

            <div class="form-group">
                <label for="SAMBANOVA_API_KEY">SambaNova API Key</label>
                <input type="text" id="SAMBANOVA_API_KEY" name="SAMBANOVA_API_KEY" placeholder="sn_...">
                <div class="help-text">
                    <span>Exposes Llama 3.3 70B (SambaNova)</span>
                    <a href="https://cloud.sambanova.ai/" target="_blank">Get key at SambaNova Cloud</a>
                </div>
            </div>

            <div class="form-group">
                <label for="CEREBRAS_API_KEY">Cerebras API Key</label>
                <input type="text" id="CEREBRAS_API_KEY" name="CEREBRAS_API_KEY" placeholder="c_...">
                <div class="help-text">
                    <span>Exposes Llama 3.1 70B (Cerebras)</span>
                    <a href="https://cloud.cerebras.ai/" target="_blank">Get key at Cerebras Console</a>
                </div>
            </div>

            <div class="form-group">
                <label for="OPENROUTER_API_KEY">OpenRouter API Key</label>
                <input type="text" id="OPENROUTER_API_KEY" name="OPENROUTER_API_KEY" placeholder="sk-or-v1-...">
                <div class="help-text">
                    <span>Exposes OpenRouter models</span>
                    <a href="https://openrouter.ai/" target="_blank">Get key at OpenRouter</a>
                </div>
            </div>

            <div class="btn-container">
                <button type="submit" class="btn btn-primary">Save & Continue</button>
                <button type="button" onclick="location.href='/skip'" class="btn btn-secondary">Skip / Use Existing</button>
            </div>
        </form>
    </div>
</body>
</html>
"""

SUCCESS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Setup Complete</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --card-border: #334155;
            --success: #10b981;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }
        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            padding: 1rem;
        }
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 2.5rem;
            max-width: 480px;
            text-align: center;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
        }
        .icon {
            font-size: 3rem;
            color: var(--success);
            margin-bottom: 1rem;
        }
        h1 { margin-bottom: 0.5rem; font-size: 1.5rem; }
        p { color: var(--text-muted); font-size: 0.95rem; margin-bottom: 1.5rem; line-height: 1.4;}
        .close-text { font-size: 0.8rem; color: var(--text-muted); font-style: italic; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">✓</div>
        <h1>Credentials Saved Successfully</h1>
        <p>API keys have been configured persistently. The installer terminal will now automatically resume setting up configurations and testing completions.</p>
        <span class="close-text">You can close this browser tab now.</span>
    </div>
    <script>
        setTimeout(function() { window.close(); }, 5000);
    </script>
</body>
</html>
"""

SKIP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Setup Skipped</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --card-border: #334155;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }
        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            padding: 1rem;
        }
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 2.5rem;
            max-width: 480px;
            text-align: center;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
        }
        .icon {
            font-size: 3rem;
            color: var(--text-muted);
            margin-bottom: 1rem;
        }
        h1 { margin-bottom: 0.5rem; font-size: 1.5rem; }
        p { color: var(--text-muted); font-size: 0.95rem; margin-bottom: 1.5rem; line-height: 1.4;}
        .close-text { font-size: 0.8rem; color: var(--text-muted); font-style: italic; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">➔</div>
        <h1>Setup Skipped</h1>
        <p>Using existing credentials configurations. The installer terminal will now resume the setup flow.</p>
        <span class="close-text">You can close this browser tab now.</span>
    </div>
    <script>
        setTimeout(function() { window.close(); }, 5000);
    </script>
</body>
</html>
"""

class PromptRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress logging console pollution
        pass

    def do_GET(self):
        if self.path == "/skip":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(SKIP_HTML.encode("utf-8"))
            
            global server_running
            server_running = False
        else:
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode("utf-8"))

    def do_POST(self):
        if self.path == "/submit":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length).decode("utf-8")
            params = urllib.parse.parse_qs(post_data)
            
            # Save environment variables persistently
            for key, val_list in params.items():
                if val_list and val_list[0].strip():
                    name = key.strip()
                    val = val_list[0].strip()
                    set_windows_env(name, val)
                    
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(SUCCESS_HTML.encode("utf-8"))
            
            global server_running
            server_running = False

def run_prompt_server():
    server_address = ("127.0.0.1", PORT)
    httpd = HTTPServer(server_address, PromptRequestHandler)
    print(f"[INFO] Server listening on http://127.0.0.1:{PORT}")
    
    # Auto-open default browser
    webbrowser.open(f"http://127.0.0.1:{PORT}")
    
    while server_running:
        httpd.handle_request()
        
    print("[INFO] Setup complete. Shutting down configuration server.")

if __name__ == "__main__":
    run_prompt_server()
