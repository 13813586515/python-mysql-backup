from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import os
import sys
import subprocess
from config import Config
from backup import MySQLBackup, get_backup_list, get_backup_logs
import json

app = Flask(__name__)
app.config.from_object(Config)

# 配置文件路径
CONFIG_FILE = '.env'

def read_config():
    """读取配置文件"""
    config = {
        'DB_HOST': Config.DB_HOST,
        'DB_PORT': Config.DB_PORT,
        'DB_USER': Config.DB_USER,
        'DB_PASSWORD': Config.DB_PASSWORD,
        'DB_NAME': Config.DB_NAME
    }
    return config

def write_config(config):
    """写入配置文件"""
    lines = []
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    
    # 更新或添加配置项
    config_map = {}
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            config_map[key] = value
    
    # 更新配置
    config_map.update(config)
    
    # 重新写入
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        for key, value in config_map.items():
            f.write(f"{key}={value}\n")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    """获取配置"""
    return jsonify(read_config())

@app.route('/api/config', methods=['POST'])
def save_config():
    """保存配置"""
    config = request.json
    write_config(config)
    return jsonify({'status': 'success', 'message': '配置已保存'})

@app.route('/api/test-connection', methods=['POST'])
def test_connection():
    """测试数据库连接"""
    config = request.json
    backup = MySQLBackup(
        host=config.get('DB_HOST'),
        port=int(config.get('DB_PORT', 3306)),
        user=config.get('DB_USER'),
        password=config.get('DB_PASSWORD'),
        database=config.get('DB_NAME')
    )
    success, message = backup.test_connection()
    return jsonify({'status': 'success' if success else 'error', 'message': message})

@app.route('/api/backup', methods=['POST'])
def do_backup():
    """执行备份"""
    config = request.json
    backup_type = config.get('type', 'all')  # all 或 single
    database = config.get('database')
    
    backup = MySQLBackup(
        host=config.get('DB_HOST'),
        port=int(config.get('DB_PORT', 3306)),
        user=config.get('DB_USER'),
        password=config.get('DB_PASSWORD'),
        database=database
    )
    
    if backup_type == 'single' and database:
        if backup.connect():
            backup_file = backup.backup_database(database)
            backup.disconnect()
            if backup_file:
                return jsonify({'status': 'success', 'message': f'备份成功: {os.path.basename(backup_file)}'})
            return jsonify({'status': 'error', 'message': '备份失败'})
        else:
            return jsonify({'status': 'error', 'message': '数据库连接失败'})
    else:
        backup_files = backup.backup_all_databases()
        if backup_files:
            return jsonify({'status': 'success', 'message': f'成功备份 {len(backup_files)} 个数据库'})
        return jsonify({'status': 'error', 'message': '没有可备份的数据库或备份失败'})

@app.route('/api/databases', methods=['POST'])
def get_databases():
    """获取数据库列表"""
    config = request.json
    backup = MySQLBackup(
        host=config.get('DB_HOST'),
        port=int(config.get('DB_PORT', 3306)),
        user=config.get('DB_USER'),
        password=config.get('DB_PASSWORD')
    )
    
    if backup.connect():
        databases = backup.get_all_databases()
        backup.disconnect()
        return jsonify({'status': 'success', 'databases': databases})
    return jsonify({'status': 'error', 'message': '数据库连接失败'})

@app.route('/api/backups', methods=['GET'])
def list_backups():
    """获取备份列表"""
    backups = get_backup_list()
    # 格式化时间和大小
    for b in backups:
        import datetime
        b['ctime_str'] = datetime.datetime.fromtimestamp(b['ctime']).strftime('%Y-%m-%d %H:%M:%S')
        size_kb = b['size'] / 1024
        if size_kb > 1024:
            b['size_str'] = f"{size_kb / 1024:.2f} MB"
        else:
            b['size_str'] = f"{size_kb:.2f} KB"
    return jsonify({'status': 'success', 'backups': backups})

@app.route('/api/download/<filename>', methods=['GET'])
def download_backup(filename):
    """下载备份文件"""
    filepath = os.path.join(Config.BACKUP_PATH, filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True, download_name=filename)
    return jsonify({'status': 'error', 'message': '文件不存在'}), 404

@app.route('/api/delete/<filename>', methods=['DELETE'])
def delete_backup(filename):
    """删除备份文件"""
    filepath = os.path.join(Config.BACKUP_PATH, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return jsonify({'status': 'success', 'message': '文件已删除'})
    return jsonify({'status': 'error', 'message': '文件不存在'}), 404

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """获取日志"""
    lines = request.args.get('lines', 100, type=int)
    logs = get_backup_logs(lines)
    return jsonify({'status': 'success', 'logs': logs})

def check_package_installed(package_name):
    """使用子进程检测包是否已安装"""
    try:
        # 使用pip show命令检测包是否安装
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'show', package_name],
            capture_output=True,
            text=True,
            check=True
        )
        return result.returncode == 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

@app.route('/api/check-env', methods=['GET'])
def check_env():
    """检查环境依赖"""
    requirements = ['flask', 'mysql-connector-python', 'python-dotenv']
    missing = []
    
    for req in requirements:
        if not check_package_installed(req):
            missing.append(req)
    
    return jsonify({
        'status': 'success',
        'all_installed': len(missing) == 0,
        'missing': missing
    })

@app.route('/api/install-deps', methods=['POST'])
def install_deps():
    """安装依赖"""
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])
        return jsonify({'status': 'success', 'message': '依赖安装成功，请刷新页面'})
    except subprocess.CalledProcessError as e:
        return jsonify({'status': 'error', 'message': f'安装失败: {str(e)}'})

if __name__ == '__main__':
    # 确保templates目录存在
    os.makedirs('templates', exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=Config.FLASK_DEBUG)
