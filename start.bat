@echo off
chcp 65001 >nul
title Immich 重复文件查找工具

echo ============================================
echo   Immich 重复文件查找工具 - 启动脚本
echo ============================================
echo.

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 检查 Python 环境
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 检查虚拟环境
if not exist "venv\Scripts\activate.bat" (
    echo [首次部署] 创建 Python 虚拟环境...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
)

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 检查并安装依赖
if not exist ".deps_installed" (
    echo [首次部署] 安装依赖包（可能需要几分钟）...
    echo [提示] 如果下载慢，可以使用国内镜像:
    echo        pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo.
    
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo.
        echo [警告] 默认源安装失败，尝试使用清华镜像源...
        pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        if %errorlevel% neq 0 (
            echo [错误] 依赖安装失败
            pause
            exit /b 1
        )
    )
    type nul > .deps_installed
    echo.
    echo [完成] 依赖安装成功
)

REM 确保数据目录存在
if not exist "data" mkdir data

REM 启动 Streamlit
echo.
echo [启动] 正在启动应用...
echo [访问] http://localhost:8503
echo [停止] 按 Ctrl+C 停止服务
echo.

streamlit run app.py --server.port 8503 --server.headless true --server.runOnSave false

pause
