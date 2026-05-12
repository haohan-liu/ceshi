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
            product_material TEXT,
            product_dimensions TEXT,
            product_function TEXT,
            selling_points TEXT,
            red_lines TEXT,
            storyboard_content TEXT,
            image_paths TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS project_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            image_data TEXT NOT NULL,
            image_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
    conn.close()


def create_project(
    project_name: str,
    product_name: str = None,
    product_material: str = None,
    product_dimensions: str = None,
    product_function: str = None,
    selling_points: str = None,
    red_lines: str = None,
    storyboard_content: str = None,
    image_paths: str = None
) -> int:
    """创建新项目"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO projects (
            project_name, product_name, product_material, product_dimensions,
            product_function, selling_points, red_lines, storyboard_content, image_paths
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        project_name, product_name, product_material, product_dimensions,
        product_function, selling_points, red_lines, storyboard_content, image_paths
    ))

    project_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return project_id


def update_project(
    project_id: int,
    storyboard_content: str = None,
    image_paths: str = None
):
    """更新项目内容"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE projects
        SET storyboard_content = COALESCE(?, storyboard_content),
            image_paths = COALESCE(?, image_paths),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (storyboard_content, image_paths, project_id))

    conn.commit()
    conn.close()


def save_project_images(project_id: int, images: List[Dict[str, str]]):
    """保存项目图片（Base64 数据）"""
    conn = get_connection()
    cursor = conn.cursor()

    for img in images:
        cursor.execute('''
            INSERT INTO project_images (project_id, image_data, image_name)
            VALUES (?, ?, ?)
        ''', (project_id, img['data'], img.get('name', 'image')))

    conn.commit()
    conn.close()


def get_project_images(project_id: int) -> List[Dict[str, Any]]:
    """获取项目所有图片"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, image_data, image_name, created_at
        FROM project_images
        WHERE project_id = ?
        ORDER BY created_at ASC
    ''', (project_id,))

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            'id': row['id'],
            'image_data': row['image_data'],
            'image_name': row['image_name'],
            'created_at': row['created_at']
        }
        for row in rows
    ]


def get_all_projects() -> List[Dict[str, Any]]:
    """获取所有项目列表（按更新时间倒序）"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, project_name, product_name, created_at, updated_at
        FROM projects
        ORDER BY updated_at DESC
    ''')

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            'id': row['id'],
            'project_name': row['project_name'],
            'product_name': row['product_name'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at']
        }
        for row in rows
    ]


def get_project(project_id: int) -> Optional[Dict[str, Any]]:
    """获取单个项目详情"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT * FROM projects WHERE id = ?
    ''', (project_id,))

    row = cursor.fetchone()
    conn.close()

    if row:
        return dict(row)
    return None


def delete_project(project_id: int) -> bool:
    """删除项目"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('DELETE FROM project_images WHERE project_id = ?', (project_id,))
    cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))

    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return deleted


# 初始化数据库
init_database()
