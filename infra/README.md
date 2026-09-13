# infra

存放本地开发和部署配置，例如 Docker Compose、数据库初始化、Redis、对象存储和环境变量模板。不得提交真实密钥、生产地址或用户数据。

## Nginx 反向代理

`nginx.conf` 是本项目的入口配置：Nginx 监听 80 端口，`/` 转发到 Next.js 3000，`/api/` 和 `/v1/` 转发到 FastAPI 8000。

Windows 将本文件复制到 Nginx 安装目录的 `conf/nginx.conf`，执行 `nginx.exe -t` 检查配置，再运行 `nginx.exe`。Linux 复制到 `/etc/nginx/nginx.conf` 后执行 `sudo nginx -t && sudo systemctl reload nginx`。
