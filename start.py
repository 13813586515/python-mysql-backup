#!/usr/bin/env python
import os
import sys
import subprocess

def check_python_version():
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print("[错误] 需要 Python 3.8 或更高版本")
        print(f"当前版本: Python {version.major}.{version.minor}.{version.micro}")
        return False
    return True

def create_venv():
    if not os.path.exists('venv'):
        print("[信息] 正在创建虚拟环境...")
        subprocess.run([sys.executable, '-m', 'venv', 'venv'], check=True)
        print("[信息] 虚拟环境创建完成")
    return True

def get_venv_python():
    if sys.platform == 'win32':
        return os.path.join('venv', 'Scripts', 'python.exe')
    return os.path.join('venv', 'bin', 'python')

def install_dependencies():
    print("[信息] 正在检查/安装依赖...")
    venv_python = get_venv_python()
    subprocess.run([venv_python, '-m', 'pip', 'install', '-r', 'requirements.txt', '-q'], check=True)
    print("[信息] 依赖安装完成")

def main():
    print("=" * 50)
    print("   MySQL 备份系统 启动脚本")
    print("=" * 50)
    print()
    
    if not check_python_version():
        sys.exit(1)
    
    print(f"[信息] Python 版本: {sys.version}")
    print()
    
    create_venv()
    install_dependencies()
    
    print()
    print("[信息] 正在启动服务...")
    print("=" * 50)
    print()
    
    venv_python = get_venv_python()
    os.execv(venv_python, [venv_python, 'app.py'])

if __name__ == '__main__':
    main()
