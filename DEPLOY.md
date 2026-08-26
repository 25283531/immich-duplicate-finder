# Immich 重复文件查找工具 - NAS 部署指南

## 一、部署前提

- NAS 与 Immich 服务器在同一台机器或同一局域网
- Immich 已正常运行（Docker 部署）
- 拥有 NAS 的文件访问权限（用于路径映射验证）

## 二、快速部署（Windows / NAS DSM 7.x+）

### 方案 A：直接运行（最简单）

1. **上传项目文件**
   - 将 `app/` 目录上传到 NAS 任意位置（如 `/volume1/docker/immich-duplicate-finder/`）

2. **安装 Python 环境**
   - NAS DSM 7.2+：套件中心安装 Python 3.9/3.10
   - 或使用 Docker 运行 Python 容器

3. **双击 `start.bat`**（Windows）或手动执行：
   ```bash
   cd /path/to/app/
   python -m venv venv
   source venv/bin/activate  # Linux
   pip install -r requirements.txt
   streamlit run app.py --server.port 8503 --server.address 0.0.0.0
   ```

4. **浏览器访问** `http://NAS-IP:8503`

### 方案 B：后台常驻运行（推荐）

#### Windows 服务模式

使用 NSSM（Non-Sucking Service Manager）将 Streamlit 注册为 Windows 服务：

```bash
# 下载 nssm: https://nssm.cc/
nssm install ImmichDupFinder "C:\path\to\venv\Scripts\python.exe" "-m streamlit run app.py --server.port 8503 --server.address 0.0.0.0"
nssm set ImmichDupFinder AppDirectory "C:\path\to\app"
nssm set ImmichDupFinder DisplayName "Immich 重复文件查找"
nssm start ImmichDupFinder
```

#### Linux systemd 服务

创建 `/etc/systemd/system/immich-duplicate-finder.service`：
```ini
[Unit]
Description=Immich 重复文件查找工具
After=network.target immich-server.service

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/app
ExecStart=/path/to/venv/bin/streamlit run app.py --server.port 8503 --server.address 0.0.0.0
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable immich-duplicate-finder
sudo systemctl start immich-duplicate-finder
```

### 方案 C：Nginx 反向代理（通过 80/443 端口访问）

1. 安装 Nginx（NAS 套件中心或 Docker）
2. 使用提供的 `nginx.example.conf` 配置反向代理
3. 修改 `server_name` 为你的域名或 NAS IP

## 三、首次配置

1. **登录设置**
   - 访问 `http://NAS-IP:8503`
   - 在「登录设置」中填入 Immich 服务器地址和 API Key
   - 点击「测试连接」确认

2. **路径映射配置**（仅批量删除需要）
   - 在「路径映射配置」中添加 Immich 容器路径 → NAS 宿主机路径
   - 例：`/usr/src/app/upload/library` → `/volume1/photo/library`

3. **开始使用**
   - 「🖼 Immich 原生重复检测」：快速处理精确重复
   - 「🔍 图片重复查找 (FAISS)」：灵活检测相似图

## 四、端口与防火墙

| 端口 | 协议 | 说明 |
|------|------|------|
| 8503 | TCP | Streamlit 应用端口 |
| 22   | TCP | SSH 管理（可选） |

如需通过 Nginx 访问，只需开放 80/443 端口。

## 五、数据存储

应用会在 `app/data/` 目录下创建以下 SQLite 数据库：

- `config.db` — 服务器连接配置
- `assets.db` — 已处理的资产记录
- `duplicates.db` — FAISS 重复检测结果
- `path_mappings.db` — 路径映射配置
- `operation_logs.db` — 操作日志

**备份建议**：定期备份 `app/data/` 目录。

## 六、常见问题

### Q: 启动慢？
A: 首次加载 ResNet152 模型（230MB）需要时间。建议使用「Immich 原生重复检测」代替 FAISS。

### Q: 连接 Immich 失败？
A: 检查 Immich 服务器地址是否正确，API Key 是否有效，网络是否可达。

### Q: 删除文件失败？
A: 检查「路径映射配置」是否正确映射了 Immich 容器路径到 NAS 路径。

### Q: 局域网其他设备无法访问？
A: 确认 `config.toml` 中 `address = "0.0.0.0"`，并检查防火墙设置。

### Q: 如何升级？
A: 覆盖 `app/` 下的 Python 文件，保留 `data/` 目录中的数据库即可。

## 七、技术栈

- **Streamlit** 1.32.2 — Web 框架
- **Python** 3.10+ — 运行时
- **FAISS** 1.8.0 — 向量相似度搜索
- **PyTorch/ResNet152** — 图像特征提取
- **Immich API** — 重复检测与资产管理
