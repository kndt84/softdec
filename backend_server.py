#!/usr/bin/env python3
"""
Backend server for RTP stream processing
Handles only /mjpeg endpoint
"""
import http.server
import socketserver
import subprocess
import os
import threading
import sys
import socket
import yaml
import json
import time

# --- Configuration file loading ---
def load_config(config_path="config.yaml"):
    """Load YAML configuration file"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: Configuration file {config_path} not found.")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error: Failed to load configuration file: {e}")
        sys.exit(1)

# Load configuration
config = load_config()

# Get configuration values as global variables
BACKEND_PORT = 8081  # Different port for backend
BOUNDARY = "spionisto"
GST_BIN = config['gstreamer']['bin_path']
LOG_FILE = config['gstreamer']['log_file']

# Payload type cache file
CACHE_FILE = "payload_cache.json"

# --- Payload type cache management ---
def load_cache():
    """Load payload type cache from file"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load cache file: {e}")
            return {}
    return {}

def save_cache(cache):
    """Save payload type cache to file"""
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except IOError as e:
        print(f"Warning: Failed to save cache file: {e}")

def invalidate_cache_entry(multicast_address, port):
    """Invalidate a specific cache entry"""
    cache = load_cache()
    cache_key = f"{multicast_address}:{port}"
    if cache_key in cache:
        del cache[cache_key]
        save_cache(cache)
        print(f"Invalidated cache for {cache_key}")

# --- Detect payload type from RTP header ---
def detect_payload_type(multicast_address, port, timeout=None):
    if timeout is None:
        timeout = config['network']['timeout']
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', port))

    # Use multicast interface from configuration
    multicast_interface = config['network']['multicast_interface']
    
    try:
        # Join multicast group using the configured interface
        mreq = socket.inet_aton(multicast_address) + socket.inet_aton(multicast_interface)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except Exception as e:
        # Retry without specifying interface
        try:
            mreq = socket.inet_aton(multicast_address) + socket.inet_aton('0.0.0.0')
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except Exception as e2:
            raise RuntimeError(f"Failed to join multicast group: {e}")
    
    sock.settimeout(timeout)

    try:
        data, addr = sock.recvfrom(9000)
        
        # Validate RTP packet
        if len(data) < 12:
            raise RuntimeError(f"Invalid RTP packet: too short ({len(data)} bytes)")
        
        pt = data[1] & 0x7F
        print(f"Detected Payload Type: {pt} for {multicast_address}:{port}")
        
        return pt
    except socket.timeout:
        print(f"ERROR: Timeout waiting for RTP packet from {multicast_address}:{port}")
        raise RuntimeError("Timeout: Failed to receive RTP packet.")
    finally:
        sock.close()

def get_payload_type(multicast_address, port, force_detect=False):
    """Get payload type with file-based caching for faster subsequent requests
    
    Args:
        multicast_address: Multicast IP address
        port: Multicast port
        force_detect: If True, bypass cache and detect fresh (default: False)
    
    Returns:
        Detected payload type
    """
    cache_key = f"{multicast_address}:{port}"
    cache = load_cache()
    
    # Check cache unless force_detect is True
    if not force_detect and cache_key in cache:
        pt = cache[cache_key].get('payload_type')
        timestamp = cache[cache_key].get('timestamp', 0)
        cache_age = time.time() - timestamp
        
        print(f"Using cached payload type {pt} for {multicast_address}:{port} (cached {cache_age:.1f}s ago)")
        return pt
    
    # Detect payload type
    print(f"Detecting payload type for {multicast_address}:{port}...")
    pt = detect_payload_type(multicast_address, port)
    
    # Save to cache with timestamp
    cache[cache_key] = {
        'payload_type': pt,
        'timestamp': time.time()
    }
    save_cache(cache)
    print(f"Cached payload type {pt} for {multicast_address}:{port}")
    return pt

# --- Build GStreamer command based on payload type ---
def build_gst_command(pt, multicast_address=None, multicast_port=None, output_mode='mjpeg'):
        
    base = [
        GST_BIN, '-q',  # Use quiet mode instead of verbose to eliminate all output
        'udpsrc', f'address={multicast_address}', f'port={multicast_port}',
        f'multicast-iface={config["network"]["multicast_interface"]}',
        f'auto-multicast={str(config["network"]["auto_multicast"]).lower()}', '!',
    ]

    if pt == 96:
        pipeline = [
            'capsfilter', 'caps=application/x-rtp,media=video,encoding-name=MP2P,payload=96,clock-rate=90000', '!',
            'rtpjitterbuffer', f'latency={config["network"]["jitter_buffer_latency"]}', 'drop-on-latency=true', '!',
            'rtpmp2pdepay', '!',
            'mpegpsdemux', '!',
            'mpegvideoparse', '!',
            'd3d11mpeg2dec', '!',
            'videoconvert', '!',
            'jpegenc', 'quality=85', '!',  # Reduced quality for better performance
            'queue', 'max-size-buffers=2', 'leaky=downstream', '!',  # Drop old frames if queue is full
            'multipartmux', f'boundary={BOUNDARY}', '!',
            'fdsink', 'fd=1', 'sync=false'  # Changed to sync=false for minimum latency
        ]

    elif pt in [33, 103]:
        pipeline = [
            'capsfilter', 'caps=application/x-rtp,media=video,encoding-name=MP2T,payload={},clock-rate=90000'.format(pt), '!',
            'rtpjitterbuffer', f'latency={config["network"]["jitter_buffer_latency"]}', '!',
            'rtpmp2tdepay2', '!',
            'tsdemux', '!',
            'h264parse', '!',
            'd3d11h264dec', '!',
            'videoconvert', '!',
            'jpegenc', 'quality=85', '!',  # Reduced quality for better performance
            'queue', 'max-size-buffers=2', 'leaky=downstream', '!',  # Drop old frames if queue is full
            'multipartmux', f'boundary={BOUNDARY}', '!',
            'fdsink', 'fd=1', 'sync=false'  # Changed to sync=false for minimum latency
        ]

    else:
        raise ValueError(f"Unsupported payload type: {pt}")

    return base + pipeline

# --- HTTP Backend handler ---
class BackendServerHandler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        # Handle preflight requests
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def do_GET(self):
        # Check if URL path starts with /mjpeg
        if self.path.startswith('/mjpeg'):
            self._handle_stream_request('mjpeg')
        else:
            self.send_error(404)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

    def _handle_stream_request(self, output_mode):
        # Initialize multicast settings
        multicast_address = None
        multicast_port = None
        force_detect = False
        
        # Parse GET parameters if present
        if '?' in self.path:
            path, query = self.path.split('?', 1)
            params = {}
            for param in query.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    params[key] = value
            
            # Use ip parameter if present
            if 'ip' in params:
                multicast_address = params['ip']
            
            # Use port parameter if present (convert to integer)
            if 'port' in params:
                try:
                    multicast_port = int(params['port'])
                except ValueError:
                    self.send_error(400, "Invalid port parameter")
                    return
            
            # Check for force_detect parameter
            if 'force_detect' in params:
                force_detect = params['force_detect'].lower() == 'true'
        
        # Error if multicast settings are incomplete
        if not multicast_address or not multicast_port:
            self.send_error(400, "Multicast address and port must be specified via URL parameters")
            return
        
        self.send_response(200)
        self.send_header('Content-type', f'multipart/x-mixed-replace; boundary={BOUNDARY}')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()

        env = os.environ.copy()
        env['GST_DEBUG'] = '4'
        env['GST_DEBUG_FILE'] = LOG_FILE
        env['GST_DEBUG_NO_COLOR'] = '1'
        env['GST_DEBUG_DUMP_DOT_DIR'] = ''

        stop_event = threading.Event()
        gst_process = None

        def stream_data(output_pipe, wfile, stop_event):
            """Stream data with non-blocking write for minimum latency"""
            try:
                while not stop_event.is_set():
                    chunk = output_pipe.read(4096)
                    if not chunk:
                        break
                    try:
                        wfile.write(chunk)
                        wfile.flush()  # Flush immediately to reduce buffering
                    except (BrokenPipeError, ConnectionResetError):
                        # Client disconnected
                        break
                    except BlockingIOError:
                        # Write would block, skip this chunk to avoid delay
                        continue
            except Exception as e:
                print(f"[Thread Error] {e}")

        try:
            print(f"Live mode ({output_mode}): multicast address {multicast_address}, port {multicast_port}")
            pt = get_payload_type(multicast_address, multicast_port, force_detect)
            print(f"Building {output_mode} pipeline for payload type {pt}")
            
            try:
                gst_command = build_gst_command(pt, multicast_address, multicast_port, output_mode)
            except ValueError as e:
                # If payload type is not supported, invalidate cache and retry detection
                print(f"Payload type {pt} not supported: {e}")
                print("Invalidating cache and retrying payload detection...")
                invalidate_cache_entry(multicast_address, multicast_port)
                pt = get_payload_type(multicast_address, multicast_port, force_detect=True)
                print(f"Retried with payload type {pt}")
                gst_command = build_gst_command(pt, multicast_address, multicast_port, output_mode)
            
            # Display pipeline to stdout
            print(f"Executing GStreamer pipeline ({output_mode}) for {multicast_address}:{multicast_port}:")
            print(" ".join(gst_command))
            print("-" * 80)
            
            gst_process = subprocess.Popen(
                gst_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,  # Capture stderr separately
                env=env
            )

            # Monitor stderr in a separate thread
            def monitor_stderr():
                try:
                    for line in iter(gst_process.stderr.readline, b''):
                        if line:
                            line_str = line.decode('utf-8', errors='ignore').strip()
                            if any(keyword in line_str.lower() for keyword in ['error', 'critical', 'warning']):
                                print(f"[GStreamer] {line_str}")
                except:
                    pass
            
            stderr_thread = threading.Thread(target=monitor_stderr, daemon=True)
            stderr_thread.start()

            thread = threading.Thread(target=stream_data, args=(gst_process.stdout, self.wfile, stop_event))
            thread.start()
            thread.join()
        except Exception as e:
            print(f"Error: {e}")
            self.send_error(500, f"Internal server error: {e}")
        finally:
            stop_event.set()
            if gst_process:
                try:
                    gst_process.terminate()
                    gst_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    gst_process.kill()

    def log_message(self, format, *args):
        return

# --- HTTP server ---
class ThreadingHTTPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

def run_server():
    handler = BackendServerHandler
    with ThreadingHTTPServer(("", BACKEND_PORT), handler) as httpd:
        print(f"Backend server running on port {BACKEND_PORT}", flush=True)
        print(f"MJPEG endpoint: http://localhost:{BACKEND_PORT}/mjpeg", flush=True)
        sys.stdout.flush()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping backend server...")
            httpd.shutdown()
            httpd.server_close()
            sys.exit(0)

# --- Execution ---
if __name__ == '__main__':
    try:
        gst_path = r'C:\gstreamer\1.0\msvc_x86_64\bin'
        os.environ["PATH"] += os.pathsep + gst_path
        run_server()
    except Exception as e:
        print(f"Backend server startup error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)