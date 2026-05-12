"""
数据库层 - SQLite 本地历史记录存储
"""
import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'storyboard_history.db')


def get_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """初始化数据库表"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            product_name TEXT,
            anchor_prompt TEXT,
            storyboard_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()


def create_project(
    project_name: str,
    product_name: str = None,
    anchor_prompt: str = None,
    storyboard_content: str = None
) -> int:
    """创建新项目"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO projects (project_name, product_name, anchor_prompt, storyboard_content)
        VALUES (?, ?, ?, ?)
    ''', (project_name, product_name, anchor_prompt, storyboard_content))

    project_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return project_id


def update_project(
    project_id: int,
    anchor_prompt: str = None,
    storyboard_content: str = None
):
    """更新项目内容"""
    conn = get_connection()
    cursor = conn.cursor()

    if anchor_prompt is not None:
        cursor.execute('''
            UPDATE projects
            SET anchor_prompt = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (anchor_prompt, project_id))

    if storyboard_content is not None:
        cursor.execute('''
            UPDATE projects
            SET storyboard_content = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (storyboard_content, project_id))

    conn.commit()
    conn.close()


def get_all_projects() -> List[Dict[str, Any]]:
    """获取所有项目列表"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, project_name, product_name, created_at, updated_at
        FROM projects
        ORDER BY updated_at DESC
    ''')

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_project(project_id: int) -> Optional[Dict[str, Any]]:
    """获取单个项目详情"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM projects WHERE id = ?', (project_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return dict(row)
    return None


def delete_project(project_id: int) -> bool:
    """删除项目"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return deleted


# 初始化数据库
init_database()
