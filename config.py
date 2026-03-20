import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Config:
    # MySQL配置
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', 3306))
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_NAME = os.getenv('DB_NAME', '')
    
    # Flask配置
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    FLASK_APP = os.getenv('FLASK_APP', 'app.py')
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    
    # 备份配置
    BACKUP_PATH = os.getenv('BACKUP_PATH', './backups')
    MAX_BACKUPS = int(os.getenv('MAX_BACKUPS', 30))
    
    # 确保备份目录存在
    os.makedirs(BACKUP_PATH, exist_ok=True)
