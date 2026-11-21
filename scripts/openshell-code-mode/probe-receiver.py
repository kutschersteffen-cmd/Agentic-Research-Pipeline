"""Private test-only receiver for OpenShell egress verification."""

from argparse import ArgumentParser
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

COUNTS = Counter()


class ProbeHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/probe":
            marker = self.headers.get("X-ARP-Probe", "")
            if marker and len(marker) <= 128 and (marker in COUNTS or len(COUNTS) < 128):
                COUNTS[marker] += 1
            self.send_response(204)
            self.end_headers()
        elif url.path == "/count":
            marker = parse_qs(url.query).get("marker", [""])[0]
            body = str(COUNTS[marker]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    arguments = parser.parse_args()
    HTTPServer((arguments.bind, arguments.port), ProbeHandler).serve_forever()
