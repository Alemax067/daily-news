# daily-news

新闻 / 政策抓取智能体。输入站点 URL 与板块名,智能体自学习页面结构,持续抓取并存储新闻条目。前端 React + 后端 FastAPI + SQLite,单容器部署。

## 功能一览

- 对话式新建订阅:把 URL 和板块名甩给智能体,自动学习 CSS 选择器
- 自动定时抓取:可配置每天 / 每 12 小时触发,新增条目入库
- Timeline:按"批次"查看每次抓取产生的新条目
- 一键导出 xlsx
- 全部数据落地到 `data/app.db`(SQLite),容器删了数据还在

---

## 快速开始(任意系统通用)

只需要两样东西:

1. **Docker Desktop**(Windows / macOS)或 **Docker Engine + Compose**(Linux)
2. 一份 `.env`,里面填好 LLM 网关的 `DAILY_NEWS_AGENT_API_KEY`

启动后浏览器打开 <http://localhost:8765> 即可。

---

## Windows 部署

### 前置

- 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/) 并启动它(WSL2 后端)
- 想用 IPv6 访问的话,在 Docker Desktop → **Settings → Resources → Network** 勾上 **Enable IPv6 networking**,然后重启 Docker Desktop

### 一键启动

```cmd
git clone <你的仓库地址> daily-news
cd daily-news
copy .env.example .env
notepad .env             :: 填入 DAILY_NEWS_AGENT_API_KEY 后保存关闭
start.bat
```

或在资源管理器里直接**双击 `start.bat`**。脚本会自动:

1. 检查 `.env` 是否存在
2. `docker compose up -d --build` 起容器
3. 输出访问地址

### 停止 / 重启 / 看日志

```cmd
docker compose logs -f          :: 看实时日志
docker compose restart          :: 重启
docker compose down             :: 停掉并删除容器(数据保留在 .\data)
docker compose up -d             :: 不重新 build,直接用已有镜像启动
```

### Windows 已知坑

- **路径里别带空格、中文**:Docker Desktop 在中文/带空格目录下偶发挂卷失败,建议放到 `C:\daily-news` 或 `D:\daily-news`
- **首次构建慢**:`pnpm install` 拉前端依赖、`uv sync` 装后端依赖,大约 3–8 分钟,看网络;后续 `up -d` 不重 build 是秒起
- **如果看到 `^M: bad interpreter` 之类报错**:你 git clone 时把 `entrypoint.sh` 的换行变成了 CRLF。解决:`git config --global core.autocrlf input` 后重新 clone,或者直接 `git checkout -- .`(项目里已配 `.gitattributes` 强制 LF,正常情况不会出现)

---

## macOS 部署

### 前置

- 安装 [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/) 并启动
- Apple Silicon(M 系列)可用,Dockerfile 用的镜像都支持 arm64

### 一键启动

```bash
git clone <你的仓库地址> daily-news
cd daily-news
cp .env.example .env
open -e .env             # 编辑填入 DAILY_NEWS_AGENT_API_KEY
./start.sh
```

或手动:

```bash
docker compose up -d --build
```

打开浏览器:<http://localhost:8765>

---

## Linux 部署

### 前置

```bash
# Ubuntu / Debian 示例,其他发行版换包管理器即可
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # 重新登录使生效,避免每条 docker 都 sudo
```

确认 `docker compose version` 能跑出版本号(新版 Docker Compose 是 docker CLI 的子命令,不再单独安装 `docker-compose`)。

### 启动

```bash
git clone <你的仓库地址> daily-news
cd daily-news
cp .env.example .env
$EDITOR .env             # 填 DAILY_NEWS_AGENT_API_KEY
./start.sh
```

### Linux 上的 IPv6

Linux Docker 默认就启用了 IPv4 端口监听;`docker-compose.yml` 里同时声明了 IPv6 映射:

```yaml
ports:
  - "0.0.0.0:8765:8765"
  - "[::]:8765:8765"
```

如果发现 `[::]:8765:8765` 不工作,需要在 `/etc/docker/daemon.json` 启用 IPv6:

```json
{
  "ipv6": true,
  "fixed-cidr-v6": "fd00:dead:beef::/64",
  "experimental": true,
  "ip6tables": true
}
```

然后 `sudo systemctl restart docker`。

如果你只是**自己一台机器跑、嫌折腾**,可以直接用 host 网络模式(只 Linux 支持):

```bash
docker run -d \
  --network host \
  -v "$(pwd)/data":/app/data \
  --env-file .env \
  --name daily-news \
  daily-news:latest
```

---

## 配置说明

`.env` 字段(从 `.env.example` 拷贝即可):

| 字段 | 必填 | 说明 |
|---|:---:|---|
| `DAILY_NEWS_AGENT_API_KEY` | ✅ | LLM 网关 API Key,空容器会启动失败 |
| `DAILY_NEWS_AGENT_BASE_URL` | ⛔ | 网关 base url,默认 `https://yunwu.ai/v1` |
| `DAILY_NEWS_AGENT_MODEL` | ⛔ | 模型名,默认 `deepseek-v4-pro` |
| `DAILY_NEWS_AGENT_TEMPERATURE` | ⛔ | 默认 0.2 |
| `DAILY_NEWS_AGENT_MAX_TOKENS` | ⛔ | 默认 65536 |
| `DAILY_NEWS_AGENT_TIMEOUT` | ⛔ | LLM 单次请求超时秒数,默认 300 |
| `DAILY_NEWS_AGENT_EXTRA_BODY` | ⛔ | 额外 JSON 字段(如关闭 thinking) |

修改 `.env` 后必须 `docker compose up -d`(或 `restart`)让容器重新读取。

---

## 数据持久化

```
./data/                  ← 宿主机
  ├── app.db             SQLite 主库:订阅、新闻、任务队列
  ├── app.db-wal         WAL,容器优雅退出时合并回主库
  ├── app.db-shm
  └── selectors.json
```

容器内挂载点是 `/app/data`,docker-compose 已经写好。

**备份**:压缩 `./data` 即可。`docker compose stop` 后再压更稳(避免 WAL 半写)。

**清空重来**:

```bash
docker compose down
rm -rf ./data
docker compose up -d
```

---

## 端口与访问

容器内固定监听 `[::]:8765`(双栈)。`docker-compose.yml` 把它映射到宿主 `8765`。想换端口直接改 compose 左边的数字:

```yaml
ports:
  - "0.0.0.0:80:8765"   # 宿主 80
  - "[::]:80:8765"
```

如果想从局域网其他机器访问,把宿主防火墙的 8765 放开即可。

---

## 升级到新版本

```bash
git pull
docker compose up -d --build
```

会重新构建镜像并替换容器。`./data` 不动,数据库迁移由容器启动时的 `alembic upgrade head` 自动跑。

---

## 故障排查

| 现象 | 排查 |
|---|---|
| 容器秒退,`docker compose logs` 看到 `DAILY_NEWS_AGENT_API_KEY is empty` | `.env` 里没填 Key,或 `.env` 不在项目根目录 |
| 浏览器打开 8765 是 404 | 确认 `frontend/dist` 在镜像里。本地 build 后再镜像里有没有?试 `docker compose build --no-cache` |
| 智能体一直转圈、不出结果 | 看 `docker compose logs -f`,常见是 LLM 网关 429 限流 / 模型名错 |
| Windows 上挂载 `data` 后 SQLite 报 `unable to open database file` | Docker Desktop → Settings → Resources → File Sharing,确认项目所在盘符已勾选 |
| 想看后端 API 文档 | 浏览器:<http://localhost:8765/api/docs> |

---

## 开发模式(不走 Docker)

如果你要改代码:

```bash
# 一次性安装
npm run setup

# 同时起前后端,前端 :4321,后端 :8765
npm run dev
```

详见 `backend/README.md`。
