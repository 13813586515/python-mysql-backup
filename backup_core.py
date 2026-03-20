import os
import gzip
import json
import logging
import datetime
import pymysql
from pymysql.cursors import DictCursor
from typing import List, Dict, Optional, Tuple
from io import StringIO

_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups', 'logs')
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, f"backup_{datetime.datetime.now().strftime('%Y%m%d')}.log")

_file_handler = logging.FileHandler(_log_file, encoding='utf-8')
_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        _file_handler
    ]
)
logger = logging.getLogger(__name__)


class MySQLBackup:
    def __init__(self, host: str, port: int, user: str, password: str, 
                 charset: str = 'utf8mb4', backup_path: str = './backups'):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.charset = charset
        self.backup_path = backup_path
        self.connection = None
        
    def connect(self) -> bool:
        try:
            self.connection = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                charset=self.charset,
                cursorclass=DictCursor
            )
            logger.info(f"成功连接到MySQL服务器: {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"连接MySQL服务器失败: {str(e)}")
            return False
    
    def close(self):
        if self.connection:
            self.connection.close()
            logger.info("MySQL连接已关闭")
    
    def test_connection(self) -> Tuple[bool, str]:
        try:
            conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                charset=self.charset,
                connect_timeout=10
            )
            conn.close()
            return True, "连接成功"
        except Exception as e:
            return False, str(e)
    
    def get_databases(self) -> List[str]:
        if not self.connection:
            if not self.connect():
                return []
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SHOW DATABASES")
                databases = [row['Database'] for row in cursor.fetchall()]
                system_dbs = ['information_schema', 'mysql', 'performance_schema', 'sys']
                databases = [db for db in databases if db not in system_dbs]
                return databases
        except Exception as e:
            logger.error(f"获取数据库列表失败: {str(e)}")
            return []
    
    def get_tables(self, database: str) -> List[str]:
        if not self.connection:
            if not self.connect():
                return []
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(f"SHOW TABLES FROM `{database}`")
                tables = [list(row.values())[0] for row in cursor.fetchall()]
                return tables
        except Exception as e:
            logger.error(f"获取表列表失败: {str(e)}")
            return []
    
    def _escape_value(self, value) -> str:
        if value is None:
            return 'NULL'
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, bytes):
            return "0x" + value.hex()
        else:
            escaped = str(value).replace('\\', '\\\\').replace("'", "\\'")
            return f"'{escaped}'"
    
    def _get_create_table_sql(self, database: str, table: str, cursor) -> str:
        cursor.execute(f"SHOW CREATE TABLE `{database}`.`{table}`")
        result = cursor.fetchone()
        create_sql = result['Create Table']
        return f"DROP TABLE IF EXISTS `{table}`;\n{create_sql};\n"
    
    def _get_table_data_sql(self, database: str, table: str, cursor) -> str:
        output = StringIO()
        cursor.execute(f"SELECT * FROM `{database}`.`{table}`")
        columns = [desc[0] for desc in cursor.description]
        
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            
            for row in rows:
                values = ', '.join(self._escape_value(v) for v in row.values())
                output.write(f"INSERT INTO `{table}` (`{'`, `'.join(columns)}`) VALUES ({values});\n")
        
        return output.getvalue()
    
    def backup_database(self, database: str, compress: bool = True) -> Tuple[bool, str, str]:
        if not self.connection:
            if not self.connect():
                return False, "", "无法连接到MySQL服务器"
        
        os.makedirs(self.backup_path, exist_ok=True)
        
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{database}_{timestamp}.sql"
        if compress:
            filename += ".gz"
        
        filepath = os.path.join(self.backup_path, filename)
        
        try:
            with self.connection.cursor() as cursor:
                sql_content = StringIO()
                sql_content.write(f"-- MySQL Backup\n")
                sql_content.write(f"-- Database: {database}\n")
                sql_content.write(f"-- Generated at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                sql_content.write(f"-- \n\n")
                sql_content.write(f"SET NAMES utf8mb4;\n")
                sql_content.write(f"SET FOREIGN_KEY_CHECKS = 0;\n\n")
                sql_content.write(f"-- Create database\n")
                sql_content.write(f"CREATE DATABASE IF NOT EXISTS `{database}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n")
                sql_content.write(f"USE `{database}`;\n\n")
                
                tables = self.get_tables(database)
                logger.info(f"正在备份数据库 {database}，共 {len(tables)} 个表")
                
                for i, table in enumerate(tables, 1):
                    logger.info(f"备份表 {i}/{len(tables)}: {table}")
                    sql_content.write(f"-- Table: {table}\n")
                    sql_content.write(self._get_create_table_sql(database, table, cursor))
                    sql_content.write("\n")
                    sql_content.write(self._get_table_data_sql(database, table, cursor))
                    sql_content.write("\n")
                
                sql_content.write("SET FOREIGN_KEY_CHECKS = 1;\n")
                
                content = sql_content.getvalue()
                
                if compress:
                    with gzip.open(filepath, 'wt', encoding='utf-8') as f:
                        f.write(content)
                else:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content)
                
                logger.info(f"备份完成: {filepath}")
                return True, filepath, "备份成功"
                
        except Exception as e:
            logger.error(f"备份数据库失败: {str(e)}")
            return False, "", str(e)
    
    def backup_all_databases(self, compress: bool = True) -> List[Dict]:
        databases = self.get_databases()
        results = []
        
        for db in databases:
            success, filepath, message = self.backup_database(db, compress)
            results.append({
                'database': db,
                'success': success,
                'filepath': filepath,
                'message': message
            })
        
        return results


class BackupManager:
    def __init__(self, config_path: str = 'config.json'):
        self.config_path = config_path
        self.config = self._load_config()
        self.backup_path = self.config.get('backup', {}).get('path', './backups')
        if not os.path.isabs(self.backup_path):
            self.backup_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), self.backup_path)
        self.log_path = os.path.join(self.backup_path, 'logs')
        os.makedirs(self.log_path, exist_ok=True)
        
    def _load_config(self) -> Dict:
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def save_config(self, config: Dict) -> bool:
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            self.config = config
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {str(e)}")
            return False
    
    def get_db_config(self) -> Dict:
        return self.config.get('database', {})
    
    def create_backup_instance(self) -> MySQLBackup:
        db_config = self.get_db_config()
        return MySQLBackup(
            host=db_config.get('host', 'localhost'),
            port=db_config.get('port', 3306),
            user=db_config.get('user', ''),
            password=db_config.get('password', ''),
            charset=db_config.get('charset', 'utf8mb4'),
            backup_path=self.backup_path
        )
    
    def get_backup_files(self) -> List[Dict]:
        files = []
        if not os.path.exists(self.backup_path):
            return files
        
        for filename in os.listdir(self.backup_path):
            if filename.endswith('.sql') or filename.endswith('.sql.gz'):
                filepath = os.path.join(self.backup_path, filename)
                stat = os.stat(filepath)
                files.append({
                    'name': filename,
                    'path': filepath,
                    'size': stat.st_size,
                    'created_at': datetime.datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
                })
        
        files.sort(key=lambda x: x['created_at'], reverse=True)
        return files
    
    def delete_backup(self, filename: str) -> bool:
        filepath = os.path.join(self.backup_path, filename)
        if os.path.exists(filepath) and os.path.isfile(filepath):
            try:
                os.remove(filepath)
                logger.info(f"已删除备份文件: {filename}")
                return True
            except Exception as e:
                logger.error(f"删除备份文件失败: {str(e)}")
                return False
        return False
    
    def get_backup_logs(self, limit: int = 100) -> List[Dict]:
        logs = []
        if not os.path.exists(self.log_path):
            return logs
        
        log_files = sorted(
            [f for f in os.listdir(self.log_path) if f.endswith('.log')],
            reverse=True
        )
        
        for log_file in log_files[:limit]:
            filepath = os.path.join(self.log_path, log_file)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            parts = line.split(' - ', 2)
                            if len(parts) >= 3:
                                logs.append({
                                    'timestamp': parts[0],
                                    'level': parts[1],
                                    'message': parts[2]
                                })
            except Exception as e:
                logger.error(f"读取日志文件失败: {str(e)}")
        
        return logs[:limit]
