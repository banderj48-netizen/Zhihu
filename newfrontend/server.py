"""本地前端开发服务器：History API 路由统一回退到 index.html。"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class FrontendHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_head(self):
        path = self.translate_path(self.path)
        if not Path(path).is_file() and not self.path.split('?', 1)[0].startswith(('/美术素材/', '/音乐/')):
            self.path = '/index.html'
        return super().send_head()


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 3000), FrontendHandler).serve_forever()
