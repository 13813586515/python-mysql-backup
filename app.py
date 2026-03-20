import os
import sys
import json
import subprocess
import importlib
import logging
from flask import Flask, render_template, request, jsonify, send_file
from backup_core import BackupManager, MySQLBackup, logger

app = Flask(__name__)
backup_manager = BackupManager()


def check_dependencies():
    required_packages = {
        'flask': 'flask',
        'pymysql': 'pymysql',
        'cryptography': 'cryptography'
    }
    
    results = {}
    for import_name, package_name in required_packages.items():
        try:
            importlib.import_module(import_name)
            results[package_name] = {'installed': True, 'version': None}
            try:
                module = importlib.import_module(import_name)
                if hasattr(module, '__version__'):
                    results[package_name]['version'] = module.__version__
            except:
                pass
        except ImportError:
            results[package_name] = {'installed': False, 'version': None}
    
    return results


def install_dependencies():
    try:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return True, "依赖安装成功"
    except subprocess.CalledProcessError as e:
        return False, f"依赖安装失败: {str(e)}"


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/check-dependencies', methods=['GET'])
def api_check_dependencies():
    deps = check_dependencies()
    all_installed = all(info['installed'] for info in deps.values())
    return jsonify({
        'success': True,
        'all_installed': all_installed,
        'dependencies': deps
    })


@app.route('/api/install-dependencies', methods=['POST'])
def api_install_dependencies():
    logger.info("开始安装依赖...")
    success, message = install_dependencies()
    if success:
        logger.info("依赖安装成功")
    else:
        logger.error(f"依赖安装失败: {message}")
    return jsonify({
        'success': success,
        'message': message
    })


@app.route('/api/config', methods=['GET'])
def api_get_config():
    config = backup_manager.config
    return jsonify({
        'success': True,
        'config': config
    })


@app.route('/api/config', methods=['POST'])
def api_save_config():
    try:
        config = request.get_json()
        if backup_manager.save_config(config):
            backup_manager.config = config
            logger.info("配置保存成功")
            return jsonify({
                'success': True,
                'message': '配置保存成功'
            })
        else:
            logger.error("配置保存失败")
            return jsonify({
                'success': False,
                'message': '配置保存失败'
            }), 500
    except Exception as e:
        logger.error(f"配置保存异常: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/test-connection', methods=['POST'])
def api_test_connection():
    try:
        data = request.get_json()
        backup = MySQLBackup(
            host=data.get('host', 'localhost'),
            port=data.get('port', 3306),
            user=data.get('user', ''),
            password=data.get('password', ''),
            charset=data.get('charset', 'utf8mb4')
        )
        success, message = backup.test_connection()
        if success:
            logger.info(f"数据库连接测试成功: {data.get('host')}:{data.get('port')}")
        else:
            logger.warning(f"数据库连接测试失败: {message}")
        return jsonify({
            'success': success,
            'message': message
        })
    except Exception as e:
        logger.error(f"数据库连接测试异常: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/databases', methods=['GET'])
def api_get_databases():
    try:
        backup = backup_manager.create_backup_instance()
        databases = backup.get_databases()
        backup.close()
        return jsonify({
            'success': True,
            'databases': databases
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/backup', methods=['POST'])
def api_backup():
    try:
        data = request.get_json()
        database = data.get('database')
        backup_all = data.get('backup_all', False)
        compress = data.get('compress', True)
        
        backup = backup_manager.create_backup_instance()
        
        if backup_all:
            logger.info("开始备份所有数据库...")
            results = backup.backup_all_databases(compress)
            backup.close()
            success_count = sum(1 for r in results if r['success'])
            logger.info(f"备份完成，成功: {success_count}/{len(results)}")
            return jsonify({
                'success': True,
                'results': results
            })
        else:
            if not database:
                return jsonify({
                    'success': False,
                    'message': '请指定要备份的数据库'
                }), 400
            
            logger.info(f"开始备份数据库: {database}")
            success, filepath, message = backup.backup_database(database, compress)
            backup.close()
            if success:
                logger.info(f"数据库备份成功: {filepath}")
            else:
                logger.error(f"数据库备份失败: {message}")
            return jsonify({
                'success': success,
                'filepath': filepath,
                'message': message
            })
    except Exception as e:
        logger.error(f"备份异常: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/backups', methods=['GET'])
def api_get_backups():
    try:
        files = backup_manager.get_backup_files()
        return jsonify({
            'success': True,
            'files': files
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/download/<filename>', methods=['GET'])
def api_download_backup(filename):
    try:
        filepath = os.path.join(backup_manager.backup_path, filename)
        if os.path.exists(filepath):
            return send_file(
                filepath,
                as_attachment=True,
                download_name=filename
            )
        else:
            return jsonify({
                'success': False,
                'message': '文件不存在'
            }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/delete-backup/<filename>', methods=['DELETE'])
def api_delete_backup(filename):
    try:
        success = backup_manager.delete_backup(filename)
        return jsonify({
            'success': success,
            'message': '删除成功' if success else '删除失败'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/logs', methods=['GET'])
def api_get_logs():
    try:
        limit = request.args.get('limit', 100, type=int)
        logs = backup_manager.get_backup_logs(limit)
        return jsonify({
            'success': True,
            'logs': logs
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


def main():
    config = backup_manager.config
    server_config = config.get('server', {})
    host = server_config.get('host', '127.0.0.1')
    port = server_config.get('port', 5000)
    
    logger.info("=" * 50)
    logger.info("MySQL 备份系统启动")
    logger.info(f"服务地址: http://{host}:{port}")
    logger.info("=" * 50)
    
    print(f"\n{'='*50}")
    print(f"MySQL 备份系统")
    print(f"{'='*50}")
    print(f"服务地址: http://{host}:{port}")
    print(f"请在浏览器中打开上述地址访问系统")
    print(f"{'='*50}\n")
    
    app.run(host=host, port=port, debug=False)


if __name__ == '__main__':
    main()
