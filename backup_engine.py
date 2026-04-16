#!/usr/bin/python
import os
import re
import gzip
import logging
import datetime
import mysql.connector
from mysql.connector import Error, errorcode
from typing import List, Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)


class BackupEngine:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.host = config.get('db_host', 'localhost')
        self.port = config.get('db_port', 3306)
        self.user = config.get('db_user', 'root')
        self.password = config.get('db_password', '')
        self.database = config.get('db_name', '')
        self.backup_path = config.get('backup_path', './backups')
        self.charset = config.get('charset', 'utf8mb4')
        
        os.makedirs(self.backup_path, exist_ok=True)

    def test_connection(self) -> Tuple[bool, str]:
        try:
            connection = mysql.connector.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                charset=self.charset
            )
            if connection.is_connected():
                connection.close()
                return True, "连接成功"
            return False, "连接失败"
        except Error as e:
            return False, f"连接失败: {str(e)}"

    def get_databases(self) -> List[str]:
        try:
            connection = mysql.connector.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                charset=self.charset
            )
            cursor = connection.cursor(buffered=True)
            cursor.execute("SHOW DATABASES")
            databases = [db[0] for db in cursor.fetchall() 
                        if db[0] not in ('information_schema', 'mysql', 'performance_schema', 'sys')]
            cursor.close()
            connection.close()
            return databases
        except Error as e:
            logger.error(f"获取数据库列表失败: {str(e)}")
            return []

    def _quote_identifier(self, identifier: str) -> str:
        return f'`{identifier.replace("`", "``")}`'

    def _escape_value(self, value: Any, connection) -> str:
        if value is None:
            return 'NULL'
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, bytes):
            return f"0x{value.hex()}"
        if isinstance(value, datetime.datetime):
            return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"
        if isinstance(value, datetime.date):
            return f"'{value.strftime('%Y-%m-%d')}'"
        if isinstance(value, datetime.timedelta):
            return f"'{str(value)}'"
        return f"'{connection.converter.escape(str(value))}'"

    def _get_create_table(self, cursor, table_name: str) -> str:
        cursor.execute(f"SHOW CREATE TABLE {self._quote_identifier(table_name)}")
        result = cursor.fetchone()
        return result[1] if result else ''

    def _get_table_columns(self, cursor, table_name: str) -> List[str]:
        cursor.execute(f"DESCRIBE {self._quote_identifier(table_name)}")
        return [col[0] for col in cursor.fetchall()]

    def _get_table_count(self, cursor, table_name: str) -> int:
        cursor.execute(f"SELECT COUNT(*) FROM {self._quote_identifier(table_name)}")
        result = cursor.fetchone()
        return result[0] if result else 0

    def _backup_database(self, database: str, progress_callback=None, db_index: int = 0, total_dbs: int = 1) -> str:
        timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        backup_file = os.path.join(self.backup_path, f'{database}_{timestamp}.sql.gz')
        
        logger.info(f"[{db_index + 1}/{total_dbs}] 开始备份数据库: {database}")
        
        connection = mysql.connector.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=database,
            charset=self.charset
        )
        
        cursor = connection.cursor(buffered=True)
        
        try:
            with gzip.open(backup_file, 'wt', encoding='utf-8') as f:
                f.write(f"-- MySQL Database Backup\n")
                f.write(f"-- Host: {self.host}\n")
                f.write(f"-- Database: {database}\n")
                f.write(f"-- Generation Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"-- --------------------------------------------------------\n\n")
                
                f.write("SET FOREIGN_KEY_CHECKS = 0;\n\n")
                
                cursor.execute("SHOW TABLES")
                tables = [table[0] for table in cursor.fetchall()]
                
                total_tables = len(tables)
                logger.info(f"数据库 {database} 包含 {total_tables} 个表")
                
                for idx, table_name in enumerate(tables, 1):
                    logger.info(f"[{db_index + 1}/{total_dbs}] 正在备份 {database}.{table_name} ({idx}/{total_tables})")
                    
                    if progress_callback:
                        overall_progress = int((db_index / total_dbs) * 100 + (idx / total_tables / total_dbs) * 100)
                        progress_callback(
                            overall_progress, 
                            100, 
                            f"正在备份: {database}.{table_name} ({idx}/{total_tables})"
                        )
                    
                    f.write(f"-- Table structure for table {self._quote_identifier(table_name)}\n")
                    f.write("DROP TABLE IF EXISTS " + self._quote_identifier(table_name) + ";\n")
                    
                    create_sql = self._get_create_table(cursor, table_name)
                    f.write(create_sql + ";\n\n")
                    
                    f.write(f"-- Dumping data for table {self._quote_identifier(table_name)}\n")
                    
                    columns = self._get_table_columns(cursor, table_name)
                    column_list = ', '.join([self._quote_identifier(col) for col in columns])
                    
                    row_count = self._get_table_count(cursor, table_name)
                    
                    if row_count > 0:
                        logger.info(f"  表 {table_name} 包含 {row_count} 条数据")
                        
                        select_cursor = connection.cursor(buffered=True)
                        select_cursor.execute(f"SELECT {column_list} FROM {self._quote_identifier(table_name)}")
                        
                        batch_size = 1000
                        insert_batch = []
                        
                        for row in select_cursor:
                            values = [self._escape_value(val, connection) for val in row]
                            insert_batch.append(f"({', '.join(values)})")
                            
                            if len(insert_batch) >= batch_size:
                                f.write(f"INSERT INTO {self._quote_identifier(table_name)} ({column_list}) VALUES\n")
                                f.write(',\n'.join(insert_batch) + ";\n")
                                insert_batch = []
                        
                        if insert_batch:
                            f.write(f"INSERT INTO {self._quote_identifier(table_name)} ({column_list}) VALUES\n")
                            f.write(',\n'.join(insert_batch) + ";\n")
                        
                        select_cursor.close()
                    
                    f.write("\n")
                
                f.write("SET FOREIGN_KEY_CHECKS = 1;\n")
            
            cursor.close()
            connection.close()
            
            logger.info(f"[{db_index + 1}/{total_dbs}] 数据库 {database} 备份完成: {backup_file}")
            return backup_file
            
        except Exception as e:
            cursor.close()
            connection.close()
            if os.path.exists(backup_file):
                os.remove(backup_file)
            logger.error(f"[{db_index + 1}/{total_dbs}] 数据库 {database} 备份失败: {str(e)}")
            raise e

    def backup(self, databases: Optional[List[str]] = None, progress_callback=None) -> List[str]:
        backup_files = []
        
        if databases and len(databases) > 0:
            total_dbs = len(databases)
            logger.info(f"开始备份 {total_dbs} 个数据库: {', '.join(databases)}")
            
            for idx, db in enumerate(databases):
                if progress_callback:
                    progress_callback(
                        int((idx / total_dbs) * 100),
                        100,
                        f"准备备份数据库: {db} ({idx + 1}/{total_dbs})"
                    )
                
                backup_file = self._backup_database(db, progress_callback, idx, total_dbs)
                backup_files.append(backup_file)
            
            logger.info(f"所有数据库备份完成，共生成 {len(backup_files)} 个备份文件")
        else:
            logger.info("未指定数据库，获取所有可用数据库...")
            all_databases = self.get_databases()
            
            if not all_databases:
                logger.warning("未找到任何可用数据库")
                return []
            
            total_dbs = len(all_databases)
            logger.info(f"找到 {total_dbs} 个数据库: {', '.join(all_databases)}")
            
            for idx, db in enumerate(all_databases):
                if progress_callback:
                    progress_callback(
                        int((idx / total_dbs) * 100),
                        100,
                        f"准备备份数据库: {db} ({idx + 1}/{total_dbs})"
                    )
                
                backup_file = self._backup_database(db, progress_callback, idx, total_dbs)
                backup_files.append(backup_file)
            
            logger.info(f"所有数据库备份完成，共生成 {len(backup_files)} 个备份文件")
        
        return backup_files

    def cleanup_old_backups(self, retention_days: int) -> int:
        if retention_days <= 0:
            logger.info("保留天数设置为0，跳过清理")
            return 0
        
        cutoff_time = datetime.datetime.now() - datetime.timedelta(days=retention_days)
        deleted_count = 0
        
        if not os.path.exists(self.backup_path):
            logger.info(f"备份路径不存在: {self.backup_path}")
            return 0
        
        logger.info(f"开始清理 {retention_days} 天前的备份文件...")
        logger.info(f"截止时间: {cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        for filename in os.listdir(self.backup_path):
            filepath = os.path.join(self.backup_path, filename)
            if os.path.isfile(filepath):
                file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(filepath))
                if file_mtime < cutoff_time:
                    os.remove(filepath)
                    deleted_count += 1
                    logger.info(f"已删除过期备份: {filename} (修改时间: {file_mtime.strftime('%Y-%m-%d %H:%M:%S')})")
        
        logger.info(f"清理完成，共删除 {deleted_count} 个过期备份文件")
        return deleted_count

    def get_backup_files(self) -> List[Dict[str, Any]]:
        files_info = []
        
        if not os.path.exists(self.backup_path):
            return files_info
        
        for filename in os.listdir(self.backup_path):
            filepath = os.path.join(self.backup_path, filename)
            if os.path.isfile(filepath) and filename.endswith('.sql.gz'):
                stat_info = os.stat(filepath)
                files_info.append({
                    'filename': filename,
                    'filepath': filepath,
                    'size': stat_info.st_size,
                    'created_time': datetime.datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'size_mb': round(stat_info.st_size / (1024 * 1024), 2)
                })
        
        files_info.sort(key=lambda x: x['created_time'], reverse=True)
        return files_info
