# Metals Close · 公开金银数据采集与可视化图表工具
<img width="1600" height="3140" alt="metals-close-2026-11-25" src="https://github.com/user-attachments/assets/dc753990-f98c-424d-85b0-292cd25acd58" />
一个轻量级、可自托管的**金银公开数据采集、归档与可视化图表工具**（FastAPI + SQLite + 纯前端零框架），用于定时整理第三方公开渠道的黄金/白银历史价格、金银比历史分位、公开库存与持仓统计数据，支持按日期回溯、中英文切换、PC/手机双端适配与竖版高清数据长图导出。

> **定位声明**：本项目仅为开源的数据采集与可视化图表展示工具，用于技术学习与公开数据整理，**不涉及任何金融业务、证券期货咨询、行情撮合或投资建议**。

---

## 核心特性

- **八大可视化数据模块**：黄金/白银收盘数据、金银比（含 1 月 / 1 季 / 半年 / 1 年回看）与 10 年百分位排名、上海/印度本地公开参考价与价差、五大公开实物白银库存（COMEX / SHFE / SGE / LBMA）、COMEX 持仓与交割统计、LBMA 库存走势图、CFTC 持仓走势图、相关 ETF（GDX / SIL）数据对比。
- **交互式可视化图表**：三张历史折线图均带底部日期刻度，支持 PC 鼠标悬停与手机触摸滑动追踪曲线、实时显示日期与数值。
- **全自动每日采集**：内置后台定时任务（默认北京时间 `07:30` 与 `17:30`），自动采集最新公开收盘数据并写入 SQLite，无需重启服务。
- **CME 公开报表自动解析**：将浏览器从 CME 官网免费下载的 `MetalsIssuesAndStopsMTDReport.pdf` 放入 `data/cme/`，后台 30 秒内自动解析并入库。
- **竖版数据长图导出**：纯 Canvas 零外部依赖生成 2x 高清 PNG 竖版数据长图，支持一键下载与分享。
- **可切换访问模式**：支持一键开启免登录开放查看（内网测试/个人自用）或邮箱验证码访问控制。

---

## 目录结构

```text
metals-close-site/
├── backend/                  # FastAPI 后端（路由、SQLite、邮箱验证码、Paddle 订阅）
├── web/                      # 纯静态前端（index.html / app.js / i18n.js / share.js / styles.css）
├── tools/
│   ├── build_daily_snapshot.py  # 免费公开源每日采集与计算脚本
│   ├── ingest.py                # 种子 JSON 批量入库脚本
│   └── seed_subscriber.py       # 订阅邮箱白名单管理工具
├── data/
│   ├── seed/                 # 每日快照 JSON 归档（YYYY-MM-DD.*.json）
│   ├── cme/                  # 放置手动下载的 CME 交割通知 PDF（自动监听解析）
│   └── cache/                # CSV 本地缓存
├── nas-deploy/               # Docker / NAS 部署模板（Dockerfile、docker-compose.yml）
├── server.py                 # Uvicorn 启动入口
├── requirements.txt          # Python 依赖
└── .env.example              # 环境变量配置模板
```

---

## 快速部署

### 方式一：Docker Compose 部署（推荐，适合 NAS / Linux 服务器）

1. **准备环境变量**
   ```bash
   cp .env.example .env
   ```
   编辑 `.env`（重点修改 `SECRET_KEY`；如需内网免登录测试，设置 `MC_PUBLIC_ACCESS=1`）。

2. **构建并启动容器**
   ```bash
   # 若在仓库根目录使用 nas-deploy 里的编排文件，或进入部署目录执行：
   docker compose up -d --build
   ```
   > `docker-compose.yml` 默认将容器内 `8765` 端口映射到宿主机 `8790`（可按需修改），并将 `./data` 挂载为持久化数据卷。

3. **验证服务状态**
   ```bash
   docker logs --tail 30 metals-close
   curl -s http://127.0.0.1:8790/api/health
   ```
   返回 `{"ok": true, ...}` 后，浏览器访问 `http://<服务器IP>:8790` 即可。

---

### 方式二：本地 Python 直接运行（Windows / macOS / Linux）

要求 Python 3.11+（推荐 3.13）：

```bash
pip install -r requirements.txt
cp .env.example .env
# 首次导入种子数据
python tools/ingest.py
# 启动服务（默认监听 8765 端口）
python server.py
```

---

## 环境变量说明

| 变量名 | 默认值 | 说明 |
|---|---|---|
| `PORT` | `8765` | 容器/服务监听端口 |
| `SECRET_KEY` | *(必填)* | 会话 Cookie 与验证码签名密钥，生产环境务必使用随机长字符串 |
| `MC_PUBLIC_ACCESS` | `0` | `1` = 免登录/免订阅开放查看（适合内网测试/自用）；`0` = 开启订阅登录墙 |
| `MC_AUTO_UPDATE` | `1` | `1` = 启用容器内每日后台定时自动采集并入库 |
| `MC_AUTO_UPDATE_TIMES` | `07:30,17:30` | 自动采集触发时间（北京时间 `HH:MM`，逗号分隔） |
| `MC_DEV_MODE` | `0` | 仅本地开发调试用：`1` 时接口直接返回验证码，**公网严禁开启** |
| `MC_COOKIE_SECURE` | `0` | 启用 HTTPS 公网部署时请设为 `1` |
| `RESEND_API_KEY` / `RESEND_FROM_EMAIL` | 空 | 生产登录验证码邮件发送配置（Resend） |
| `PADDLE_*` | 空 | 订阅结账配置（Paddle API Key / Price ID / Webhook Secret） |

---

## 日常数据更新与维护

### 1. 自动更新（默认开启）
容器启动后会在后台按 `MC_AUTO_UPDATE_TIMES` 自动执行：
```bash
python tools/build_daily_snapshot.py --date auto --ingest
```
运行日志保存在 `data/auto_update.log`，更新后直接刷新网页即可，**无需重启容器**。

### 2. 手动补采指定交易日
```bash
# Docker 容器内执行
docker exec metals-close python tools/build_daily_snapshot.py --date 2026-11-20 --ingest

# 批量补采多日
for d in 2026-11-17 2026-11-18 2026-11-19; do
  docker exec metals-close python tools/build_daily_snapshot.py --date $d --ingest
done
```

### 3. 导入 CME 交割通知 PDF（免费补齐交割通知）
因 CME 官网对程序直连启用访问限制（`403`），脚本不做反爬绕过，采用本地自动监听解析方式：
1. 浏览器打开 [CME NYMEX/COMEX Delivery Notices](https://www.cmegroup.com/clearing/operations-and-deliveries/nymex-delivery-notices.html)；
2. 免费下载 **`MetalsIssuesAndStopsMTDReport.pdf`**（含当月每日与累计 COMEX 5000 白银交割手数）；
3. 放入 `data/cme/` 目录，容器后台每 30 秒自动检测变动并解析入库。

### 4. 管理订阅邮箱白名单（开启订阅墙后）
```bash
docker exec metals-close python tools/seed_subscriber.py add user@example.com --days 365
docker exec metals-close python tools/seed_subscriber.py remove user@example.com
```

---

## 数据来源与更新频率

| 模块 | 数据源 | 更新频率 | 口径说明 |
|---|---|---|---|
| 黄金 / 白银主行情、金银比、矿股、汇率 | Yahoo Finance (`GC=F` / `SI=F` / `GDX` / `SIL` / `CNY=X` / `INR=X`) | 每个交易日 | COMEX 连续期货日收盘（非现货口径） |
| 上海黄金 / 白银本地价 | 上海黄金交易所（SGE）官网 `Au99.99` / `Ag(T+D)` | 每个交易日 | 按当日 `CNY=X` 折算 USD/oz |
| 印度黄金 / 白银本地价 | 印度金银珠宝协会（IBJA）官网 PM 999 基准价 | 每个交易日 | 不含 GST，按当日 `INR=X` 折算 USD/oz（官网仅保留近期交易日） |
| 上期所白银仓单库存 | 上海期货交易所（SHFE）官网 | 日度 / 周五周报 | 总计仓单（含保税），千克折算 Moz |
| 上金所白银指定仓库库存 | 上海黄金交易所（SGE）《行情周报》PDF | 每周 | 千克折算 Moz |
| COMEX 注册 / 合格库存 & 上海白银周均溢价 | [MetalCharts.org](https://metalcharts.org) 免费 CSV | 每周 | 署名许可免费使用，页面已保留可见署名链接 |
| COMEX 白银总持仓量 & 曲线 | CFTC 官方公开 API（COT Disaggregated） | 每周（周二快照） | 纯期货总持仓张数 × 5,000 oz |
| LBMA 伦敦金库库存 & 曲线 | LBMA London Vault Holdings | 每月 | 月末总量（Moz） |
| COMEX 交割通知 | CME 官方免费 PDF（`data/cme/` 本地导入） | 按导入更新 | 手数 × 5,000 oz |

---

## 注意事项（上线 & 推 GitHub 必读）

### 1. 推送 GitHub 前的安全检查
- **切勿提交敏感文件**：`.gitignore` 已屏蔽 `.env`、`**/.env`、`*.db`、`data/.dev_secret`、`data/auto_update.log`、`data/cme/*.pdf`、`tools/_tmp/`。推送前请运行 `git status` 确认无 `.env`、`site.db` 或个人邮箱泄露。
- **不要把个人 NAS 内网 IP 或真实密钥写死在代码里**：所有密钥和域名均通过 `.env` 注入。

### 2. 公网生产部署安全要求
- 必须设置足够复杂的随机 `SECRET_KEY`；
- 必须关闭 `MC_DEV_MODE=0`，否则任何人都能在接口响应中直接看到验证码；
- 如需开启收费/白名单订阅，将 `MC_PUBLIC_ACCESS=0` 并配置好 Resend 发信与 HTTPS 反向代理（同时设置 `MC_COOKIE_SECURE=1`）；
- 定期备份 `data/` 目录（`site.db` 与 `data/seed/` 即为全站全部持久化数据）。

### 3. 网络环境要求
- 自动采集脚本需访问 Yahoo Finance、CFTC、IBJA、MetalCharts、SGE、SHFE；若部署在受限网络环境，请在 `docker-compose.yml` 的 `environment` 中配置 `HTTP_PROXY` / `HTTPS_PROXY` 或通过旁路由提供外网连通性。

### 4. 数据来源许可与合规边界
- **个人学习 / 内网自用**：上述公开免费数据源均可用于个人数据整理与可视化学习。
- **公开再分发提示**：请注意各第三方源站的许可协议：
  - CFTC COT 属美国政府公有领域数据；LBMA 月报需注明来源；MetalCharts 免费 CSV 须保留页面可见署名链接，禁止转售原始文件。
  - Yahoo Finance 非官方接口、IBJA 官网页面及 CME 报表受原机构使用条款约束，若用于任何商业用途请先获取对应官方授权。

### 5. 免责声明
本项目仅为公开数据的自动化采集与可视化图表工具，仅供技术学习与公开数据整理参考，**不涉及任何金融服务、证券期货咨询、行情撮合或买卖指引，不构成任何投资或决策建议**。不同来源的数据存在统计口径与更新频率差异（日/周/月），不可直接互换或相加；第三方原始数据可能存在延迟或修订，使用者需自行承担据此作出的任何决策与后果。
