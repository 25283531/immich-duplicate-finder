# 威联通 NAS 部署指南

## 回答你的问题：威联通 NAS 支持 Python 进程吗？

**✅ 完全支持！** 威联通 NAS 有三种方式运行 Python 进程：

| 方式 | 难度 | 推荐度 | 说明 |
|------|------|--------|------|
| **Docker（Container Station）** | ⭐⭐ | ⭐⭐⭐⭐⭐ | 最推荐，与 Immich 同架构 |
| **Python QPKG** | ⭐⭐⭐ | ⭐⭐⭐ | 需要命令行操作 |
| **Web 服务 + CGI** | ⭐⭐⭐⭐⭐ | ⭐ | 不适合 Streamlit |

---

## 方案 A：Docker 部署（强烈推荐 ⭐⭐⭐⭐⭐）

### 为什么推荐 Docker？

1. **与 Immich 同架构**：你的 Immich 已经是 Docker 部署的，管理方式一致
2. **无需 SSH**：全图形界面操作
3. **隔离性好**：不影响 NAS 系统环境
4. **易于升级**：重新构建镜像即可
5. **资源限制**：可设置内存/CPU上限

### 步骤 1：安装 Container Station

1. 打开 NAS 浏览器管理页面
2. 进入 **应用中心（App Center）**
3. 搜索 **Container Station** 并安装
4. 安装完成后打开 Container Station

### 步骤 2：创建项目目录

1. 在 NAS 上创建目录，例如：
   ```
   /volume1/docker/immich-duplicate-finder/
   ```
2. 上传 `docker-compose.yml` 到该目录（**只需一个文件**）

> 💡 **小贴士**：如果使用预构建镜像，无需上传整个项目，只需 `docker-compose.yml` 即可。GitHub Actions 会自动构建并推送镜像到 `ghcr.io/25283531/immich-duplicate-finder:latest`。

如果需要本地构建（不使用预构建镜像），则将 `app/` 目录下所有文件上传，并确保 `data/` 目录有写入权限。

### 步骤 3：构建 Docker 镜像

#### 方式 1：通过 Container Station 界面

1. 打开 Container Station
2. 点击 **创建** → **构建**
3. 填写配置：
   - 项目名称：`immich-duplicate-finder`
   - 构建上下文：`/volume1/docker/immich-duplicate-finder/`
   - Dockerfile 路径：`/volume1/docker/immich-duplicate-finder/Dockerfile`
4. 点击 **构建**，等待完成（首次约 5-10 分钟）

#### 方式 2：通过 SSH 命令行（更快）

```bash
# SSH 登录 NAS
cd /volume1/docker/immich-duplicate-finder/
docker build -t immich-duplicate-finder:latest .
```

### 步骤 4：创建容器

1. 在 Container Station 中点击 **创建** → **创建容器**
2. 选择刚构建的镜像 `immich-duplicate-finder:latest`
3. 配置容器参数：

   ```
   容器名称: immich-duplicate-finder
   端口映射: 8503:8503
   重启策略: 始终重启
   ```

4. 高级设置：

   ```
   卷挂载:
   - /volume1/docker/immich-duplicate-finder/data → /app/data
   
   环境变量:
   - TZ=Asia/Shanghai
   - PYTHONUNBUFFERED=1
   
   资源限制:
   - 内存: 2GB
   - CPU: 2核
   ```

5. 如果需要删除 NAS 上的源文件，还要挂载照片目录：

   ```
   # 只读挂载（安全）
   - /volume1/photo → /mnt/nas_photo:ro
   - /volume1/photo2 → /mnt/nas_photo2:ro
   ```

### 步骤 5：启动并访问

1. 点击 **启动** 按钮
2. 等待容器状态变为"运行中"
3. 浏览器访问：`http://NAS-IP:8503`

---

## 方案 B：Python QPKG 直接部署（⭐⭐⭐）

如果你不想用 Docker，可以直接在 NAS 上安装 Python 环境。

### 步骤 1：安装 Python QPKG

1. 打开 **应用中心（App Center）**
2. 搜索 **Python 3** 并安装
3. 安装完成后，Python 会安装到 `/usr/bin/python3`

### 步骤 2：开启 SSH 访问

1. 进入 **控制面板** → **网络与虚拟交换机** → **Telnet / SSH**
2. 启用 SSH 服务
3. 设置端口（默认 22）

### 步骤 3：通过 SSH 部署

```bash
# SSH 登录 NAS
ssh admin@NAS-IP

# 进入项目目录
cd /volume1/docker/immich-duplicate-finder/

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 启动 Streamlit
streamlit run app.py \
    --server.port 8503 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.runOnSave false
```

### 步骤 4：后台常驻

Streamlit 进程会随 SSH 会话结束而终止，需要使用以下方式保持后台运行：

```bash
# 方式 1：使用 nohup
nohup streamlit run app.py \
    --server.port 8503 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.runOnSave false \
    > streamlit.log 2>&1 &

# 方式 2：使用 screen（需要安装）
screen -dmS streamlit bash -c 'source /volume1/docker/immich-duplicate-finder/venv/bin/activate && streamlit run /volume1/docker/immich-duplicate-finder/app.py --server.port 8503 --server.address 0.0.0.0'
```

### 步骤 5：开机自启动

在 NAS 的 **控制面板** → **启动/关机** → **用户自定义启动脚本** 中添加：

```bash
#!/bin/sh
cd /volume1/docker/immich-duplicate-finder/
source venv/bin/activate
nohup streamlit run app.py \
    --server.port 8503 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.runOnSave false \
    >> streamlit.log 2>&1 &
```

---

## 方案 C：Web 服务 + CGI（不推荐 ⭐）

威联通的 Web 服务（Web Hosting Station）支持 PHP，但不适合运行 Streamlit 这种需要长连接的 Web 应用。

**不推荐此方案**，Streamlit 需要 WebSocket 支持，而威联通的 Web 服务不支持。

---

## 与 Immich 共存的注意事项

### 网络配置

```
NAS 内部网络:
├── Immich (Docker) - 端口 2283
├── Immich 重复查找工具 (Docker) - 端口 8503
└── NAS 管理界面 - 端口 8080/443
```

### 防火墙配置

确保以下端口已开放：
- **8503**：Streamlit 应用端口
- **2283**：Immich API 端口（内部访问）

### 数据互通

两个 Docker 容器需要在同一网络中才能互通：

```bash
# 创建共享网络（如果还没有）
docker network create immich-network

# 在 Streamlit 容器中加入网络
# Container Station → 容器设置 → 网络 → 加入 immich-network
```

---

## 常见问题

### Q: Docker 构建失败？

**A**: 检查网络连接，或使用清华镜像源（Dockerfile 中已配置）。

### Q: 容器启动后无法访问？

**A**: 
1. 检查端口映射是否正确
2. 检查 NAS 防火墙设置
3. 查看容器日志

### Q: 内存占用过高？

**A**: 
1. 在容器设置中限制内存（推荐 2GB）
2. 优先使用「Immich 原生检测」而非 FAISS
3. FAISS 索引文件较大，定期清理

### Q: 如何备份数据？

**A**: 数据存储在 `data/` 目录，直接复制即可。

---

## 方案对比总结

| 特性 | Docker | Python QPKG | Web 服务 |
|------|--------|-------------|----------|
| 难度 | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 图形界面 | ✅ | ❌ | ✅ |
| 隔离性 | ✅ | ❌ | ❌ |
| 自动重启 | ✅ | ❌（需配置） | ❌ |
| 资源限制 | ✅ | ❌ | ❌ |
| 与 Immich 互通 | ✅ | ✅ | ❌ |
| 推荐度 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ❌ |

**强烈推荐使用 Docker 部署**，与 Immich 保持一致的架构，管理和维护都更方便。
