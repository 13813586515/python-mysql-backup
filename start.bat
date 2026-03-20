@echo off
chcp 65001 >nul
echo ========================================
echo    MySQL 备份系统 启动脚本
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8 或更高版本
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [信息] 检测到 Python 环境
echo.

if not exist "venv" (
    echo [信息] 正在创建虚拟环境...
    python -m venv venv
    echo [信息] 虚拟环境创建完成
    echo.
)

echo [信息] 正在激活虚拟环境...
call venv\Scripts\activate.bat

echo [信息] 正在检查/安装依赖...
pip install -r requirements.txt -q

echo.
echo [信息] 正在启动服务...
echo ========================================
echo.

python app.py

pause
