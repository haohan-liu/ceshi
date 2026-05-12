# AI 商业视频制片工作台

一个基于向导式流程的 AI 商业视频分镜生成工具，支持流式输出和专业分镜表格导出。

## 功能特性

- **三步向导流程**: 需求摄入 → 产品档案 → 分镜生成
- **文件上传解析**: 支持 CSV/Excel 格式的需求表
- **流式 SSE 输出**: 实时查看 AI 生成过程
- **专业分镜表格**: 包含首尾帧提示词、景别、运镜等信息
- **一键复制/导出**: 快速复制提示词或导出完整脚本
- **历史项目管理**: 自动保存项目到本地 SQLite 数据库

## 技术栈

- **前端**: HTML5 + Vanilla JS + TailwindCSS (CDN)
- **后端**: Python Flask
- **数据库**: SQLite (本地存储)
- **AI 接口**: OpenAI 兼容 API (支持聚合平台)

## 安装与运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API

编辑 `.env` 文件，填入你的 API Key 和地址：

```env
NEW_API_KEY=your_api_key_here
NEW_API_BASE_URL=https://api.openai.com/v1
MODEL_NAME=gpt-4o
```

### 3. 启动服务

```bash
python app.py
```

### 4. 访问页面

打开浏览器访问: http://localhost:5000

## 项目结构

```
├── app.py              # Flask 后端主文件
├── database.py         # SQLite 数据库模块
├── requirements.txt    # Python 依赖
├── .env               # 环境配置 (API Key)
├── storyboard_history.db  # SQLite 数据库 (自动生成)
├── templates/
│   └── index.html     # 前端页面
└── README.md
```

## 使用流程

### Step 1: 需求摄入
- 上传包含镜头信息的 CSV/Excel 文件
- 或跳过直接进入下一步

### Step 2: 产品档案
- 填写产品名称、材质、尺寸等核心信息
- 特别注意**物理红线**（禁止改变的特征）

### Step 3: 分镜生成
- 点击"推演商业分镜"启动 AI 生成
- 查看流式输出和最终分镜表格
- 一键复制提示词或导出脚本

## CSV/Excel 格式

上传的文件需包含以下字段（支持中英文列名）：

| 片段时长 | 镜头语言 | 画面描述 | 核心动作 | 核心卖点 |
|---------|---------|---------|---------|---------|
| duration | camera_language | visual_description | core_action | core_selling_point |

## 提示词工程

系统使用专业的 Prompt 工程：
- 角色: 资深跨境电商视觉总监 + 好莱坞级灯光摄影指导
- 约束: 严格遵守物理尺寸和品牌红线
- 格式: 纯英文逗号分隔的 Tag 格式
- 输出: 包含首尾帧提示词的专业分镜 JSON

## API 接口

| 端点 | 方法 | 描述 |
|-----|------|-----|
| `/` | GET | 主页面 |
| `/api/upload` | POST | 上传解析需求表 |
| `/api/generate` | POST | 流式生成分镜 (SSE) |
| `/api/save` | POST | 保存项目 |
| `/api/projects` | GET | 获取项目列表 |
| `/api/project/<id>` | GET | 获取项目详情 |
| `/api/project/<id>` | DELETE | 删除项目 |
