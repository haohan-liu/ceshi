"""
AI 商业视频制片工作台 - Flask 后端
双阶段工作流：产品锚定 + 分镜生成
"""
import os
import json
import base64
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

# 加载环境变量
load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

# API 配置
API_KEY = os.getenv("NEW_API_KEY", os.getenv("OPENAI_API_KEY", ""))
API_BASE = os.getenv("NEW_API_BASE_URL", os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"))
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o")

# 初始化 OpenAI 客户端
client = OpenAI(api_key=API_KEY, base_url=API_BASE)


# ==================== 图片压缩 ====================
def compress_image(file_data, max_size=(1024, 1024), quality=85):
    """压缩图片，减少 Base64 大小"""
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


# ==================== 阶段一：产品分析 Prompt ====================
PRODUCT_ANALYSIS_SYSTEM = """You are a senior Midjourney prompt engineer specializing in product photography.

Your task: Analyze the uploaded product images and generate a precise, pure English product appearance description.

CRITICAL RULES:
1. Output ONLY a single line of comma-separated English tags
2. Focus ONLY on: material, texture, color, shape, surface finish, key structural details
3. Do NOT include any lighting, background, or environmental elements
4. Use professional photography terms
5. Keep it under 200 characters total

Example output format:
"metallic aluminum alloy, brushed surface texture, matte silver finish, cylindrical body, 15cm height, precision-machined edges, minimalist industrial design, premium build quality"
"""

PRODUCT_ANALYSIS_USER = """Please analyze this product image and describe its appearance in detail for Midjourney image generation.

Focus on:
- Exact colors and color gradients
- Material texture (matte, glossy, brushed, metallic, etc.)
- Shape and form
- Surface finish details
- Key structural elements
- Size proportions if visible

Provide ONLY the English description tags, comma-separated, no explanations."""


# ==================== 阶段二：分镜生成 Prompt ====================
SCRIPT_GENERATION_SYSTEM = """You are a Hollywood cinematographer and professional storyboard artist.

Your task: Generate professional commercial video storyboards based on the user's requirements.

MANDATORY OUTPUT FORMAT - You MUST output valid Markdown table:

| 镜头编号 | 景别/焦段 | 画面与动作描述 | 首帧提示词(Start) | 尾帧提示词(End) |
|---------|----------|--------------|------------------|----------------|

CRITICAL CONSISTENCY RULE:
- Every "首帧提示词" and "尾帧提示词" MUST contain the user's "锚定词" (anchor prompt) FIRST
- The anchor prompt must appear EXACTLY as provided, then add scene-specific elements
- Do NOT modify or paraphrase the anchor prompt

PROMPT FORMAT (English only, comma-separated tags):
- Start prompts: begin with anchor + specific scene elements
- End prompts: begin with anchor + movement/transformation elements

MANDATORY BILINGUAL FORMAT for each prompt cell:
```
{English prompt}
<br><span style="font-size:12px;color:#9ca3af;">(中文：{Chinese translation})</span>
```

Example:
```
sleek metallic body, brushed aluminum surface, soft studio lighting, 8k, product photography, centered composition
<br><span style="font-size:12px;color:#9ca3af;">(中文：时尚金属机身，刷纹铝面，柔和影棚灯光，8K，产品摄影，居中构图)</span>
```

Keep descriptions concise, professional, and suitable for actual video production."""


# ==================== 路由 ====================
@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')


@app.route('/api/projects', methods=['GET'])
def list_projects():
    """获取所有项目"""
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
        return jsonify({'success': False, 'error': '项目不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== 阶段一：产品特征提取 ====================
@app.route('/api/analyze_product', methods=['POST'])
def analyze_product():
    """
    接收产品图片，返回锚定词
    """
    try:
        # 获取产品名称
        product_name = request.form.get('product_name', 'Unknown Product')

        # 处理图片
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

        # 构建消息内容
        message_content = []
        for img in images:
            message_content.append({
                "type": "image_url",
                "image_url": {"url": img['data'], "detail": "high"}
            })
        message_content.append({
            "type": "text",
            "text": PRODUCT_ANALYSIS_USER
        })

        # 调用 AI
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": PRODUCT_ANALYSIS_SYSTEM},
                    {"role": "user", "content": message_content}
                ],
                max_tokens=500,
                temperature=0.7
            )
        except Exception as api_err:
            print(f"API 调用失败: {traceback.format_exc()}")
            return jsonify({'success': False, 'error': f'API 调用失败: {str(api_err)}'}), 500

        anchor_prompt = response.choices[0].message.content.strip()

        # 创建项目记录
        project_id = create_project(
            project_name=f"{product_name} - {datetime.now().strftime('%Y%m%d %H:%M')}",
            product_name=product_name,
            anchor_prompt=anchor_prompt
        )

        return jsonify({
            'success': True,
            'anchor_prompt': anchor_prompt,
            'project_id': project_id
        })

    except Exception as e:
        print(f"产品分析错误: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== 阶段二：分镜脚本生成（流式） ====================
@app.route('/api/generate_script', methods=['POST'])
def generate_script():
    """
    接收需求表 + 锚定词，生成流式分镜脚本
    """
    try:
        # 获取数据
        anchor_prompt = request.form.get('anchor_prompt', '')
        project_id = request.form.get('project_id')
        requirements_content = ''

        # 解析需求表
        if 'requirements' in request.files:
            file = request.files['requirements']
            if file and file.filename:
                ext = os.path.splitext(file.filename)[1].lower()
                content = file.read()

                if ext in ['.xlsx', '.xls']:
                    if PANDAS_AVAILABLE:
                        try:
                            df = pd.read_excel(BytesIO(content))
                            # 转换为 CSV 格式的纯文本
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
                # 构建提示词
                user_prompt = build_script_prompt(anchor_prompt, requirements_content)

                # 发送开始信号
                yield f"data: {json.dumps({'type': 'start', 'message': '开始生成专业分镜脚本...'})}\n\n"

                # 流式调用
                stream = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": SCRIPT_GENERATION_SYSTEM},
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
                        # 发送增量内容
                        yield f"data: {json.dumps({'type': 'chunk', 'content': content, 'accumulated': accumulated})}\n\n"

                # 完成
                yield f"data: {json.dumps({'type': 'done', 'message': '生成完成'})}\n\n"

                # 保存到数据库
                try:
                    if project_id:
                        update_project(int(project_id), storyboard_content=accumulated)
                    yield f"data: {json.dumps({'type': 'saved', 'message': '已保存到历史记录'})}\n\n"
                except Exception as save_err:
                    yield f"data: {json.dumps({'type': 'save_warning', 'message': f'保存失败: {save_err}'})}\n\n"

            except Exception as e:
                error_detail = traceback.format_exc()
                print(f"生成错误: {error_detail}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

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


def build_script_prompt(anchor_prompt: str, requirements_content: str) -> str:
    """构建分镜生成提示词"""
    prompt = f"""## 产品锚定词 (ANCHOR - 必须原封不动用于所有首尾帧)

{anchor_prompt}

"""

    if requirements_content:
        prompt += f"""## 镜头需求表

{requirements_content}

"""

    prompt += """请根据以上信息，生成专业商业视频分镜脚本。

严格遵循以下格式输出 Markdown 表格：

| 镜头编号 | 景别/焦段 | 画面与动作描述 | 首帧提示词(Start) | 尾帧提示词(End) |
|---------|----------|--------------|------------------|----------------|

【核心一致性法则】：
1. 每个"首帧提示词"和"尾帧提示词"必须以锚定词开头，后面才是场景特定描述
2. 锚定词必须完全一致，不能有任何修改
3. 提示词必须是纯英文逗号分隔的标签

【提示词格式示例】：
首帧: `sleek metallic body, brushed aluminum surface, cinematic soft lighting, 8k, product photography`<br>
      `<span style="font-size:12px;color:#9ca3af;">(中文：时尚金属机身，刷纹铝面，电影级柔和灯光，8K，产品摄影)</span>`

请立即开始生成 Markdown 表格："""

    return prompt


# ==================== 启动 ====================
if __name__ == '__main__':
    init_database()
    print("=" * 60)
    print("  AI 商业视频制片工作台")
    print("  模型: " + MODEL_NAME)
    print("  访问: http://localhost:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
