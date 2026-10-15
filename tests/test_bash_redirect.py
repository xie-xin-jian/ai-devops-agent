"""bash 巡检命令拦截器 + http_check 工具的单元测试。"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from agent.tools.ops import run_http_check
from agent.tools.shell import suggest_tool_for_command


class TestSuggestToolForCommand:
    def test_port_listen(self):
        assert suggest_tool_for_command("ss -tlnp | grep 8001")[0] == "port_listen"
        assert suggest_tool_for_command("netstat -tlnp")[0] == "port_listen"

    def test_disk_usage(self):
        assert suggest_tool_for_command("df -h")[0] == "disk_usage"
        assert suggest_tool_for_command("sudo df -h")[0] == "disk_usage"

    def test_memory_usage(self):
        assert suggest_tool_for_command("free -h")[0] == "memory_usage"

    def test_system_info(self):
        assert suggest_tool_for_command("uptime")[0] == "system_info"

    def test_process_search(self):
        assert (
            suggest_tool_for_command('pgrep -af "pip install"')[0]
            == "process_search"
        )
        assert (
            suggest_tool_for_command("ps -ef | grep uvicorn")[0]
            == "process_search"
        )
        assert (
            suggest_tool_for_command("ps aux | grep nginx")[0]
            == "process_search"
        )

    def test_http_check(self):
        assert (
            suggest_tool_for_command(
                'curl -s -o /dev/null -w "HTTP %{http_code}" '
                "http://127.0.0.1:8000/"
            )[0]
            == "http_check"
        )
        assert (
            suggest_tool_for_command("curl -s https://example.com/health")[0]
            == "http_check"
        )

    def test_curl_write_not_redirected(self):
        assert suggest_tool_for_command(
            "curl -s -X POST -d '{}' http://127.0.0.1:8000/api"
        ) is None
        assert suggest_tool_for_command(
            "curl --data-binary @f.json http://127.0.0.1:8000/api"
        ) is None

    def test_compound_command_not_redirected(self):
        assert suggest_tool_for_command("df -h; free -h; uptime") is None
        assert suggest_tool_for_command("cd /opt && df -h") is None

    def test_force_prefix_bypasses(self):
        assert suggest_tool_for_command("force: df -h") is None

    def test_unrelated_command_not_redirected(self):
        assert suggest_tool_for_command("git status") is None
        assert suggest_tool_for_command("systemctl restart nginx") is None
        assert suggest_tool_for_command("") is None
        assert suggest_tool_for_command(None) is None


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
        else:
            self.send_response(404)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


class TestRunHttpCheck:
    @classmethod
    def setup_class(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.start()

    @classmethod
    def teardown_class(cls):
        cls.server.shutdown()
        cls.thread.join()

    def test_ok(self):
        out = run_http_check(f"http://127.0.0.1:{self.port}/health")
        assert out.startswith("HTTP 200")
        assert "ok" in out

    def test_http_error_status(self):
        out = run_http_check(f"http://127.0.0.1:{self.port}/missing")
        assert out.startswith("HTTP 404")

    def test_scheme_autofill(self):
        out = run_http_check(f"127.0.0.1:{self.port}/health")
        assert out.startswith("HTTP 200")

    def test_empty_url(self):
        assert run_http_check("").startswith("Error")

    def test_unreachable(self):
        # 127.0.0.1:1 几乎必然不可达，应返回 Error 而非抛异常
        out = run_http_check("http://127.0.0.1:1/", timeout=2)
        assert out.startswith("Error")
