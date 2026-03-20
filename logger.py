import os
import json
import time
from datetime import datetime
from threading import Lock

class BackupLogger:
    """备份日志管理器"""
    
    def __init__(self, log_dir=None):
        if log_dir is None:
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self.lock = Lock()
    
    def _get_log_file(self):
        """获取当天的日志文件路径"""
        date_str = datetime.now().strftime('%Y%m%d')
        return os.path.join(self.log_dir, f'backup_{date_str}.log')
    
    def log(self, level, message, details=None):
        """记录日志"""
        with self.lock:
            log_entry = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'level': level,
                'message': message,
                'details': details or {}
            }
            
            log_file = self._get_log_file()
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def info(self, message, details=None):
        """记录信息日志"""
        self.log('INFO', message, details)
    
    def error(self, message, details=None):
        """记录错误日志"""
        self.log('ERROR', message, details)
    
    def warning(self, message, details=None):
        """记录警告日志"""
        self.log('WARNING', message, details)
    
    def success(self, message, details=None):
        """记录成功日志"""
        self.log('SUCCESS', message, details)
    
    def get_logs(self, date=None, level=None, limit=100):
        """
        获取日志
        :param date: 日期字符串，格式 YYYYMMDD，None表示今天
        :param level: 日志级别过滤
        :param limit: 返回的最大条数
        :return: 日志列表
        """
        if date is None:
            date = datetime.now().strftime('%Y%m%d')
        
        log_file = os.path.join(self.log_dir, f'backup_{date}.log')
        
        if not os.path.exists(log_file):
            return []
        
        logs = []
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if level is None or entry.get('level') == level:
                            logs.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"读取日志文件失败: {e}")
        
        # 返回最新的日志
        return logs[-limit:][::-1]
    
    def get_log_dates(self):
        """获取所有有日志的日期列表"""
        dates = []
        if os.path.exists(self.log_dir):
            for filename in os.listdir(self.log_dir):
                if filename.startswith('backup_') and filename.endswith('.log'):
                    date_str = filename[7:-4]  # 提取日期部分
                    dates.append(date_str)
        return sorted(dates, reverse=True)
    
    def get_stats(self):
        """获取备份统计信息"""
        stats = {
            'total_backups': 0,
            'successful_backups': 0,
            'failed_backups': 0,
            'last_backup': None
        }
        
        dates = self.get_log_dates()
        for date in dates[:7]:  # 最近7天
            logs = self.get_logs(date, limit=1000)
            for log in logs:
                if '备份' in log.get('message', ''):
                    stats['total_backups'] += 1
                    if log.get('level') == 'SUCCESS':
                        stats['successful_backups'] += 1
                    elif log.get('level') == 'ERROR':
                        stats['failed_backups'] += 1
                    if stats['last_backup'] is None:
                        stats['last_backup'] = log.get('timestamp')
        
        return stats

# 全局日志实例
logger = BackupLogger()
