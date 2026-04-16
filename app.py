#!/usr/bin/python
import os
import json
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        QueueHandler(log_queue)
    ]
)
logger = logging.getLogger(__name__)


def load_config() -> Dict[str, Any]:
    default_config = {
        'db_host': 'localhost',
        'db_port': 3306,
        'db_user': 'root',
        'db_password': '',
        'db_name': '',
        'backup_path': './backups',
        'retention_days': 30,
        'backup_mode': 'manual',
        'schedule_type': 'daily',
        'schedule_time': '02:00',
        'schedule_days': 7,
        'selected_databases': []
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
                default_config.update(loaded_config)
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
    
    return default_config


def save_config(config: Dict[str, Any]) -> bool:
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        logger.info("配置已保存")
        return True
    except Exception as e:
        logger.error(f"保存配置文件失败: {str(e)}")
        return False


def update_scheduler(config: Dict[str, Any]):
    global backup_job
    
    if backup_job:
        scheduler.remove_job(backup_job.id)
        backup_job = None
    
    if config.get('backup_mode') == 'scheduled':
        schedule_type = config.get('schedule_type', 'daily')
        schedule_time = config.get('schedule_time', '02:00')
        schedule_days = config.get('schedule_days', 7)
        
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


def perform_backup():
    global backup_running, backup_progress
    
    if backup_running:
        logger.warning("备份任务已在运行中")
        return
    
    backup_running = True
    backup_progress = {'status': 'running', 'message': '准备开始备份...', 'progress': 0, 'total': 0}
    
    try:
        config = load_config()
        engine = BackupEngine(config)
        
        selected_dbs = config.get('selected_databases', [])
        if not selected_dbs and config.get('db_name'):
            selected_dbs = [config['db_name']]
        
        backup_files = engine.backup(databases=selected_dbs if selected_dbs else None, 
                                      progress_callback=progress_callback)
        
        retention_days = config.get('retention_days', 30)
        if retention_days > 0:
            engine.cleanup_old_backups(retention_days)
        
        backup_progress = {
            'status': 'completed',
            'message': f'备份完成，共生成 {len(backup_files)} 个备份文件',
            'progress': 100,
            'total': 100
        }
        logger.info("备份任务执行完成")
        
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
    perform_backup()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)


@app.route('/api/config', methods=['GET'])
def get_config():
    config = load_config()
    config_copy = config.copy()
    config_copy['db_password'] = '********'
    return jsonify({'success': True, 'config': config_copy})


@app.route('/api/config', methods=['POST'])
def save_config_api():
    try:
        new_config = request.get_json()
        
        if new_config.get('db_password') == '********':
            old_config = load_config()
            new_config['db_password'] = old_config.get('db_password', '')
        
        if save_config(new_config):
            update_scheduler(new_config)
            return jsonify({'success': True, 'message': '配置保存成功'})
        else:
            return jsonify({'success': False, 'message': '配置保存失败'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/config/test', methods=['POST'])
def test_connection():
    try:
        config = request.get_json()
        
        if config.get('db_password') == '********':
            old_config = load_config()
            config['db_password'] = old_config.get('db_password', '')
        
        engine = BackupEngine(config)
        success, message = engine.test_connection()
        
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/databases', methods=['POST'])
def get_databases():
    try:
        config = request.get_json()
        
        if config.get('db_password') == '********':
            old_config = load_config()
            config['db_password'] = old_config.get('db_password', '')
        
        engine = BackupEngine(config)
        databases = engine.get_databases()
        
        return jsonify({'success': True, 'databases': databases})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e), 'databases': []})


@app.route('/api/backup/start', methods=['POST'])
def start_backup():
    global backup_running
    
    if backup_running:
        return jsonify({'success': False, 'message': '备份任务已在运行中'})
    
    thread = threading.Thread(target=perform_backup)
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
        config = load_config()
        engine = BackupEngine(config)
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
        
        config = load_config()
        backup_path = config.get('backup_path', './backups')
        
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
    config = load_config()
    
    job_info = None
    if backup_job:
        job_info = {
            'id': backup_job.id,
            'next_run_time': backup_job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if backup_job.next_run_time else None
        }
    
    return jsonify({
        'success': True,
        'scheduler_running': scheduler.running,
        'backup_mode': config.get('backup_mode', 'manual'),
        'schedule_type': config.get('schedule_type', 'daily'),
        'schedule_time': config.get('schedule_time', '02:00'),
        'job_info': job_info
    })


def init_app():
    os.makedirs('static', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('backups', exist_ok=True)
    
    scheduler.start()
    logger.info("调度器已启动")
    
    config = load_config()
    update_scheduler(config)


if __name__ == '__main__':
    init_app()
    
    logger.info("启动Web服务器: http://localhost:5000")
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
