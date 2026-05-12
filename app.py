"""
AI 商业视频制片工作台 - Flask 后端
支持多模态图片输入 + 流式 Markdown 输出
"""
import os
import json
import base64
import uuid
import traceback
from datetime import datetime
from io import BytesIO

from flask import Flask, render_template, request, jsonify, Response
from openai import OpenAI
from openai import APIError, RateLimitError, APITimeoutError
from dotenv import load_dotenv

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from database import (
    init_database, create_project, update_project,
    get_all_projects, get_project, delete_project,
    save_project_images, get_project_images
)

# 加载环境变量
load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max

# API 配置
API_KEY = os.getenv("NEW_API_KEY", os.getenv("OPENAI_API_KEY", ""))
API_BASE = os.getenv("NEW_API_BASE_URL", os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"))
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o")

# 初始化 OpenAI 客户端
client = OpenAI(api_key=API_KEY, base_url=API_BASE)

# 图片压缩函数
def compress_image(file_data, max_size=(1024, 1024), quality=85):
    """压缩图片，减少 Base64 大小"""
    if not PIL_AVAILABLE:
        return file_data

    try:
        img = Image.open(BytesIO(file_data))
        # 转换为 RGB（如果是 RGBA）
        if img.mode == 'RGBA':
            img = img.convert('RGB')

        # 缩放图片
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

        # 保存为 JPEG
        output = BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        return output.getvalue()
    except Exception as e:
        print(f"图片压缩失败: {e}")
        return file_data

# 测试连接
def test_api_connection():
    """测试 API 连接"""
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5
        )
        return True, "连接成功"
    except Exception as e:
        return False, str(e)

# ==================== 系统提示词 ====================
SYSTEM_PROMPT = """你是好莱坞级灯光摄影指导与 Midjourney/Sora 资深提示词工程师。

## 你的任务
根据用户提供的需求表和产品信息，为商业视频生成专业的分镜脚本和 Midjourney 提示词。

## 核心原则
1. **你已看到用户上传的产品参考图** - 在撰写提示词时，必须精准描述图中的材质、颜色和结构
2. **分镜脚本必须专业** - 包含镜头编号、时长、运镜、场景描述、画面内容、AI提示词
3. **提示词格式要求** - 首尾帧提示词必须以 `[Image Reference]` 开头
4. **双语呈现** - 英文提示词下方必须附带低调的中文翻译

## 输出格式
直接输出 Markdown 格式的分镜表格，使用以下列：
| 镜头 | 时长 | 运镜 | 场景描述 | 画面内容 | AI提示词(英文+中文) |

## AI提示词列的 HTML 格式要求
```html
[Image Reference] cinematic lighting, 8k resolution, product photography...<br>
<span style="font-size: 12px; color: #94a3b8;">(中文翻译：电影院级打光，8K分辨率，产品摄影...)</span>
```

## 关键提示
- 镜头时长建议 3-8 秒
- 运镜方式要多样化（推、拉、摇、移、跟等）
- 每个镜头必须有独特的视觉叙事
- 提示词要具体、生动、可执行
- 中文翻译要简洁、准确、与英文对应
"""

# ==================== 路由 ====================
@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')


@app.route('/api/projects', methods=['GET'])
def list_projects():
    """获取所有项目列表"""
    try:
        projects = get_all_projects()
        return jsonify({'success': True, 'projects': projects})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/projects/<int:project_id>', methods=['GET'])
def get_project_detail(project_id):
    """获取项目详情"""
    try:
        project = get_project(project_id)
        if not project:
            return jsonify({'success': False, 'error': '项目不存在'}), 404

        images = get_project_images(project_id)
        project['images'] = images

        return jsonify({'success': True, 'project': project})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/projects/<int:project_id>', methods=['DELETE'])
def delete_project_route(project_id):
    """删除项目"""
    try:
        success = delete_project(project_id)
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': '项目不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/generate', methods=['POST'])
def generate_storyboard():
    """
    接收产品数据和图片，调用多模态 AI 生成流式分镜脚本
    """
    # 先获取所有数据
    product_metadata = request.form.get('productMetadata', '{}')
    product_metadata = json.loads(product_metadata)

    # 处理上传的图片
    images = []
    total_size = 0
    if 'images' in request.files:
        files = request.files.getlist('images')
        for f in files:
            if f and f.filename:
                # 读取原始数据
                original_data = f.read()
                f.seek(0)  # 重置文件指针

                # 压缩图片
                compressed_data = compress_image(original_data)
                img_data = base64.b64encode(compressed_data).decode('utf-8')
                total_size += len(img_data)

                # 检查总大小，超过 20MB 就跳过剩余图片
                if total_size > 20 * 1024 * 1024:
                    print(f"警告: 图片总大小超过 20MB，跳过剩余图片")
                    break

                mime_type = 'image/jpeg'  # 压缩后统一转为 JPEG
                images.append({
                    'data': f"data:{mime_type};base64,{img_data}",
                    'name': f.filename
                })

    def generate():
        try:
            # 构建消息内容数组（多模态）
            message_content = []

            # 添加图片（如果有）
            for img in images:
                message_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": img['data'],
                        "detail": "high"
                    }
                })

            # 添加用户需求文本
            user_prompt = build_user_prompt(product_metadata)
            message_content.append({
                "type": "text",
                "text": user_prompt
            })

            # 发送开始信号
            yield f"data: {json.dumps({'type': 'start', 'message': '🎬 开始生成商业分镜脚本...'})}\n\n"

            # 调用 AI 流式接口
            try:
                stream = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": message_content}
                    ],
                    stream=True,
                    temperature=0.7,
                    max_tokens=8192
                )
            except Exception as api_error:
                error_msg = str(api_error)
                print(f"API 调用错误: {error_msg}")
                yield f"data: {json.dumps({'type': 'error', 'message': f'API 调用失败: {error_msg}'})}\n\n"
                return

            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    # 发送增量内容
                    yield f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"

            # 发送完成信号
            yield f"data: {json.dumps({'type': 'done', 'message': '生成完成！'})}\n\n"

            # 保存到数据库
            try:
                project_name = product_metadata.get('project_name', f'项目_{datetime.now().strftime("%Y%m%d_%H%M")}')
                product_name = product_metadata.get('product_name', '')

                project_id = create_project(
                    project_name=project_name,
                    product_name=product_name,
                    product_material=product_metadata.get('material_color', ''),
                    product_dimensions=product_metadata.get('dimensions', ''),
                    product_function=product_metadata.get('function', ''),
                    selling_points=product_metadata.get('selling_points', ''),
                    red_lines=product_metadata.get('red_lines', '')
                )

                # 保存图片
                if images:
                    save_project_images(project_id, images)

                yield f"data: {json.dumps({'type': 'saved', 'project_id': project_id})}\n\n"

            except Exception as db_err:
                yield f"data: {json.dumps({'type': 'save_warning', 'message': f'保存失败: {str(db_err)}'})}\n\n"

        except Exception as e:
            error_detail = traceback.format_exc()
            print(f"生成错误: {error_detail}")
            yield f"data: {json.dumps({'type': 'error', 'message': f'生成失败: {str(e)}'})}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


def build_user_prompt(product_metadata: dict) -> str:
    """构建发送给 AI 的用户提示"""
    prompt_parts = []

    prompt_parts.append("## 产品信息")

    if product_metadata.get('product_name'):
        prompt_parts.append(f"**产品名称**: {product_metadata.get('product_name')}")

    if product_metadata.get('material_color'):
        prompt_parts.append(f"**材质与颜色**: {product_metadata.get('material_color')}")

    if product_metadata.get('dimensions'):
        prompt_parts.append(f"**精确尺寸** (禁止变形): {product_metadata.get('dimensions')}")

    if product_metadata.get('function'):
        prompt_parts.append(f"**产品功能**: {product_metadata.get('function')}")

    if product_metadata.get('selling_points'):
        prompt_parts.append(f"**卖点**: {product_metadata.get('selling_points')}")

    if product_metadata.get('red_lines'):
        prompt_parts.append(f"**视觉红线** (禁止修改): {product_metadata.get('red_lines')}")

    if product_metadata.get('requirements'):
        prompt_parts.append("\n## 镜头需求表:")
        prompt_parts.append(product_metadata.get('requirements'))

    prompt_parts.append("\n\n请根据以上信息，生成专业的商业视频分镜脚本，包含 Midjourney/Sora 提示词。")

    return "\n".join(prompt_parts)


# ==================== 启动 ====================
if __name__ == '__main__':
    init_database()
    print("=" * 50)
    print("🎬 AI 商业视频制片工作台启动中...")
    print(f"📡 使用模型: {MODEL_NAME}")
    print(f"🌐 访问地址: http://localhost:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
