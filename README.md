# Immich 重复文件查找工具

> 基于 Immich API 的重复文件检测与批量删除工具，支持 Immich 原生检测和本地 FAISS 检测两种模式。

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python)
![Streamlit](https://img.shields.io/badge/Streamlit-1.32.2-FF4B4B?style=flat-square&logo=streamlit)
![Immich](https://img.shields.io/badge/Immich-v1.120+-4250AF?style=flat-square&logo=immich)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker)

[![构建并推送 Docker 镜像](https://github.com/25283531/immich-duplicate-finder/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/25283531/immich-duplicate-finder/actions/workflows/docker-publish.yml)
[![GitHub Container Registry](https://img.shields.io/badge/ghcr.io-latest-blue?style=flat-square&logo=github)](https://github.com/25283531/immich-duplicate-finder/pkgs/container/immich-duplicate-finder)

</div>

---

## 📖 目录

- [项目简介](#-项目简介)
- [功能特性](#-功能特性)
- [工作原理](#-工作原理)
- [两种检测模式对比](#-两种检测模式对比)
- [快速开始](#-快速开始)
- [部署指南](#-部署指南)
- [使用流程](#-使用流程)
- [配置说明](#-配置说明)
- [目录结构](#-目录结构)
- [技术栈](#-技术栈)
- [常见问题](#-常见问题)
- [更新日志](#-更新日志)

---

## 🎯 项目简介

**Immich 重复文件查找工具** 是一个专为 Immich 用户设计的重复照片/视频检测与清理工具。

它直接调用 Immich 的 REST API 获取资产信息，提供两种重复检测模式，并支持批量删除（包括从 NAS 磁盘删除源文件）。

### 解决的痛点

- 📸 **照片越来越多**：几年下来积累了成千上万张照片
- 🔁 **重复照片占空间**：同一张照片不同角度、不同压缩版本重复存在
- 😓 **手动清理太累**：逐张对比标记删除耗时耗力
- 💾 **存储空间浪费**：重复照片可能占用数 GB 甚至数 TB 空间

### 核心价值

通过自动化的重复检测和批量删除，帮助你：
- **节省 20-50%** 的照片存储空间
- **快速清理** 同内容的不同版本
- **保留最佳版本**（最高分辨率、最大文件等）
- **安全操作**：DryRun 预览 → 回收站删除 → 永久删除

---

## ✨ 功能特性

### 🔍 重复检测

| 功能 | 说明 |
|------|------|
| **Immich 原生检测** | 直接调用 Immich 服务端 API，秒级返回结果 |
| **FAISS 向量检测** | ResNet152 神经网络特征提取，检测视觉相似图片 |
| **灵活阈值调整** | FAISS 模式支持 0.0-10.0 距离阈值调整 |
| **批量智能选择** | 6 种保留策略（最大/最高分辨率/最早/外部库等） |

### 🗑 批量删除

| 功能 | 说明 |
|------|------|
| **DryRun 模式** | 模拟运行，只记录日志不实际删除 |
| **回收站模式** | 移动到 Immich 回收站，30 天内可恢复 |
| **永久删除** | 绕过回收站，直接从数据库清除 |
| **NAS 源文件删除** | 同步删除 NAS 磁盘上的原始文件 |
| **路径映射** | 支持容器路径到 NAS 宿主机路径转换 |

### 📊 操作管理

| 功能 | 说明 |
|------|------|
| **操作日志** | 所有删除操作记录，支持查询和导出 |
| **批量执行** | 分批处理，支持中途停止 |
| **进度显示** | 实时进度条和状态统计 |

---

## 🔧 工作原理

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户浏览器                                │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Streamlit Web 界面（导航/表单/对比图/日志）              │    │
│  └─────────────────────────────────────────────────────────┘    │
│                           ↕ HTTP/WebSocket                       │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                     Immich 重复查找工具（Python）                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐    │
│  │  Immich API │  │  FAISS 引擎 │  │   NAS 文件操作      │    │
│  │  ·获取资产  │  │  ·特征提取  │  │   ·路径映射         │    │
│  │  ·删除资产  │  │  ·向量搜索  │  │   ·文件删除         │    │
│  │  ·重复检测  │  │  ·相似度计算│  │   ·权限验证         │    │
│  └─────────────┘  └─────────────┘  └─────────────────────┘    │
│                           ↕                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  SQLite 数据库（配置/日志/索引）                         │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                           ↕ HTTP API
┌─────────────────────────────────────────────────────────────────┐
│                     Immich 服务器（Docker）                     │
│  · PostgreSQL 数据库                                           │
│  · Redis 缓存                                                  │
│  · ML 机器学习服务                                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🆚 两种检测模式对比

| 对比项 | Immich 原生检测 | FAISS 本地检测 |
|--------|----------------|---------------|
| **速度** | ⚡ 秒级返回 | 🐢 需要下载+特征提取 |
| **带宽** | ✅ 零下载 | ❌ 需下载所有缩略图 |
| **依赖** | ✅ 无需额外模型 | ❌ 需 230MB ResNet152 |
| **检测算法** | 文件名+时间戳+hash | ResNet152 特征向量+L2 距离 |
| **灵活性** | 固定算法 | 可调阈值（0.0-10.0） |
| **检测精度** | 精确重复 | 精确+相似 |
| **适用场景** | 快速去重 | 相似图检测 |

### 使用建议

1. **先用 Immich 原生检测**：快速处理精确重复（同一文件多次上传）
2. **再用 FAISS 检测**：灵活检测相似图（不同角度、不同压缩的同一内容）

---

## 🚀 快速开始

### 前置条件

- Immich 服务器已部署运行（v1.120+）
- Immich API Key（在 Immich 后台 → 设置 → 密钥中生成）
- NAS 管理员权限（用于路径映射和文件删除）

### 方式一：使用预构建镜像（最简单 ⭐⭐⭐⭐⭐）

每次提交代码，GitHub Actions 会自动构建多架构镜像（amd64/arm64）并推送到 GitHub Container Registry。
我们提供两种镜像变体，请按需选择（99% 的用户选轻量版即可）：

| 变体 | 标签 | 压缩体积 | 功能 | 推荐 |
|------|------|----------|------|------|
| **轻量版（默认）** | `latest` | **~450MB** | Immich 原生重复检测、批量删除、路径映射、操作日志 | ⭐ 99% 用户首选 |
| 完整版 | `latest-full` | ~5.5GB | 轻量版全部功能 **+** 本地 FAISS 向量检测（ResNet152 视觉相似度） | 需要本地检测相似图时用 |

#### A1. 轻量版（推荐，仅 Immich 原生检测，~450MB）

```bash
# 1. 拉取镜像（支持 amd64/arm64）
docker pull ghcr.io/25283531/immich-duplicate-finder:latest

# 2. 直接运行（无需克隆代码）
docker run -d \
  --name immich-duplicate-finder \
  --restart unless-stopped \
  -p 8503:8503 \
  -v immich-df-data:/app/data \
  -e TZ=Asia/Shanghai \
  ghcr.io/25283531/immich-duplicate-finder:latest

# 3. 如需访问 NAS 上的照片目录（用于物理删除源文件）
#    关键：容器内挂载路径必须等于 NAS 真实路径（左右两边相同）
docker run -d \
  --name immich-duplicate-finder \
  --restart unless-stopped \
  -p 8503:8503 \
  -v immich-df-data:/app/data \
  -v /share/照片视频/immich_photos:/share/照片视频/immich_photos \
  -v /share/照片视频:/share/照片视频 \
  -e TZ=Asia/Shanghai \
  ghcr.io/25283531/immich-duplicate-finder:latest

# 4. 浏览器访问
#    http://服务器IP:8503
```

#### A2. 完整版（含 FAISS 本地检测，~5.5GB）

```bash
docker pull ghcr.io/25283531/immich-duplicate-finder:latest-full

docker run -d \
  --name immich-duplicate-finder \
  --restart unless-stopped \
  -p 8503:8503 \
  -v immich-df-data:/app/data \
  -v /share/照片视频/immich_photos:/share/照片视频/immich_photos \
  -v /share/照片视频:/share/照片视频 \
  -e TZ=Asia/Shanghai \
  ghcr.io/25283531/immich-duplicate-finder:latest-full
```

**镜像标签说明**：

| 标签 | 适用 |
|------|------|
| `latest` | 轻量版最新（推荐） |
| `latest-full` | 完整版最新（含 FAISS） |
| `v0.2.0` | 轻量版指定版本 |
| `v0.2.0-full` | 完整版指定版本 |
| `main` | 轻量版 main 分支 |
| `main-full` | 完整版 main 分支 |

### 方式二：Docker Compose 本地构建（⭐⭐⭐⭐）

```bash
# 1. 克隆项目
git clone https://github.com/25283531/immich-duplicate-finder.git
cd immich-duplicate-finder/app

# 2. 修改配置（可选）
#    编辑 config.toml 修改端口等设置

# 3. 构建并启动
docker compose up -d

# 4. 查看日志
docker compose logs -f

# 5. 浏览器访问
#    http://服务器IP:8503
```

### 方式三：Python 直接运行

```bash
# 1. 克隆项目
git clone https://github.com/25283531/immich-duplicate-finder.git
cd immich-duplicate-finder/app

# 2. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动应用
streamlit run app.py --server.port 8503 --server.address 0.0.0.0

# 5. 浏览器访问
#    http://localhost:8503
```

### 方式三：威联通 NAS 部署

详细步骤请参考 [DEPLOY_QNAP.md](DEPLOY_QNAP.md)

---

## 📦 部署指南

详细部署文档：

| 文档 | 说明 |
|------|------|
| [DEPLOY_QNAP.md](DEPLOY_QNAP.md) | 威联通 NAS 专属部署指南 |
| [DEPLOY.md](DEPLOY.md) | 通用部署文档（PythonAnywhere/Hugging Face 等） |
| [nginx.example.conf](nginx.example.conf) | Nginx 反向代理配置示例 |

### 端口要求

| 端口 | 协议 | 说明 |
|------|------|------|
| 8503 | TCP | Streamlit 应用端口 |

### 防火墙

确保 8503 端口已开放，或通过 Nginx 反向代理使用 80/443 端口。

---

## 📝 使用流程

### 步骤 1：登录设置

1. 访问应用首页
2. 点击左侧导航「🔑 登录设置」
3. 填写：
   - Immich 服务器地址（如 `http://nas-ip:2283`）
   - API 密钥（在 Immich 后台生成）
   - 请求超时时间
4. 点击「💾 保存设置」
5. 点击「🔌 测试连接」确认连通

### 步骤 2：运行开关

1. 点击左侧导航「⚙️ 运行开关」
2. 配置：
   - **DryRun 模式**：首次运行默认开启，模拟操作不真实删除
   - **删除模式**：回收站（推荐）或永久删除
   - **批次大小**：每批处理的资产数量（默认 100）

### 步骤 3：路径映射（仅删除 NAS 文件需要）

1. 点击左侧导航「🗺 路径映射配置」
2. 添加映射关系：
   - Immich 容器路径 → NAS 宿主机路径
   - 示例：`/usr/src/app/upload/library` → `/volume1/photo`
3. 点击「测试 NAS 路径访问」验证

### 步骤 4：开始检测

#### Immich 原生检测（推荐首选）

1. 点击左侧导航「🖼 Immich 原生重复检测」
2. 点击「🔍 获取重复检测结果」
3. 查看重复组，点击「⭐ 保留此资产」标记保留项

#### FAISS 本地检测（灵活模式）

1. 点击左侧导航「🔍 图片重复查找 (FAISS)」
2. 调整 FAISS 阈值参数（可选）
3. 操作流程：
   - 点击「🖼️ 创建/更新 FAISS 索引」（首次）
   - 点击「📊 创建/更新重复数据库」
   - 点击「🔍 查找重复图片」查看结果

### 步骤 5：批量删除

1. 点击左侧导航「🚀 批量删除管理」
2. **Step 1**：审核待删清单
3. **Step 2**：DryRun 模拟执行（首次强烈建议）
4. **Step 3**：真实执行（需输入 DELETE/FORCE 字符串确认）

### 步骤 6：查看日志

1. 点击左侧导航「📜 操作日志」
2. 查看所有历史操作记录
3. 支持按 Batch ID、DryRun 状态筛选
4. 支持导出 JSON

---

## ⚙️ 配置说明

### config.toml

```toml
[server]
headless = true           # 无头模式（服务器部署）
port = 8503               # 服务端口
address = "0.0.0.0"       # 监听地址（0.0.0.0 表示所有网卡）

[browser]
gatherUsageStats = false  # 禁用使用统计收集

[theme]
base = "light"            # 主题（light/dark）

[client]
maxUploadSize = 100       # 最大上传大小（MB）
maxMessageSize = 500      # 最大消息大小（MB）
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| TZ | Asia/Shanghai | 时区设置 |
| PYTHONUNBUFFERED | 1 | Python 无缓冲输出 |

---

## 📁 目录结构

```
immich-duplicate-finder/
├── app/
│   ├── app.py                 # 主入口文件
│   ├── startup.py             # 启动配置（登录/运行开关/图片设置）
│   ├── api.py                 # Immich API 封装
│   ├── db.py                  # SQLite 数据库操作
│   ├── utility.py             # 工具函数
│   ├── imageDuplicate.py      # FAISS 重复检测
│   ├── imageProcessing.py    # 图像处理
│   ├── core/                  # 核心模块
│   │   ├── pathMapper.py      # 路径映射
│   │   ├── nasDeleter.py      # NAS 文件删除
│   │   └── smartSelect.py     # 智能选择策略
│   ├── ui_tabs/               # 页面组件
│   │   ├── mapping_page.py    # 路径映射配置页
│   │   ├── deletion_page.py   # 批量删除管理页
│   │   ├── log_page.py        # 操作日志页
│   │   └── immich_duplicates.py # Immich 原生检测页
│   ├── data/                  # 数据库存储（自动创建）
│   ├── config.toml            # Streamlit 配置
│   ├── requirements.txt       # Python 依赖
│   ├── Dockerfile             # Docker 构建文件
│   ├── docker-compose.yml     # Docker Compose 配置
│   ├── start.bat              # Windows 启动脚本
│   └── nginx.example.conf     # Nginx 配置示例
├── tests/                     # 单元测试
├── DEPLOY.md                  # 通用部署文档
├── DEPLOY_QNAP.md             # 威联通 NAS 部署文档
├── README.md                  # 本文件
└── LICENSE                    # 许可证
```

---

## 🛠 技术栈

| 类别 | 技术 | 版本 |
|------|------|------|
| **语言** | Python | 3.10+ |
| **Web 框架** | Streamlit | 1.32.2 |
| **向量搜索** | FAISS | 1.8.0 |
| **深度学习** | PyTorch / ResNet152 | 2.2.1 |
| **数据库** | SQLite | 3.x |
| **HTTP 客户端** | Requests | 2.31.0 |
| **图像处理** | Pillow / pillow-heif | 10.2.0 |
| **容器化** | Docker | 24.x |
| **反向代理** | Nginx | 1.24+ |

---

## ❓ 常见问题

### Q: 首次启动很慢？

**A**: 首次需要下载 ResNet152 模型权重（约 230MB）。建议使用「Immich 原生检测」代替 FAISS 检测。

### Q: 连接 Immich 失败？

**A**: 检查以下几点：
1. Immich 服务器地址是否正确（需包含端口）
2. API Key 是否有效（在 Immich 后台重新生成）
3. 网络是否可达（从运行工具的机器访问 Immich）
4. Immich 版本是否支持（需 v1.120+）

### Q: 删除文件失败？

**A**: 检查「路径映射配置」：
1. 确认 Immich 容器路径正确
2. 确认 NAS 宿主机路径正确
3. 确认 NAS 用户有读取/删除权限
4. 确认文件不是外部库（外部库可能无权删除）

### Q: FAISS 检测结果不准确？

**A**: 调整阈值：
- **严格去重**：最大阈值 0.2-0.3
- **平衡模式**（推荐）：最大阈值 0.5-0.7
- **宽松检测**：最大阈值 1.0-2.0

### Q: 如何升级？

**A**: 
1. 备份 `data/` 目录中的数据库文件
2. 拉取最新代码
3. 重新安装依赖：`pip install -r requirements.txt`
4. 重启应用

### Q: 支持视频检测吗？

**A**: 当前版本专注于图片检测。视频检测功能开发中，可在侧边栏看到入口。

### Q: 数据存储在哪里？

**A**: 所有数据存储在 `app/data/` 目录下的 SQLite 数据库中：
- `config.db` — 服务器连接配置
- `assets.db` — 已处理的资产记录
- `duplicates.db` — FAISS 重复检测结果
- `path_mappings.db` — 路径映射配置
- `operation_logs.db` — 操作日志

---

## 🔄 更新日志

### v0.2.0 (2026-08-26)

- 🎉 新增 **Immich 原生重复检测**（直接调用 `/api/duplicates`）
- 🔄 重构导航布局为侧边栏导航
- 🌐 全面汉化界面
- 🛡 改进安全模式（DryRun 强制启动）
- 📝 完善操作日志记录
- 🐳 新增 Docker 部署支持
- 📚 新增威联通 NAS 部署文档

### v0.1.0 (2026-08-25)

- 🚀 初始版本
- 📸 FAISS 向量相似度检测
- 🗑 批量删除管理
- 🗺 路径映射配置
- 📝 操作日志记录

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

---

## 🙏 致谢

- [Immich](https://immich.app/) — 优秀的开源照片管理工具
- [Streamlit](https://streamlit.io/) — 快速构建数据应用的 Python 框架
- [FAISS](https://github.com/facebookresearch/faiss) — Facebook 开源的向量搜索库

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 提交 Pull Request

---

## 📞 联系方式

如有问题，请提交 Issue。

**Enjoy your clean photo library!** 📸✨
