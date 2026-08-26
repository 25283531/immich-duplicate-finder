# ============================================================
# Immich 重复文件查找工具 Dockerfile
#
# 双变体：
#   --target runtime-core  轻量版（默认）→ 约 450MB
#                          仅支持 Immich 原生重复检测
#                          不含 PyTorch / FAISS / ResNet152 权重
#   --target runtime-full  完整版 → 约 5.5GB
#                          支持 Immich 原生检测 + FAISS 本地检测
#                          含 PyTorch 2.2.1 + torchvision + FAISS
#
# 两者都用多阶段构建 + pip --no-cache-dir + 清理 __pycache__
# ============================================================

# ------------------------------------------------------------
# 阶段 0 (base): 所有变体共用的基础运行时镜像
# 只装运行时的系统库（不装 gcc / g++ / build-essential）
# ------------------------------------------------------------
FROM python:3.10-slim-bookworm AS base

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Pillow-heif、ImageHash、Streamlit 显示所需的运行时库
# 注意：**不装 gcc**，编译动作全部放在 builder 阶段
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libde265-0 \
        libheif1 \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && find / -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

ENTRYPOINT ["/usr/bin/tini", "--"]

# ------------------------------------------------------------
# 阶段 1-builder-core: 编译+安装轻量版依赖（无 torch/faiss）
# ------------------------------------------------------------
FROM base AS builder-core

WORKDIR /install

# pillow-heif 在某些平台需要编译 C 扩展
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libc6-dev \
        libheif-dev \
        libde265-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-core.txt ./

# --prefix=/install 把包安装到指定目录，方便后面拷贝
RUN pip install --no-cache-dir --prefix=/install -r requirements-core.txt \
    && find /install -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true \
    && find /install -name "*.pyc" -delete 2>/dev/null || true \
    && find /install -name "tests" -type d -prune -exec rm -rf {} + 2>/dev/null || true \
    && find /install -name "*.a" -delete 2>/dev/null || true

# ------------------------------------------------------------
# 阶段 1-builder-full: 编译+安装完整版依赖（含 torch/faiss）
# ------------------------------------------------------------
FROM base AS builder-full

WORKDIR /install

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libc6-dev \
        libheif-dev \
        libde265-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && find /install -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true \
    && find /install -name "*.pyc" -delete 2>/dev/null || true \
    && find /install -name "tests" -type d -prune -exec rm -rf {} + 2>/dev/null || true \
    && find /install -name "*.a" -delete 2>/dev/null || true

# ------------------------------------------------------------
# 阶段 2A (runtime-core): 轻量版镜像（默认 ~450MB）
# ------------------------------------------------------------
FROM base AS runtime-core

# 拷贝 builder-core 安装好的 Python 包
COPY --from=builder-core /install /usr/local

# 拷贝应用代码
COPY . .

RUN mkdir -p /app/data && \
    python -c "import streamlit, numpy, PIL, requests, pillow_heif; print('core deps OK')"

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8503/_stcore/health')" || exit 1

EXPOSE 8503

CMD ["streamlit", "run", "app.py", \
     "--server.port", "8503", \
     "--server.address", "0.0.0.0", \
     "--server.headless", "true", \
     "--server.runOnSave", "false"]

# ------------------------------------------------------------
# 阶段 2B (runtime-full): 完整版镜像（含 PyTorch/FAISS ~5.5GB）
# 只有需要本地 FAISS 检测时才使用
# ------------------------------------------------------------
FROM base AS runtime-full

# 拷贝 builder-full 安装好的 Python 包（含 torch/faiss）
COPY --from=builder-full /install /usr/local

# 拷贝应用代码
COPY . .

RUN mkdir -p /app/data && \
    python -c "import streamlit, numpy, PIL, faiss, torch; print('full deps OK, torch version:', torch.__version__)"

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8503/_stcore/health')" || exit 1

EXPOSE 8503

CMD ["streamlit", "run", "app.py", \
     "--server.port", "8503", \
     "--server.address", "0.0.0.0", \
     "--server.headless", "true", \
     "--server.runOnSave", "false"]
