#!/usr/bin/python
import os
import json
import uuid
import logging
import threading
import queue
import datetime
from typing import Dict, Any, Optional, List
from logging.handlers import QueueHandler, QueueListener
from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backup_engine import BackupEngine

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

CONFIG_FILE = 'config.json'
scheduler = BackgroundScheduler()
log_queue = queue.Queue()
backup_running = False
backup_progress = {'status': 'idle', 'message': '', 'progress': 0, 'total': 0}
backup_job = None
current_config_id = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        QueueHandler(log_queue)
    ]
)
logger = logging.getLogger(__name__)


def generate_id() -> str:
    return str(uuid.uuid4())[:8]


def load_all_configs() -> Dict[str, Any]:
    default_structure = {
        'global_config': {
            'backup_path': './backups',
            'retention_days': 30,
            'backup_mode': 'manual',
            'schedule_type': 'daily',
            'schedule_time': '02:00',
            'schedule_days': 7
        },
        'database_configs': [],
        'current_config_id': None
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if 'database_configs' not in loaded:
                    old_config = loaded.copy()
                    db_config = {
                        'id': generate_id(),
                        'name': '默认配置',
                        'db_host': old_config.get('db_host', 'localhost'),
                        'db_port': old_config.get('db_port', 3306),
                        'db_user': old_config.get('db_user', 'root'),
                        'db_password': old_config.get('db_password', ''),
                        'selected_databases': old_config.get('selected_databases', []),
                        'created_at': datetime.datetime.now().isoformat()
                    }
                    default_structure['database_configs'].append(db_config)
                    default_structure['current_config_id'] = db_config['id']
                    
                    if 'global_config' in old_config:
                        default_structure['global_config'] = old_config['global_config']
                    
                    save_all_configs(default_structure)
                    logger.info("旧配置已自动迁移到新格式")
                    
                    return default_structure
                return loaded
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
    
    return default_structure


def save_all_configs(configs: Dict[str, Any]) -> bool:
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(configs, f, ensure_ascii=False, indent=4)
        logger.info("配置已保存")
        return True
    except Exception as e:
        logger.error(f"保存配置文件失败: {str(e)}")
        return False


def get_database_config(config_id: str) -> Optional[Dict[str, Any]]:
    all_configs = load_all_configs()
    for config in all_configs.get('database_configs', []):
        if config['id'] == config_id:
            return config
    return None


def update_scheduler(global_config: Dict[str, Any]):
    global backup_job
    
    if backup_job:
        scheduler.remove_job(backup_job.id)
        backup_job = None
    
    if global_config.get('backup_mode') == 'scheduled':
        schedule_type = global_config.get('schedule_type', 'daily')
        schedule_time = global_config.get('schedule_time', '02:00')
        schedule_days = global_config.get('schedule_days', 7)
        
        try:
            hour, minute = map(int, schedule_time.split(':'))
        except:
            hour, minute = 2, 0
        
        if schedule_type == 'daily':
            trigger = CronTrigger(hour=hour, minute=minute)
        elif schedule_type == 'interval':
            trigger = IntervalTrigger(days=schedule_days)
        else:
            trigger = CronTrigger(hour=hour, minute=minute)
        
        backup_job = scheduler.add_job(
            scheduled_backup_task,
            trigger=trigger,
            id='backup_job',
            replace_existing=True
        )
        logger.info(f"定时任务已设置: {schedule_type} at {schedule_time}")


def progress_callback(current: int, total: int, message: str):
    global backup_progress
    backup_progress = {
        'status': 'running',
        'message': message,
        'progress': current,
        'total': total
    }


def perform_backup(config_id: str = None):
    global backup_running, backup_progress
    
    if backup_running:
        logger.warning("备份任务已在运行中")
        return
    
    all_configs = load_all_configs()
    
    if config_id is None:
        config_id = all_configs.get('current_config_id')
    
    if config_id is None:
        logger.error("未选择任何数据库配置")
        backup_progress = {
            'status': 'error',
            'message': '未选择任何数据库配置',
            'progress': 0,
            'total': 0
        }
        return
    
    db_config = get_database_config(config_id)
    if db_config is None:
        logger.error(f"找不到数据库配置: {config_id}")
        backup_progress = {
            'status': 'error',
            'message': f'找不到数据库配置: {config_id}',
            'progress': 0,
            'total': 0
        }
        return
    
    backup_running = True
    backup_progress = {'status': 'running', 'message': f'准备备份: {db_config.get("name", config_id)}', 'progress': 0, 'total': 0}
    
    try:
        global_config = all_configs.get('global_config', {})
        
        full_config = {
            **db_config,
            **global_config
        }
        
        engine = BackupEngine(full_config)
        
        selected_dbs = db_config.get('selected_databases', [])
        
        logger.info(f"使用配置 [{db_config.get('name', config_id)}] 开始备份")
        
        backup_files = engine.backup(databases=selected_dbs if selected_dbs else None, 
                                      progress_callback=progress_callback)
        
        retention_days = global_config.get('retention_days', 30)
        if retention_days >= 0:
            engine.cleanup_old_backups(retention_days)
        
        backup_progress = {
            'status': 'completed',
            'message': f'配置 [{db_config.get("name", config_id)}] 备份完成，共生成 {len(backup_files)} 个备份文件',
            'progress': 100,
            'total': 100
        }
        logger.info(f"配置 [{db_config.get('name', config_id)}] 备份任务执行完成")
        
    except Exception as e:
        backup_progress = {
            'status': 'error',
            'message': f'备份失败: {str(e)}',
            'progress': 0,
            'total': 0
        }
        logger.error(f"备份任务执行失败: {str(e)}")
    
    finally:
        backup_running = False


def scheduled_backup_task():
    logger.info("执行定时备份任务")
    all_configs = load_all_configs()
    config_id = all_configs.get('current_config_id')
    
    if config_id:
        perform_backup(config_id)
    else:
        logger.warning("定时备份任务: 未选择当前配置")


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)


@app.route('/api/configs', methods=['GET'])
def get_all_configs():
    configs = load_all_configs()
    result = {
        'global_config': configs.get('global_config', {}),
        'current_config_id': configs.get('current_config_id'),
        'database_configs': []
    }
    
    for db_config in configs.get('database_configs', []):
        db_config_copy = db_config.copy()
        db_config_copy['db_password'] = '********'
        result['database_configs'].append(db_config_copy)
    
    return jsonify({'success': True, 'configs': result})


@app.route('/api/configs/<config_id>', methods=['GET'])
def get_single_config(config_id: str):
    db_config = get_database_config(config_id)
    if db_config is None:
        return jsonify({'success': False, 'message': '配置不存在'})
    
    db_config_copy = db_config.copy()
    db_config_copy['db_password'] = '********'
    return jsonify({'success': True, 'config': db_config_copy})


@app.route('/api/configs', methods=['POST'])
def create_config():
    try:
        new_config = request.get_json()
        
        all_configs = load_all_configs()
        
        db_config = {
            'id': generate_id(),
            'name': new_config.get('name', '未命名配置'),
            'db_host': new_config.get('db_host', 'localhost'),
            'db_port': new_config.get('db_port', 3306),
            'db_user': new_config.get('db_user', 'root'),
            'db_password': new_config.get('db_password', ''),
            'selected_databases': new_config.get('selected_databases', []),
            'created_at': datetime.datetime.now().isoformat()
        }
        
        all_configs['database_configs'].append(db_config)
        
        if all_configs.get('current_config_id') is None:
            all_configs['current_config_id'] = db_config['id']
        
        if save_all_configs(all_configs):
            db_config_copy = db_config.copy()
            db_config_copy['db_password'] = '********'
            return jsonify({'success': True, 'message': '配置创建成功', 'config': db_config_copy})
        else:
            return jsonify({'success': False, 'message': '配置保存失败'})
    except Exception as e:
        logger.error(f"创建配置失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/configs/<config_id>', methods=['PUT'])
def update_config(config_id: str):
    try:
        update_data = request.get_json()
        
        all_configs = load_all_configs()
        
        found = False
        for idx, db_config in enumerate(all_configs.get('database_configs', [])):
            if db_config['id'] == config_id:
                db_config['name'] = update_data.get('name', db_config.get('name', '未命名配置'))
                db_config['db_host'] = update_data.get('db_host', db_config.get('db_host', 'localhost'))
                db_config['db_port'] = update_data.get('db_port', db_config.get('db_port', 3306))
                db_config['db_user'] = update_data.get('db_user', db_config.get('db_user', 'root'))
                
                if update_data.get('db_password') != '********':
                    db_config['db_password'] = update_data.get('db_password', db_config.get('db_password', ''))
                
                db_config['selected_databases'] = update_data.get('selected_databases', db_config.get('selected_databases', []))
                db_config['updated_at'] = datetime.datetime.now().isoformat()
                
                found = True
                break
        
        if not found:
            return jsonify({'success': False, 'message': '配置不存在'})
        
        if save_all_configs(all_configs):
            return jsonify({'success': True, 'message': '配置更新成功'})
        else:
            return jsonify({'success': False, 'message': '配置保存失败'})
    except Exception as e:
        logger.error(f"更新配置失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/configs/<config_id>', methods=['DELETE'])
def delete_config(config_id: str):
    try:
        all_configs = load_all_configs()
        
        db_configs = all_configs.get('database_configs', [])
        new_configs = [c for c in db_configs if c['id'] != config_id]
        
        if len(new_configs) == len(db_configs):
            return jsonify({'success': False, 'message': '配置不存在'})
        
        all_configs['database_configs'] = new_configs
        
        if all_configs.get('current_config_id') == config_id:
            if len(new_configs) > 0:
                all_configs['current_config_id'] = new_configs[0]['id']
            else:
                all_configs['current_config_id'] = None
        
        if save_all_configs(all_configs):
            return jsonify({'success': True, 'message': '配置删除成功'})
        else:
            return jsonify({'success': False, 'message': '配置保存失败'})
    except Exception as e:
        logger.error(f"删除配置失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/configs/<config_id>/select', methods=['POST'])
def select_config(config_id: str):
    try:
        all_configs = load_all_configs()
        
        db_config = get_database_config(config_id)
        if db_config is None:
            return jsonify({'success': False, 'message': '配置不存在'})
        
        all_configs['current_config_id'] = config_id
        
        if save_all_configs(all_configs):
            return jsonify({'success': True, 'message': f'已选择配置: {db_config.get("name", config_id)}'})
        else:
            return jsonify({'success': False, 'message': '配置保存失败'})
    except Exception as e:
        logger.error(f"选择配置失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/configs/<config_id>/test', methods=['POST'])
def test_config_connection(config_id: str):
    try:
        db_config = get_database_config(config_id)
        if db_config is None:
            return jsonify({'success': False, 'message': '配置不存在'})
        
        engine = BackupEngine(db_config)
        success, message = engine.test_connection()
        
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/configs/<config_id>/databases', methods=['POST'])
def get_config_databases(config_id: str):
    try:
        db_config = get_database_config(config_id)
        if db_config is None:
            return jsonify({'success': False, 'message': '配置不存在', 'databases': []})
        
        engine = BackupEngine(db_config)
        databases = engine.get_databases()
        
        return jsonify({'success': True, 'databases': databases})
    except Exception as e:
        logger.error(f"获取数据库列表失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e), 'databases': []})


@app.route('/api/global-config', methods=['GET'])
def get_global_config():
    all_configs = load_all_configs()
    return jsonify({'success': True, 'config': all_configs.get('global_config', {})})


@app.route('/api/global-config', methods=['PUT'])
def update_global_config():
    try:
        new_config = request.get_json()
        all_configs = load_all_configs()
        
        all_configs['global_config'] = {
            'backup_path': new_config.get('backup_path', './backups'),
            'retention_days': new_config.get('retention_days', 30),
            'backup_mode': new_config.get('backup_mode', 'manual'),
            'schedule_type': new_config.get('schedule_type', 'daily'),
            'schedule_time': new_config.get('schedule_time', '02:00'),
            'schedule_days': new_config.get('schedule_days', 7)
        }
        
        if save_all_configs(all_configs):
            update_scheduler(all_configs['global_config'])
            return jsonify({'success': True, 'message': '全局配置更新成功'})
        else:
            return jsonify({'success': False, 'message': '配置保存失败'})
    except Exception as e:
        logger.error(f"更新全局配置失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/backup/start', methods=['POST'])
def start_backup():
    global backup_running
    
    if backup_running:
        return jsonify({'success': False, 'message': '备份任务已在运行中'})
    
    data = request.get_json() or {}
    config_id = data.get('config_id')
    
    thread = threading.Thread(target=perform_backup, args=(config_id,))
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': '备份任务已启动'})


@app.route('/api/backup/status', methods=['GET'])
def backup_status():
    global backup_progress, backup_running
    return jsonify({
        'success': True,
        'running': backup_running,
        'progress': backup_progress
    })


@app.route('/api/backups', methods=['GET'])
def list_backups():
    try:
        all_configs = load_all_configs()
        global_config = all_configs.get('global_config', {})
        
        engine = BackupEngine({
            'backup_path': global_config.get('backup_path', './backups')
        })
        files = engine.get_backup_files()
        return jsonify({'success': True, 'files': files})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e), 'files': []})


@app.route('/api/backups/download', methods=['GET'])
def download_backup():
    try:
        filename = request.args.get('filename', '')
        if not filename:
            return jsonify({'success': False, 'message': '文件名不能为空'})
        
        all_configs = load_all_configs()
        global_config = all_configs.get('global_config', {})
        backup_path = global_config.get('backup_path', './backups')
        
        filepath = os.path.join(backup_path, filename)
        if not os.path.exists(filepath) or not os.path.isfile(filepath):
            return jsonify({'success': False, 'message': '文件不存在'})
        
        from flask import send_file
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/backups/cleanup', methods=['POST'])
def manual_cleanup():
    try:
        request_data = request.get_json() or {}
        all_configs = load_all_configs()
        global_config = all_configs.get('global_config', {})
        
        if 'retention_days' in request_data:
            retention_days = request_data.get('retention_days')
        else:
            retention_days = global_config.get('retention_days', 30)
        
        if isinstance(retention_days, str):
            retention_days = int(retention_days) if retention_days.isdigit() else 30
        
        engine = BackupEngine({
            'backup_path': global_config.get('backup_path', './backups')
        })
        deleted_count = engine.cleanup_old_backups(retention_days)
        
        return jsonify({
            'success': True, 
            'message': f'清理完成，共删除 {deleted_count} 个过期备份文件',
            'deleted_count': deleted_count,
            'retention_days': retention_days
        })
    except Exception as e:
        logger.error(f"手动清理失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/logs/stream')
def stream_logs():
    def event_stream():
        while True:
            try:
                record = log_queue.get(timeout=1.0)
                if record:
                    log_data = {
                        'timestamp': datetime.datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S'),
                        'level': record.levelname,
                        'message': record.getMessage()
                    }
                    yield f"data: {json.dumps(log_data)}\n\n"
            except queue.Empty:
                yield "data: {}\n\n"
    
    return Response(
        event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/api/scheduler/status', methods=['GET'])
def scheduler_status():
    global backup_job
    all_configs = load_all_configs()
    global_config = all_configs.get('global_config', {})
    
    job_info = None
    if backup_job:
        job_info = {
            'id': backup_job.id,
            'next_run_time': backup_job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if backup_job.next_run_time else None
        }
    
    return jsonify({
        'success': True,
        'scheduler_running': scheduler.running,
        'backup_mode': global_config.get('backup_mode', 'manual'),
        'schedule_type': global_config.get('schedule_type', 'daily'),
        'schedule_time': global_config.get('schedule_time', '02:00'),
        'job_info': job_info
    })


def init_app():
    os.makedirs('static', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    
    all_configs = load_all_configs()
    backup_path = all_configs.get('global_config', {}).get('backup_path', './backups')
    os.makedirs(backup_path, exist_ok=True)
    
    scheduler.start()
    logger.info("调度器已启动")
    
    update_scheduler(all_configs.get('global_config', {}))


if __name__ == '__main__':
    init_app()
    
    logger.info("启动Web服务器: http://localhost:5000")
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
