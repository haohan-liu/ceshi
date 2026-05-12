"""
AI 商业视频制片工作台 - Flask 后端
Gemini 风格重构版
"""
import os
import re
import json
import base64
import shutil
import traceback
from datetime import datetime
from io import BytesIO

from flask import Flask, render_template, request, jsonify, Response
from openai import OpenAI
from dotenv import load_dotenv

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

from database import init_database, create_project, update_project, get_all_projects, get_project, delete_project

# 加载环境变量（强制重新加载）
load_dotenv(override=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

ENV_FILE = os.path.join(os.path.dirname(__file__), '.env')


# ==================== 环境变量管理 ====================
def get_settings():
    """读取当前设置"""
    return {
        'api_key': os.getenv("NEW_API_KEY", ""),
        'api_base': os.getenv("NEW_API_BASE_URL", "https://api.openai.com/v1"),
        'model_name': os.getenv("MODEL_NAME", "gpt-4o")
    }


def save_settings(api_key: str, api_base: str, model_name: str) -> bool:
    """保存设置到 .env 文件"""
    try:
        lines = []
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()

        # 更新或添加配置
        new_lines = []
        keys = {
            "NEW_API_KEY": api_key,
            "NEW_API_BASE_URL": api_base or "https://api.openai.com/v1",
            "MODEL_NAME": model_name or "gpt-4o"
        }
        found = {k: False for k in keys}

        for line in lines:
            stripped = line.strip()
            # 保留注释行和空行
            if not stripped or stripped.startswith('#'):
                new_lines.append(line)
                continue
            if '=' in stripped:
                key = stripped.split('=', 1)[0].strip()
                if key in keys:
                    new_lines.append(f"{key}={keys[key]}\n")
                    found[key] = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        # 添加缺失的键
        for key, val in keys.items():
            if not found[key]:
                new_lines.append(f"{key}={val}\n")

        with open(ENV_FILE, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        # 强制重新加载环境变量
        for key in ["NEW_API_KEY", "NEW_API_BASE_URL", "MODEL_NAME"]:
            os.environ.pop(key, None)
        load_dotenv(override=True)
        return True
    except Exception as e:
        print(f"保存设置失败: {e}")
        return False


# ==================== OpenAI 客户端 ====================
def get_client():
    """获取当前配置的 OpenAI 客户端"""
    # 直接读取 .env 文件，确保获取最新配置
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(env_path, override=True)
    
    api_key = os.getenv("NEW_API_KEY", "")
    api_base = os.getenv("NEW_API_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("MODEL_NAME", "")
    
    print(f"[DEBUG] 读取 .env 文件: {env_path}")
    print(f"[DEBUG] API Key: {api_key[:15]}..." if api_key else "[DEBUG] API Key: 未设置")
    print(f"[DEBUG] API Base: {api_base}")
    print(f"[DEBUG] Model: {model}")
    
    if not api_key:
        raise Exception("API Key 未配置！请编辑 .env 文件设置 NEW_API_KEY")
    if not model:
        raise Exception("模型名称未配置！请编辑 .env 文件设置 MODEL_NAME")
        
    return OpenAI(api_key=api_key, base_url=api_base)


# ==================== 图片压缩 ====================
def compress_image(file_data, max_size=(1024, 1024), quality=85):
    if not PIL_AVAILABLE:
        return file_data
    try:
        img = Image.open(BytesIO(file_data))
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        output = BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        return output.getvalue()
    except Exception as e:
        print(f"图片压缩失败: {e}")
        return file_data


# ==================== Prompt 定义 ====================
PRODUCT_ANALYSIS_SYSTEM = """You are a Midjourney prompt engineer specializing in product photography.

TASK: Analyze product images and generate a precise English product appearance description.

RULES:
1. Output ONLY comma-separated English tags
2. Focus on: material, texture, color, shape, surface finish, structural details, LOGO design
3. NO lighting, background, or environmental elements
4. Keep under 200 characters
5. Always include "LOGO" if the product has a visible brand mark

Example: "metallic aluminum alloy, brushed surface, matte silver finish, cylindrical body, precision-machined edges, minimalist design, embossed LOGO"
"""

PRODUCT_ANALYSIS_USER = """Analyze this product image and describe its appearance for Midjourney image generation.

Focus on: exact colors, material texture (matte/glossy/brushed/metallic), shape, surface finish, key structural elements, size proportions, LOGO visibility.

Output ONLY English tags, comma-separated."""


def build_script_system_prompt(aspect_ratio: str) -> str:
    """根据画幅比例构建动态 system prompt"""
    ar_display = "16:9 横屏 (Cinematic Widescreen)" if aspect_ratio == "16:9" else "9:16 竖屏 (Vertical Mobile)"

    if aspect_ratio == '9:16':
        composition_rules = """
【画幅与构图控制法则 - 9:16 竖屏】
- 提示词必须包含：vertical video format, portrait orientation, tight framing, optimized for mobile, vertical composition
- 产品主体居中或放置在垂直三分线上
- 简洁纵向背景，聚焦主体
- 画幅描述：16:9 横屏 → 9:16 竖屏（请在中文翻译中明确标注画幅比例）"""
        ar_param = "--ar 9:16"
    else:
        composition_rules = """
【画幅与构图控制法则 - 16:9 横屏】
- 提示词必须包含：cinematic widescreen, landscape orientation, expansive environment, film grain, cinematic composition
- 横向广阔空间，电影级构图
- 可包含更多环境背景元素
- 画幅描述：9:16 竖屏 → 16:9 横屏（请在中文翻译中明确标注画幅比例）"""
        ar_param = "--ar 16:9"

    return f"""你是一位好莱坞 cinematographer（摄影指导）。

【铁律 1：禁止幻觉】
- 必须严格根据用户提供的 CSV/Excel 表格数据生成镜头
- 表格有多少行，就生成至少多少个镜头
- 禁止自行发明任何不在表格中的镜头

【铁律 2：动作拆分】
- 如果某行包含多个动作（如"先俯拍...再侧拍..."），必须拆分为多个独立镜头
- 每个镜头必须有明确的物理动作
- 不得遗漏任何动作描述

【铁律 3：首尾帧绑定】
- 首帧(Start)：描述画面初始状态 + 锚定词
- 尾帧(End)：描述动作完成后的状态 + 锚定词
- 必须包含明确的物理动作和状态变化

【铁律 4：锚定词一致性】
- 每个首帧和尾帧必须以锚定词开头
- 锚定词必须原封不动，不能修改

【铁律 5：画幅比例 {ar_display}】
{composition_rules}

【铁律 6：参数强制写入】
- 每一个首帧和尾帧提示词的最后，必须无条件加上：{ar_param}
- 直接拼接到英文提示词末尾

【铁律 7：产品不变形红线】
- 无论画幅如何变化，产品绝对不能发生挤压、拉伸或变形
- 只调整构图和背景

【铁律 8：LOGO 规范】
- 所有关于"标识"、"标志"统一翻译为 "LOGO"

【输出格式】
输出纯 Markdown 表格：

| 镜头编号 | 景别/焦段 | 画面与动作描述 | 首帧提示词(Start) | 尾帧提示词(End) |

【提示词格式（悬浮翻译）】
<span title="中文翻译：{ar_display}时尚金属机身，刷纹铝面，柔和灯光">英文提示词 {ar_param}</span>

注意：[Image Reference] 不需要翻译。"""


# ==================== 路由 ====================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/projects', methods=['GET'])
def list_projects():
    try:
        projects = get_all_projects()
        return jsonify({'success': True, 'projects': projects})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/projects/<int:project_id>', methods=['GET'])
def get_project_detail(project_id):
    try:
        project = get_project(project_id)
        if not project:
            return jsonify({'success': False, 'error': '项目不存在'}), 404
        return jsonify({'success': True, 'project': project})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/projects/<int:project_id>', methods=['DELETE'])
def delete_project_route(project_id):
    try:
        success = delete_project(project_id)
        if success:
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': '项目不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== 阶段一：产品特征提取（流式） ====================
@app.route('/api/analyze_product', methods=['POST'])
def analyze_product():
    try:
        product_name = request.form.get('product_name', 'Unknown Product')

        images = []
        if 'images' in request.files:
            files = request.files.getlist('images')
            for f in files:
                if f and f.filename:
                    original_data = f.read()
                    compressed = compress_image(original_data)
                    img_data = base64.b64encode(compressed).decode('utf-8')
                    images.append({
                        'data': f"data:image/jpeg;base64,{img_data}",
                        'name': f.filename
                    })

        if not images:
            return jsonify({'success': False, 'error': '请上传至少一张产品图片'}), 400

        message_content = []
        for img in images:
            message_content.append({
                "type": "image_url",
                "image_url": {"url": img['data'], "detail": "high"}
            })
        message_content.append({"type": "text", "text": PRODUCT_ANALYSIS_USER})

        def generate():
            try:
                yield f"data: {json.dumps({'type': 'start', 'message': '正在分析产品...'})}\n\n"

                client = get_client()
                stream = client.chat.completions.create(
                    model=os.getenv("MODEL_NAME", "gpt-4o"),
                    messages=[
                        {"role": "system", "content": PRODUCT_ANALYSIS_SYSTEM},
                        {"role": "user", "content": message_content}
                    ],
                    max_tokens=500,
                    temperature=0.7,
                    stream=True
                )

                accumulated = ''
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        accumulated += content
                        yield f"data: {json.dumps({'type': 'chunk', 'content': content, 'accumulated': accumulated})}\n\n"

                yield f"data: {json.dumps({'type': 'done', 'anchor_prompt': accumulated})}\n\n"

            except Exception as e:
                error_msg = str(e)
                print(f"="*50)
                print(f"分析错误: {error_msg}")
                print(f"traceback: {traceback.format_exc()}")
                print(f"="*50)
                yield f"data: {json.dumps({'type': 'error', 'message': f'服务器错误: {error_msg[:200]}'})}\n\n"

        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no'
            }
        )

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/analyze_product/save', methods=['POST'])
def analyze_product_save():
    """保存锚定词并创建项目"""
    try:
        data = request.get_json()
        anchor_prompt = data.get('anchor_prompt', '')
        product_name = data.get('product_name', '未命名')

        project_id = create_project(
            project_name=f"{product_name} - {datetime.now().strftime('%Y%m%d %H:%M')}",
            product_name=product_name,
            anchor_prompt=anchor_prompt
        )

        return jsonify({'success': True, 'project_id': project_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== 阶段二：分镜生成（流式） ====================
@app.route('/api/generate_script', methods=['POST'])
def generate_script():
    try:
        anchor_prompt = request.form.get('anchor_prompt', '')
        project_id = request.form.get('project_id')
        aspect_ratio = request.form.get('aspect_ratio', '16:9')
        requirements_content = ''

        if 'requirements' in request.files:
            file = request.files['requirements']
            if file and file.filename:
                ext = os.path.splitext(file.filename)[1].lower()
                content = file.read()

                if ext in ['.xlsx', '.xls']:
                    if PANDAS_AVAILABLE:
                        try:
                            df = pd.read_excel(BytesIO(content))
                            requirements_content = df.to_csv(index=False, encoding='utf-8')
                        except Exception as excel_err:
                            print(f"Excel 解析失败: {excel_err}")
                            requirements_content = ''
                elif ext == '.csv':
                    if PANDAS_AVAILABLE:
                        try:
                            df = pd.read_csv(BytesIO(content))
                            requirements_content = df.to_csv(index=False, encoding='utf-8')
                        except Exception as csv_err:
                            print(f"CSV 解析失败: {csv_err}")
                            requirements_content = content.decode('utf-8', errors='replace')
                    else:
                        requirements_content = content.decode('utf-8', errors='replace')

        def generate():
            try:
                system_prompt = build_script_system_prompt(aspect_ratio)
                user_prompt = build_script_prompt(anchor_prompt, requirements_content, aspect_ratio)

                yield f"data: {json.dumps({'type': 'start', 'message': f'开始生成 [{aspect_ratio}]...'})}\n\n"

                client = get_client()
                stream = client.chat.completions.create(
                    model=os.getenv("MODEL_NAME", "gpt-4o"),
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    stream=True,
                    temperature=0.7,
                    max_tokens=8192
                )

                accumulated = ''
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        accumulated += content
                        yield f"data: {json.dumps({'type': 'chunk', 'content': content, 'accumulated': accumulated})}\n\n"

                yield f"data: {json.dumps({'type': 'done', 'message': '生成完成'})}\n\n"

                if project_id:
                    try:
                        update_project(int(project_id), storyboard_content=accumulated, aspect_ratio=aspect_ratio)
                        yield f"data: {json.dumps({'type': 'saved', 'message': '已保存'})}\n\n"
                    except Exception as save_err:
                        yield f"data: {json.dumps({'type': 'save_warning', 'message': str(save_err)})}\n\n"

            except Exception as e:
                error_msg = str(e)
                print(f"="*50)
                print(f"生成错误: {error_msg}")
                print(f"traceback: {traceback.format_exc()}")
                print(f"="*50)
                yield f"data: {json.dumps({'type': 'error', 'message': f'服务器错误: {error_msg[:200]}'})}\n\n"

        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no'
            }
        )

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def build_script_prompt(anchor_prompt: str, requirements_content: str, aspect_ratio: str) -> str:
    ar_display = "16:9 横屏" if aspect_ratio == "16:9" else "9:16 竖屏"
    ar_param = f"--ar {aspect_ratio}"

    prompt = f"""## 【阶段一】产品锚定词 (ANCHOR)

```
{anchor_prompt}
```

"""

    if requirements_content:
        prompt += f"""## 【阶段二】镜头需求表

请逐行分析以下表格，生成对应数量的镜头：
```
{requirements_content}
```

"""

    prompt += f"""## 【阶段三】画幅比例

当前选择：{ar_display}

"""

    prompt += f"""## 【执行要求】

1. 逐行分析表格，生成对应数量的镜头
2. 动作拆分：多个动作 → 多个独立镜头
3. 首帧提示词：初始状态 + 锚定词 + 构图词 + {ar_param}
4. 尾帧提示词：完成状态 + 锚定词 + 构图词 + {ar_param}
5. 中文翻译必须包含画幅比例描述（{ar_display}）
6. 所有"标识"、"标志"统一写 "LOGO"

## 【输出格式】

| 镜头编号 | 景别/焦段 | 画面与动作描述 | 首帧提示词(Start) | 尾帧提示词(End) |

## 【提示词格式】

<span title="中文翻译：{ar_display}时尚金属机身，刷纹铝面，柔和灯光">metallic aluminum, brushed surface, soft lighting, cinematic composition {ar_param}</span>

请立即开始生成："""

    return prompt


# ==================== 启动 ====================
if __name__ == '__main__':
    init_database()
    print("=" * 50)
    print("  AI 商业视频制片工作台")
    print(f"  模型: {os.getenv('MODEL_NAME', 'gpt-4o')}")
    print(f"  API:  {os.getenv('NEW_API_BASE_URL', '')}")
    print("  访问: http://localhost:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
