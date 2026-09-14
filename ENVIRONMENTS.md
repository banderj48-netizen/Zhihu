# 两套运行环境

## 本地开发

后端（PowerShell）：

```powershell
cd backend
.\run_server.ps1 -Environment local
```

前端（另开终端）：

```powershell
cd frontend
npm install
npm run dev -- --hostname 127.0.0.1
```

访问 `http://127.0.0.1:3000`。

## 服务器部署

服务器拉取 `main` 后，后端使用服务器 `.env`：

```powershell
cd backend
.\run_server.ps1 -Environment server
```

前端：

```powershell
cd frontend
npm install
npm run build
npm run start -- --hostname 0.0.0.0 --port 3000
```

访问 `http://8.133.211.26:3000`。服务器需放行 3000、8000 端口，并在知乎开放平台登记服务器回调地址。

`.env.local` 优先用于本地开发；`.env` 为服务器配置。两者可按当前部署策略提交仓库，修改后需重启服务。
