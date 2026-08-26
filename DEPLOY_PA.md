# PythonAnywhere 部署指南

## 一、注册与准备

1. 访问 https://www.pythonanywhere.com/ 注册账号
2. 选择 "Web Developer" 账户类型（免费版即可）

## 二、上传代码

### 方式 1：通过网页上传
1. 登录后进入 **Files** 页面
2. 在 `/home/你的用户名/` 下创建目录 `immich-duplicate-finder`
3. 将 `app/` 目录下所有文件上传

### 方式 2：通过 Git（推荐）
```bash
# 在本地电脑打包
# 然后在 PythonAnywhere 的 Consoles 页面上传
```

## 三、创建虚拟环境并安装依赖

1. 进入 **Consoles** 页面
2. 点击 "Open a bash console"
3. 执行：
```bash
cd /home/你的用户名/immich-duplicate-finder
mkvirtualenv --python=/usr/bin/python3.10 myenv
pip install -r requirements.txt
```

## 四、配置 WSGI

1. 进入 **Web** 页面
2. 点击 "Add a new web app"
3. 选择 "Manual configuration"
4. 选择 Python 3.10
5. 点击 "Next"，然后 "Next" 跳过框架选择

### 配置 WSGI 文件

在 **Web** 页面点击 wsgi 配置文件链接，修改为：

```python
import os
import sys

# 添加项目路径
project_home = '/home/你的用户名/immich-duplicate-finder'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# 切换工作目录
os.chdir(project_home)

# 激活虚拟环境
activate_this = '/home/你的用户名/.virtualenvs/myenv/bin/activate_this.py'
with open(activate_this) as file_:
    exec(file_.read(), {'__file__': activate_this})

# Streamlit 不使用传统 WSGI，需要特殊处理
# 实际上我们用 .bashrc 启动 Streamlit 服务
```

**重要**：Streamlit 不是传统 WSGI 应用，PythonAnywhere 需要特殊处理。

## 五、正确的 Streamlit 部署方式

### 在 .bashrc 中添加启动命令

进入 **Consoles** → 编辑 `.bashrc`，添加：

```bash
# Streamlit 启动
cd /home/你的用户名/immich-duplicate-finder
streamlit run app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.runOnSave false
```

### 使用守护进程（Daemon）

PythonAnywhere 免费版不支持持久后台进程，需要：

**付费版**：可以使用进程守护
```bash
# 在 Web 页面配置 "Startup" 命令
# 或者使用 supervisord
```

**免费版替代方案**：使用 **Always-on Tasks**
1. 进入 **Tasks** 页面
2. 添加一个每分钟执行的任务：
```bash
cd /home/你的用户名/immich-duplicate-finder && pgrep -f "streamlit" || (streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &)
```

## 六、配置域名

1. 进入 **Web** 页面
2. 点击你的应用域名（如 `yourname.pythonanywhere.com`）
3. 如果使用自定义域名，在 DNS 添加 CNAME 记录指向 PythonAnywhere

## 七、验证访问

浏览器访问：`https://你的用户名.pythonanywhere.com:8501`

## 八、注意事项

### 免费版限制
- 512MB 存储（ResNet152 模型约 230MB，注意空间）
- CPU 时间有限
- 无持久后台进程（需要 Tasks 守护）

### 优化建议
1. **优先使用 Immich 原生检测**：避免下载所有缩略图和加载 230MB 模型
2. **使用付费版**：获得更好的性能和持久进程
3. **定期清理**：清理 data/ 目录下的临时文件

## 九、替代平台对比

| 平台 | 免费 | Streamlit 支持 | 自定义域名 | 后台持久 |
|------|------|----------------|------------|----------|
| PythonAnywhere | 512MB | ✅ | ✅ | 需付费/Tasks |
| Railway | $5额度 | ✅ | ✅ | ✅ |
| Render | 750h/月 | ✅ | ✅ | ✅（会休眠） |
| Hugging Face | 无限 | ✅ | ❌ | ✅ |

## 十、最简方案：Hugging Face Spaces

如果你想要**最简单**的方案，Hugging Face Spaces 完全免费且原生支持 Streamlit：

1. 访问 https://huggingface.co/spaces
2. 创建 New Space → 选择 Streamlit
3. 上传代码（app/ 目录内容）
4. 添加 `requirements.txt`
5. 自动部署完成

**优点**：
- 完全免费
- 自动部署
- 自动 HTTPS
- 支持自定义域名（Pro 版）
- 无需配置任何服务

**缺点**：
- 国内访问可能较慢
- 有使用配额
