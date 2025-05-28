import http.server
import socketserver
import subprocess
import os
import threading
import sys
import argparse
import socket

# --- 引数パース ---
parser = argparse.ArgumentParser(description="MJPEG HTTP Server with RTP Payload Type Detection")
parser.add_argument('--port', type=int, default=8080, help='Port to serve HTTP on')
parser.add_argument('--test-mode', action='store_true', help='Enable test mode with pcap file')
parser.add_argument('--pcap-file', type=str, help='Path to pcap file for test mode')
args = parser.parse_args()

HTTP_PORT = args.port
BOUNDARY = "spionisto"
GST_BIN = r"C:\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe"
LOG_FILE = "gst_debug.log"


# --- RTPヘッダからPTを判別 ---
def detect_payload_type(multicast_address, port, timeout=5):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', port))

    # ネットワークインターフェース情報をデバッグ出力
    import subprocess
    try:


        # Windowsのipconfig出力を取得
        result = subprocess.run(['ipconfig'], capture_output=True, text=True, encoding='cp932')
        print("=== ネットワークインターフェース情報 ===")
        print(result.stdout)
        print("=" * 50)
    except Exception as e:
        print(f"ipconfig実行エラー: {e}")

    # ローカルIPアドレスを動的に取得
    try:
        # デフォルトゲートウェイに接続してローカルIPを取得
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        test_sock.connect(("8.8.8.8", 80))
        #local_ip = test_sock.getsockname()[0]
        local_ip = "192.168.200.1"
        test_sock.close()
        print(f"動的に取得したローカルIP: {local_ip}")
    except Exception as e:
        print(f"動的IP取得失敗: {e}")
        # フォールバック
        local_ip = socket.gethostbyname(socket.gethostname())
        print(f"フォールバックIP: {local_ip}")
    
    print(f"マルチキャストバインド用IP: {local_ip}")
    print(f"マルチキャストアドレス: {multicast_address}")
    print(f"ポート: {port}")

    # マルチキャストグループへの参加を試行
    try:
        mreq = socket.inet_aton(multicast_address) + socket.inet_aton(local_ip)
        print(f"マルチキャストグループ参加試行: {multicast_address} (インターフェース: {local_ip})")
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        print("マルチキャストグループ参加成功")
    except Exception as e:
        print(f"マルチキャストグループ参加失敗: {e}")
        print("代替方法として、インターフェースを指定せずに試行...")
        try:
            # インターフェースを指定しない方法で再試行
            mreq = socket.inet_aton(multicast_address) + socket.inet_aton('0.0.0.0')
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            print("代替方法でマルチキャストグループ参加成功")
        except Exception as e2:
            print(f"代替方法も失敗: {e2}")
            raise RuntimeError(f"マルチキャストグループへの参加に失敗しました: {e}")
    
    sock.settimeout(timeout)

    try:
        data, _ = sock.recvfrom(9000)
        print(f"Received packet: {data[:12].hex()} (len={len(data)})")
        pt = data[1] & 0x7F
        print(f"Detected Payload Type: {pt}")
        return pt
    except socket.timeout:
        raise RuntimeError("Timeout: Failed to receive RTP packet.")
    finally:
        sock.close()

# --- PTに応じてGStreamerコマンドを構築 ---
def build_gst_command(pt, multicast_address=None, multicast_port=None):
        
    base = [
        GST_BIN, '-v',
        'udpsrc', f'address={multicast_address}', f'port={multicast_port}',
        'multicast-iface=0.0.0.0', 'auto-multicast=true', '!',
    ]

    if pt == 96:
        pipeline = [
            'capsfilter', 'caps=application/x-rtp,media=video,encoding-name=MP2P,payload=96,clock-rate=90000', '!',
            'rtpjitterbuffer', 'latency=200', '!',
            'rtpmp2pdepay', '!',
            'decodebin', '!',
            'videoconvert', '!',
            'qsvjpegenc', '!',
            'queue', '!',
            'multipartmux', f'boundary={BOUNDARY}', '!',
            'fdsink', 'fd=1', 'sync=true'
        ]

    elif pt == 103:
        pipeline = [
            'capsfilter', 'caps=application/x-rtp,media=video,encoding-name=MP2T,payload=103,clock-rate=90000', '!',
            'rtpjitterbuffer', 'latency=200', '!',
            'rtpmp2tdepay2', '!',
            'tsdemux', '!',
            'h264parse', '!',
            'qsvh264dec', '!',
            'videoconvert', '!',
            'qsvjpegenc', '!',
            'queue', '!',
            'multipartmux', f'boundary={BOUNDARY}', '!',
            'fdsink', 'fd=1', 'sync=true'
        ]

    elif pt == 33:
        pipeline = [
            'capsfilter', 'caps=application/x-rtp,media=video,encoding-name=MP2T,payload=33,clock-rate=90000', '!',
            'rtpjitterbuffer', 'latency=200', '!',
            'rtpmp2tdepay2', '!',
            'tsdemux', '!',
            'h264parse', '!',
            'qsvh264dec', '!',
            'videoconvert', '!',
            'qsvjpegenc', '!',
            'queue', '!',
            'multipartmux', f'boundary={BOUNDARY}', '!',
            'fdsink', 'fd=1', 'sync=true'
        ]
    else:
        raise ValueError(f"Unsupported payload type: {pt}")

    return base + pipeline

# --- HTTP MJPEGハンドラ ---
class MJPEGServerHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # URLパスが/mjpegで始まるかチェック
        if self.path.startswith('/mjpeg'):
            
            # GETパラメータがある場合は解析
            if '?' in self.path:
                path, query = self.path.split('?', 1)
                params = {}
                for param in query.split('&'):
                    if '=' in param:
                        key, value = param.split('=', 1)
                        params[key] = value
                
                # ipパラメータがあれば使用
                if 'ip' in params:
                    multicast_address = params['ip']
                
                # portパラメータがあれば使用（整数に変換）
                if 'port' in params:
                    try:
                        multicast_port = int(params['port'])
                    except ValueError:
                        self.send_error(400, "Invalid port parameter")
                        return
            
            self.send_response(200)
            self.send_header('Content-type', f'multipart/x-mixed-replace; boundary={BOUNDARY}')
            self.end_headers()

            env = os.environ.copy()
            env['GST_DEBUG'] = '4'
            env['GST_DEBUG_FILE'] = LOG_FILE

            stop_event = threading.Event()
            gst_process = None  # ここで初期化

            def stream_mjpeg(output_pipe, wfile, stop_event):
                try:
                    while not stop_event.is_set():
                        chunk = output_pipe.read(4096)
                        if not chunk:
                            break
                        try:
                            wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            break
                except Exception as e:
                    print(f"[Thread Error] {e}")

            try:

                print(f"ライブモード: マルチキャストアドレス {multicast_address}, ポート {multicast_port}")
                pt = detect_payload_type(multicast_address, multicast_port)
                gst_command = build_gst_command(pt, multicast_address, multicast_port)
                
                # パイプラインを標準出力に表示
                print("実行するGStreamerパイプライン:")
                print(" ".join(gst_command))
                print("-" * 80)
                
                gst_process = subprocess.Popen(
                    gst_command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=env
                )

                thread = threading.Thread(target=stream_mjpeg, args=(gst_process.stdout, self.wfile, stop_event))
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
        else:
            self.send_error(404)
            self.end_headers()

    def log_message(self, format, *args):
        return

# --- HTTPサーバ ---
class ThreadingHTTPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

def run_server():
    handler = MJPEGServerHandler
    with ThreadingHTTPServer(("", HTTP_PORT), handler) as httpd:
        print(f"Serving MJPEG stream at http://localhost:{HTTP_PORT}/mjpeg")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping server...")
            httpd.shutdown()
            httpd.server_close()
            sys.exit(0)

# --- 実行 ---
if __name__ == '__main__':
    gst_path = r'C:\gstreamer\1.0\msvc_x86_64\bin'
    os.environ["PATH"] += os.pathsep + gst_path
    run_server()
