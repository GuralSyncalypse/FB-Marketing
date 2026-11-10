import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Nếu các biến toàn cục này được dùng ở file khác, bạn nên cân nhắc trả về qua callback
# Ở đây tạm thời giữ nguyên cấu trúc logic của bạn
class ExtensionHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server):
        # Lấy hàm callback được lưu trong server object
        self.on_data_received = server.on_data_received
        super().__init__(request, client_address, server)

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        
        try:
            data = json.loads(post_data)
            uid = data.get("uid", "")
            user_agent = data.get("user_agent", "")
            cookies = data.get("cookie_json", [])
            
            print("\n" + "="*50)
            print("[SERVER] NHẬN DATA THÀNH CÔNG TỪ EXTENSION")
            print(f"-> UID nhận được: {uid}")
            print("="*50)

            # Gói tất cả vào một dictionary
            session_data = {
                "uid": uid,
                "user_agent": user_agent,
                "cookies": cookies
            }

            # Thay vì gọi trực tiếp UI, ta kích hoạt hàm callback và truyền dữ liệu đi
            print()
            if self.on_data_received:
                self.on_data_received(session_data)

        except Exception as e:
            print(f"[Server Lỗi] Không thể xử lý JSON: {str(e)}")

        # Phản hồi lại cho Extension
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        # Tắt log mặc định của BaseHTTPRequestHandler để tránh rác console
        return


def start_local_server(port, on_uid_received_callback):
    def run_server():
        try:
            server_address = ('', port)
            httpd = HTTPServer(server_address, ExtensionHandler)
            httpd.on_data_received = on_uid_received_callback
            
            msg = f"[Server] Đang chạy ngầm tại http://localhost:{port}..."
            print(msg)
                
            httpd.serve_forever()
        except Exception as e:
            err_msg = f"[Server Lỗi] Không thể khởi động: {str(e)}"
            print(err_msg)

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()