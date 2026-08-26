# 基于 Python 3.10 官方镜像（锁定 bookworm 避免 bullseye EOL）
FROM python:3.10-slim-bookworm

# 设置工作目录
WORKDIR /app

# 安装系统依赖
# bookworm 中 libgl1-mesa-glx 已被 libgl1 替代
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
# 通过 ARG 参数控制是否使用国内镜像源（默认不使用，适配 GitHub Actions）
ARG PIP_INDEX_URL=""
ARG PIP_TRUSTED_HOST=""
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip config set global.index-url "$PIP_INDEX_URL" && \
        pip config set global.trusted-host "$PIP_TRUSTED_HOST"; \
    fi && \
    pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data

# 创建非 root 用户运行（安全）
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# 暴露端口
EXPOSE 8503

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8503/_stcore/health')" || exit 1

# 启动命令
CMD ["streamlit", "run", "app.py", \
     "--server.port", "8503", \
     "--server.address", "0.0.0.0", \
     "--server.headless", "true", \
     "--server.runOnSave", "false"]
