import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from src import safehttp
from src.media import MediaDownloadError
from src.media.pixabay import UrllibTransport


class Handler(BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        Handler.seen.append((self.path, self.headers.get("x-test-secret")))
        if self.path == "/evil":      # different host name -> must be blocked
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{self.server.server_port}/final")
            self.end_headers()
        elif self.path == "/same":    # same host -> allowed
            self.send_response(302)
            self.send_header("Location", "/final")
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"hello")

    def log_message(self, *a):
        pass


class SafeHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.srv.server_port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    @staticmethod
    def allow(url):
        return urlparse(url).hostname == "127.0.0.1"

    def test_same_host_redirect_followed(self):
        r = safehttp.fetch(f"http://127.0.0.1:{self.port}/same", allowed=self.allow)
        self.assertEqual((r.status, r.body), (200, b"hello"))

    def test_cross_host_redirect_blocked_before_request_and_header_not_leaked(self):
        Handler.seen.clear()
        with self.assertRaises(safehttp.UnsafeRedirect):
            safehttp.fetch(f"http://127.0.0.1:{self.port}/evil", allowed=self.allow,
                           headers={"x-test-secret": "TOPSECRET"})
        paths = [p for p, _ in Handler.seen]
        self.assertEqual(paths, ["/evil"])        # redirect target was never requested

    def test_disallowed_initial_url(self):
        with self.assertRaises(safehttp.UnsafeRedirect):
            safehttp.fetch("https://example.com/", allowed=self.allow)

    def test_size_limit(self):
        with self.assertRaises(safehttp.ResponseTooLarge):
            safehttp.fetch(f"http://127.0.0.1:{self.port}/final", allowed=self.allow, max_bytes=2)

    def test_network_error_has_no_url(self):
        with self.assertRaises(safehttp.NetworkError) as cm:
            safehttp.fetch("http://127.0.0.1:1/x", allowed=self.allow, timeout=2)
        self.assertNotIn("127.0.0.1", str(cm.exception))

    def test_pixabay_transport_refuses_foreign_and_plain_http(self):
        t = UrllibTransport()
        for url in ("https://evil.example/x.mp4", "http://pixabay.com/api/?key=SECRET",
                    "https://pixabay.com.evil.example/x"):
            with self.assertRaises(MediaDownloadError):
                t.fetch(url)


if __name__ == "__main__":
    unittest.main()
