from flask import Flask, render_template, request, jsonify, send_file, Response
import os
import json
import subprocess
import sys
import platform
from datetime import datetime
from config import Config
from backup_engine import MySQLBackupEngine
from logger import logger
import threading

app = Flask(__name__)
app.config.from_object(Config)

# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db_config.json')

# 全局配置缓存
current_config = {}

# 备份任务线程
backup_thread = None

def load_config():
    """加载配置"""
    global current_config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                current_config = json.load(f)
        except Exception as e:
            print(f"加载配置失败: {e}")
            current_config = {}
    else:
        current_config = {}
    return current_config

def save_config(config):
    """保存配置"""
    global current_config
    current_config = config
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存配置失败: {e}")
        return False

def get_backup_dir():
    """获取备份目录"""
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir

def get_backup_files():
    """获取所有备份文件"""
    backup_dir = get_backup_dir()
    files = []
    
    for root, dirs, filenames in os.walk(backup_dir):
        for filename in filenames:
            if filename.endswith(('.sql', '.sql.gz')):
                filepath = os.path.join(root, filename)
                stat = os.stat(filepath)
                files.append({
                    'name': filename,
                    'path': filepath,
                    'size': stat.st_size,
                    'size_formatted': format_size(stat.st_size),
                    'created': datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S'),
                    'database': filename.split('_')[0] if '_' in filename else 'unknown'
                })
    
    # 按创建时间排序
    files.sort(key=lambda x: x['created'], reverse=True)
    return files

def format_size(size_bytes):
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"

# 页面路由
@app.route('/')
def index():
    """主页"""
    return render_template('index.html')

# API路由 - 依赖检查
@app.route('/api/check-dependencies', methods=['GET'])
def check_dependencies():
    """检查环境依赖"""
    dependencies = {
        'python': {
            'name': 'Python',
            'installed': True,
            'version': platform.python_version(),
            'required': '3.7+'
        },
        'pymysql': {
            'name': 'PyMySQL',
            'installed': False,
            'version': None,
            'required': '1.0.0+',
            'install_cmd': 'pip install pymysql>=1.0.0'
        },
        'flask': {
            'name': 'Flask',
            'installed': False,
            'version': None,
            'required': '2.0.0+',
            'install_cmd': 'pip install flask>=2.0.0'
        }
    }
    
    # 检查PyMySQL
    try:
        import pymysql
        dependencies['pymysql']['installed'] = True
        dependencies['pymysql']['version'] = pymysql.__version__
    except ImportError:
        pass
    
    # 检查Flask
    try:
        import flask
        dependencies['flask']['installed'] = True
        dependencies['flask']['version'] = flask.__version__
    except ImportError:
        pass
    
    all_installed = all(dep['installed'] for dep in dependencies.values())
    
    return jsonify({
        'success': True,
        'all_installed': all_installed,
        'dependencies': dependencies
    })

@app.route('/api/install-dependencies', methods=['POST'])
def install_dependencies():
    """安装依赖"""
    try:
        # 使用pip安装依赖
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        
        if result.returncode == 0:
            logger.success('依赖安装成功')
            return jsonify({'success': True, 'message': '依赖安装成功'})
        else:
            logger.error('依赖安装失败', {'error': result.stderr})
            return jsonify({'success': False, 'message': f'安装失败: {result.stderr}'})
    except Exception as e:
        logger.error('依赖安装异常', {'error': str(e)})
        return jsonify({'success': False, 'message': str(e)})

# API路由 - 配置管理
@app.route('/api/config', methods=['GET'])
def get_config():
    """获取配置"""
    config = load_config()
    # 不返回密码
    safe_config = config.copy()
    if 'password' in safe_config:
        safe_config['password'] = '******'
    return jsonify({'success': True, 'config': safe_config})

@app.route('/api/config', methods=['POST'])
def update_config():
    """更新配置"""
    try:
        config = request.json
        
        # 验证必填字段
        required_fields = ['host', 'port', 'user']
        for field in required_fields:
            if not config.get(field):
                return jsonify({'success': False, 'message': f'缺少必填字段: {field}'})
        
        # 如果密码是掩码，保留原密码
        if config.get('password') == '******':
            old_config = load_config()
            config['password'] = old_config.get('password', '')
        
        if save_config(config):
            logger.info('配置已更新', {'host': config.get('host'), 'database': config.get('database')})
            return jsonify({'success': True, 'message': '配置保存成功'})
        else:
            return jsonify({'success': False, 'message': '配置保存失败'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/test-connection', methods=['POST'])
def test_connection():
    """测试数据库连接"""
    try:
        config = request.json
        
        engine = MySQLBackupEngine(
            host=config.get('host', 'localhost'),
            port=int(config.get('port', 3306)),
            user=config.get('user', 'root'),
            password=config.get('password', ''),
            database=config.get('database') or None
        )
        
        success, message = engine.test_connection()
        
        if success:
            logger.info('数据库连接测试成功', {'host': config.get('host')})
            return jsonify({'success': True, 'message': message})
        else:
            logger.error('数据库连接测试失败', {'host': config.get('host'), 'error': message})
            return jsonify({'success': False, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/databases', methods=['GET'])
def get_databases():
    """获取数据库列表"""
    try:
        config = load_config()
        
        engine = MySQLBackupEngine(
            host=config.get('host', 'localhost'),
            port=int(config.get('port', 3306)),
            user=config.get('user', 'root'),
            password=config.get('password', ''),
        )
        
        databases = engine.get_databases()
        engine.close()
        
        return jsonify({'success': True, 'databases': databases})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# API路由 - 备份管理
@app.route('/api/backup', methods=['POST'])
def create_backup():
    """创建备份"""
    try:
        data = request.json or {}
        databases = data.get('databases', [])
        compress = data.get('compress', True)
        
        config = load_config()
        
        engine = MySQLBackupEngine(
            host=config.get('host', 'localhost'),
            port=int(config.get('port', 3306)),
            user=config.get('user', 'root'),
            password=config.get('password', ''),
        )
        
        # 如果没有指定数据库，备份所有
        if not databases:
            databases = None
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = os.path.join(get_backup_dir(), timestamp)
        os.makedirs(backup_dir, exist_ok=True)
        
        backup_files = engine.backup_multiple_databases(databases, backup_dir, compress)
        engine.close()
        
        if backup_files:
            logger.success('备份完成', {
                'databases': databases,
                'files': [os.path.basename(f) for f in backup_files],
                'count': len(backup_files)
            })
            return jsonify({
                'success': True,
                'message': f'成功备份 {len(backup_files)} 个数据库',
                'files': [os.path.basename(f) for f in backup_files]
            })
        else:
            logger.error('备份失败，没有生成备份文件')
            return jsonify({'success': False, 'message': '备份失败，没有生成备份文件'})
            
    except Exception as e:
        logger.error('备份异常', {'error': str(e)})
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/backups', methods=['GET'])
def list_backups():
    """获取备份列表"""
    try:
        files = get_backup_files()
        return jsonify({'success': True, 'backups': files})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/download/<path:filename>')
def download_backup(filename):
    """下载备份文件"""
    try:
        # 安全检查：防止目录遍历
        if '..' in filename or filename.startswith('/'):
            return jsonify({'success': False, 'message': '非法文件名'}), 400
        
        backup_dir = get_backup_dir()
        filepath = os.path.join(backup_dir, filename)
        
        # 如果直接路径不存在，尝试在子目录中查找
        if not os.path.exists(filepath):
            for root, dirs, files in os.walk(backup_dir):
                if filename in files:
                    filepath = os.path.join(root, filename)
                    break
        
        if os.path.exists(filepath) and os.path.isfile(filepath):
            logger.info('下载备份文件', {'file': filename})
            return send_file(filepath, as_attachment=True)
        else:
            return jsonify({'success': False, 'message': '文件不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/delete/<path:filename>', methods=['DELETE'])
def delete_backup(filename):
    """删除备份文件"""
    try:
        # 安全检查
        if '..' in filename or filename.startswith('/'):
            return jsonify({'success': False, 'message': '非法文件名'}), 400
        
        backup_dir = get_backup_dir()
        filepath = os.path.join(backup_dir, filename)
        
        # 在子目录中查找
        if not os.path.exists(filepath):
            for root, dirs, files in os.walk(backup_dir):
                if filename in files:
                    filepath = os.path.join(root, filename)
                    break
        
        if os.path.exists(filepath) and os.path.isfile(filepath):
            os.remove(filepath)
            logger.info('删除备份文件', {'file': filename})
            return jsonify({'success': True, 'message': '文件已删除'})
        else:
            return jsonify({'success': False, 'message': '文件不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# API路由 - 日志管理
@app.route('/api/logs', methods=['GET'])
def get_logs():
    """获取日志"""
    try:
        date = request.args.get('date')
        level = request.args.get('level')
        limit = int(request.args.get('limit', 100))
        
        logs = logger.get_logs(date, level, limit)
        return jsonify({'success': True, 'logs': logs})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/logs/dates', methods=['GET'])
def get_log_dates():
    """获取日志日期列表"""
    try:
        dates = logger.get_log_dates()
        return jsonify({'success': True, 'dates': dates})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """获取统计信息"""
    try:
        stats = logger.get_stats()
        backups = get_backup_files()
        stats['total_files'] = len(backups)
        stats['total_size'] = sum(f['size'] for f in backups)
        stats['total_size_formatted'] = format_size(stats['total_size'])
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

if __name__ == '__main__':
    # 确保必要的目录存在
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups'), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs'), exist_ok=True)
    
    print("=" * 50)
    print("MySQL Backup Tool")
    print("=" * 50)
    print(f"访问地址: http://localhost:5000")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
