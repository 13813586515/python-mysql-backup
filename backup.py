import os
import gzip
import datetime
import mysql.connector
from mysql.connector import Error
from config import Config
import logging

# 配置日志 - 使用UTF-8编码写入文件
log_file = os.path.join(Config.BACKUP_PATH, 'backup.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MySQLBackup:
    def __init__(self, host=None, port=None, user=None, password=None, database=None):
        self.host = host or Config.DB_HOST
        self.port = port or Config.DB_PORT
        self.user = user or Config.DB_USER
        self.password = password or Config.DB_PASSWORD
        self.database = database or Config.DB_NAME
        self.connection = None
        self.backup_dir = Config.BACKUP_PATH
        self.max_backups = Config.MAX_BACKUPS

    def connect(self):
        """建立数据库连接"""
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset='utf8mb4'
            )
            return True
        except Error as e:
            logger.error(f"数据库连接失败: {e}")
            return False

    def disconnect(self):
        """关闭数据库连接"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            logger.info("数据库连接已关闭")

    def get_all_databases(self):
        """获取所有数据库列表"""
        if not self.connection:
            return []
        
        try:
            cursor = self.connection.cursor()
            cursor.execute("SHOW DATABASES")
            databases = [db[0] for db in cursor.fetchall() 
                        if db[0] not in ['information_schema', 'performance_schema', 'mysql', 'sys']]
            cursor.close()
            return databases
        except Error as e:
            logger.error(f"获取数据库列表失败: {e}")
            return []

    def get_all_tables(self, database):
        """获取指定数据库的所有表"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(f"USE `{database}`")
            cursor.execute("SHOW TABLES")
            tables = [table[0] for table in cursor.fetchall()]
            cursor.close()
            return tables
        except Error as e:
            logger.error(f"获取表列表失败 ({database}): {e}")
            return []

    def get_table_schema(self, database, table):
        """获取表的CREATE TABLE语句"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(f"SHOW CREATE TABLE `{database}`.`{table}`")
            schema = cursor.fetchone()[1]
            cursor.close()
            return schema
        except Error as e:
            logger.error(f"获取表结构失败 ({database}.{table}): {e}")
            return None

    def get_table_data(self, database, table):
        """获取表的数据"""
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute(f"SELECT * FROM `{database}`.`{table}`")
            data = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            cursor.close()
            return columns, data
        except Error as e:
            logger.error(f"获取表数据失败 ({database}.{table}): {e}")
            return None, None

    def generate_insert_statements(self, database, table, columns, data):
        """生成INSERT语句"""
        if not data:
            return []
        
        inserts = []
        for row in data:
            values = []
            for col in columns:
                val = row[col]
                if val is None:
                    values.append('NULL')
                elif isinstance(val, (int, float)):
                    values.append(str(val))
                else:
                    # 转义字符串中的特殊字符
                    escaped_val = str(val).replace("'", "''").replace('\\', '\\\\')
                    values.append(f"'{escaped_val}'")
            
            columns_str = ', '.join([f"`{col}`" for col in columns])
            values_str = ', '.join(values)
            insert = f"INSERT INTO `{table}` ({columns_str}) VALUES ({values_str});"
            inserts.append(insert)
        
        return inserts

    def backup_database(self, database):
        """备份单个数据库"""
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(self.backup_dir, f"{database}_{timestamp}.sql.gz")
        
        try:
            tables = self.get_all_tables(database)
            if not tables:
                logger.warning(f"数据库 {database} 没有表可备份")
                return None

            # 使用gzip压缩写入
            with gzip.open(backup_file, 'wt', encoding='utf-8') as f:
                # 写入备份头信息
                f.write(f"-- MySQL Backup for database: {database}\n")
                f.write(f"-- Backup Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"-- Host: {self.host}\n")
                f.write("-- ============================================\n\n")
                f.write(f"CREATE DATABASE IF NOT EXISTS `{database}`;\n")
                f.write(f"USE `{database}`;\n\n")

                # 备份每个表
                for table in tables:
                    logger.info(f"正在备份表: {database}.{table}")
                    
                    # 表结构
                    schema = self.get_table_schema(database, table)
                    if schema:
                        f.write(f"-- Table structure for `{table}`\n")
                        f.write(f"DROP TABLE IF EXISTS `{table}`;\n")
                        f.write(f"{schema};\n\n")
                    
                    # 表数据
                    columns, data = self.get_table_data(database, table)
                    if columns and data:
                        f.write(f"-- Data for `{table}`\n")
                        inserts = self.generate_insert_statements(database, table, columns, data)
                        for insert in inserts:
                            f.write(f"{insert}\n")
                        f.write("\n")

            logger.info(f"数据库 {database} 备份完成: {backup_file}")
            return backup_file

        except Exception as e:
            logger.error(f"备份数据库 {database} 失败: {e}")
            if os.path.exists(backup_file):
                os.remove(backup_file)
            return None

    def backup_all_databases(self):
        """备份所有数据库"""
        if not self.connect():
            return []

        databases = self.get_all_databases()
        if not databases:
            logger.warning("没有找到可备份的数据库")
            self.disconnect()
            return []

        backup_files = []
        for db in databases:
            backup_file = self.backup_database(db)
            if backup_file:
                backup_files.append(backup_file)

        self.disconnect()
        self.cleanup_old_backups()
        return backup_files

    def cleanup_old_backups(self):
        """清理旧的备份文件，保留最新的MAX_BACKUPS个"""
        try:
            # 获取所有备份文件
            backup_files = []
            for filename in os.listdir(self.backup_dir):
                if filename.endswith('.sql.gz'):
                    filepath = os.path.join(self.backup_dir, filename)
                    backup_files.append((filepath, os.path.getmtime(filepath)))

            # 按修改时间排序，保留最新的
            backup_files.sort(key=lambda x: x[1], reverse=True)
            for filepath, _ in backup_files[self.max_backups:]:
                os.remove(filepath)
                logger.info(f"删除旧备份: {filepath}")
        except Exception as e:
            logger.error(f"清理旧备份失败: {e}")

    def test_connection(self):
        """测试数据库连接"""
        if self.connect():
            self.disconnect()
            return True, "连接成功"
        return False, "无法连接到数据库，请检查配置"

def get_backup_list():
    """获取备份文件列表"""
    backup_files = []
    for filename in os.listdir(Config.BACKUP_PATH):
        if filename.endswith('.sql.gz'):
            filepath = os.path.join(Config.BACKUP_PATH, filename)
            stat = os.stat(filepath)
            backup_files.append({
                'filename': filename,
                'size': stat.st_size,
                'ctime': stat.st_ctime,
                'path': filepath
            })
    
    # 按时间排序，最新的在前
    backup_files.sort(key=lambda x: x['ctime'], reverse=True)
    return backup_files

def get_backup_logs(lines=100):
    """获取备份日志"""
    log_file = os.path.join(Config.BACKUP_PATH, 'backup.log')
    if not os.path.exists(log_file):
        return []
    
    # 尝试多种编码方式读取文件，解决Windows编码问题
    encodings = ['utf-8', 'gbk', 'gb2312', 'cp1252']
    logs = []
    
    for encoding in encodings:
        try:
            with open(log_file, 'r', encoding=encoding) as f:
                logs = f.readlines()
            break  # 读取成功，跳出循环
        except UnicodeDecodeError:
            continue  # 尝试下一种编码
        except Exception:
            break  # 其他错误，跳出循环
    
    # 返回最后N行
    return [line.strip() for line in logs[-lines:]]
