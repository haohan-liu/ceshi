"""
数据库模块 - 管理项目历史记录的 SQLite 封装
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any


class Database:
    def __init__(self, db_path: str = "storyboard_history.db"):
        """初始化数据库连接"""
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """初始化数据库表结构"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                product_metadata TEXT,
                raw_table_data TEXT,
                generated_script TEXT,
                status TEXT DEFAULT 'completed'
            )
        """)

        conn.commit()
        conn.close()

    def save_project(
        self,
        project_name: str,
        product_metadata: Dict[str, Any],
        raw_table_data: List[Dict[str, Any]],
        generated_script: str
    ) -> int:
        """
        保存项目记录

        Args:
            project_name: 项目名称
            product_metadata: 产品元数据 (字典)
            raw_table_data: 原始表格数据 (列表)
            generated_script: AI 生成的最终脚本

        Returns:
            新记录的 ID
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO project_history (
                project_name, created_at, product_metadata,
                raw_table_data, generated_script
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            project_name,
            datetime.now().isoformat(),
            json.dumps(product_metadata, ensure_ascii=False),
            json.dumps(raw_table_data, ensure_ascii=False),
            generated_script
        ))

        project_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return project_id

    def get_all_projects(self) -> List[Dict[str, Any]]:
        """获取所有项目历史记录"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, project_name, created_at, status
            FROM project_history
            ORDER BY created_at DESC
        """)

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def get_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        """根据 ID 获取单个项目详情"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM project_history WHERE id = ?
        """, (project_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            result = dict(row)
            # 解析 JSON 字段
            if result.get('product_metadata'):
                result['product_metadata'] = json.loads(result['product_metadata'])
            if result.get('raw_table_data'):
                result['raw_table_data'] = json.loads(result['raw_table_data'])
            return result

        return None

    def delete_project(self, project_id: int) -> bool:
        """删除项目记录"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM project_history WHERE id = ?", (project_id,))
        deleted = cursor.rowcount > 0

        conn.commit()
        conn.close()

        return deleted

    def search_projects(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索项目"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, project_name, created_at, status
            FROM project_history
            WHERE project_name LIKE ?
            ORDER BY created_at DESC
        """, (f"%{keyword}%",))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]


# 全局数据库实例
db = Database()


def get_db() -> Database:
    """获取数据库实例"""
    return db
