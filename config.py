import os

# 应用配置
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'mysql-backup-secret-key'
    
    # 数据库配置
    DB_HOST = os.environ.get('DB_HOST') or 'localhost'
    DB_PORT = int(os.environ.get('DB_PORT') or 3306)
    DB_USER = os.environ.get('DB_USER') or 'root'
    DB_PASSWORD = os.environ.get('DB_PASSWORD') or ''
    DB_NAME = os.environ.get('DB_NAME') or ''
    
    # 备份配置
    BACKUP_PATH = os.environ.get('BACKUP_PATH') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
    
    # 确保备份目录存在
    @staticmethod
    def init_app(app):
        if not os.path.exists(Config.BACKUP_PATH):
            os.makedirs(Config.BACKUP_PATH)
