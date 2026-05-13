"""
AI 商业视频制片工作台 - 企业级重构版
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

from database import init_database, create_project, update_project, get_all_projects, get_project, delete_project, rename_project

# 加载环境变量
load_dotenv(override=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024


# ==================== OpenAI 客户端 ====================
def get_client():
    """获取当前配置的 OpenAI 客户端"""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(env_path, override=True)
    
    api_key = os.getenv("NEW_API_KEY", "")
    api_base = os.getenv("NEW_API_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("MODEL_NAME", "")
    
    print(f"[DEBUG] .env: {env_path}")
    print(f"[DEBUG] Key: {api_key[:15]}..." if api_key else "[DEBUG] Key: 未设置")
    print(f"[DEBUG] Base: {api_base}")
    print(f"[DEBUG] Model: {model}")
    
    if not api_key:
        raise Exception("API Key 未配置！请编辑 .env 文件")
    if not model:
        raise Exception("模型名称未配置！请编辑 .env 文件")
        
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
        img.save(output, format="JPEG", quality=quality, optimize=True)
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
    """根据画幅比例构建专业的 system prompt"""
    ar_display = "16:9 横屏 (Cinematic Widescreen)" if aspect_ratio == "16:9" else "9:16 竖屏 (Vertical Mobile)"
    ar_param = "--ar 16:9" if aspect_ratio == "16:9" else "--ar 9:16"

    composition_rules = """
【画幅与构图 - {ar_display}】
- 横向: cinematic widescreen, landscape orientation, expansive environment, film grain, cinematic composition
- 竖向: vertical video format, portrait orientation, tight framing, optimized for mobile, vertical composition
""".format(ar_display=ar_display) if aspect_ratio == "16:9" else """
【画幅与构图 - {ar_display}】
- 横向: cinematic widescreen, landscape orientation, expansive environment, film grain, cinematic composition
- 竖向: vertical video format, portrait orientation, tight framing, optimized for mobile, vertical composition
""".format(ar_display=ar_display)

    return f"""You are a Hollywood cinematographer (Director of Photography).

【CRITICAL RULE 1: NO HALLUCINATION】
- Strictly generate shots based on the user's CSV/Excel table data
- The number of shots MUST match the number of rows in the table
- NEVER invent any shots not in the table

【CRITICAL RULE 2: ACTION SPLITTING】
- If a row contains multiple actions (e.g., "first aerial shot... then side shot..."), split into multiple independent shots
- Each shot MUST have a clear physical action
- Do not miss any action description

【CRITICAL RULE 3: START-END FRAME BINDING】
- Start Frame (Start): Describe the initial state of the scene + anchor keywords
- End Frame (End): Describe the state after the action completes + anchor keywords
- MUST include clear physical action and state change

【CRITICAL RULE 4: ANCHOR CONSISTENCY】
- Every start and end frame MUST start with the anchor keywords
- Anchor keywords must be used verbatim, do not modify

【CRITICAL RULE 5: {ar_display}】
{composition_rules}

【CRITICAL RULE 6: PARAM MANDATORY】
- EVERY start and end prompt MUST end with: {ar_param}
- Append directly to the English prompt

【CRITICAL RULE 7: PRODUCT NO DISTORTION】
- Regardless of aspect ratio changes, the product MUST NOT be squashed, stretched or deformed
- Only adjust composition and background

【CRITICAL RULE 8: LOGO STANDARD】
- All "logo", "mark", "emblem" unified translation: "LOGO"

【CRITICAL RULE 9: PROMPT PROFESSIONALISM】
- You are writing Midjourney/Sora control instructions, NOT essays!
- Start Frame Prompt = [Environment/Shot Type] + [Product Anchor Keywords] + [Initial State]
- End Frame Prompt = [Environment/Shot Type] + [Product Anchor Keywords] + [Final State After Action]
- Must be professional English visual tags (e.g., cinematic lighting, shot on 35mm lens, photorealistic)

【OUTPUT FORMAT - PURE MARKDOWN TABLE】

Output pure Markdown table:

| 镜头 | 景别/焦段 | 画面与动作描述 | 首帧提示词(Start) | 尾帧提示词(End) |
| 1 | ... | ... | ... | ... |

【PROMPT FORMAT - DECOUPLED TRANSLATION】

In the Start/End prompt cells, output in this EXACT format:
```
English prompt text here {ar_param} <!--cn:Chinese translation here:-->
```

The <!--cn:...:--> is an HTML comment for translation. Do NOT use <span title="..."> tags!

Example:
`close-up product shot, soft studio lighting, centered composition, sharp focus {ar_param} <!--cn:产品特写，柔和灯光，中心构图，清晰对焦:-->`

【IMPORTANT】
- [Image Reference] does not need translation
- Strictly follow the table row count - N rows = N shots minimum""".format(ar_display=ar_display, ar_param=ar_param)


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


@app.route('/api/history/rename', methods=['POST'])
def rename_project_route():
    """重命名项目"""
    try:
        data = request.get_json()
        project_id = data.get('id')
        new_name = data.get('name', '').strip()
        
        if not project_id or not new_name:
            return jsonify({'success': False, 'error': '参数错误'}), 400
            
        success = rename_project(project_id, new_name)
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
                model = os.getenv("MODEL_NAME", "gpt-4o")
                stream = client.chat.completions.create(
                    model=model,
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
            project_name=f"{product_name} - {datetime.now().strftime('%m%d %H:%M')}",
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

                yield f"data: {json.dumps({'type': 'start', 'message': f'生成中 [{aspect_ratio}]...'})}\n\n"

                client = get_client()
                model = os.getenv("MODEL_NAME", "gpt-4o")
                stream = client.chat.completions.create(
                    model=model,
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

    prompt = f"""## 【Phase 1】Product Anchor Keywords (ANCHOR)

```
{anchor_prompt}
```

"""

    if requirements_content:
        prompt += f"""## 【Phase 2】Shot Requirements Table

Analyze the following table row by row and generate corresponding shots:
```
{requirements_content}
```

"""

    prompt += f"""## 【Phase 3】Aspect Ratio

Current selection: {ar_display}

"""

    prompt += f"""## 【Execution Requirements】

1. Analyze the table row by row, generate at least N shots for N rows
2. Action splitting: multiple actions → multiple independent shots
3. Start Frame: initial state + anchor keywords + composition + {ar_param}
4. End Frame: completed state + anchor keywords + composition + {ar_param}
5. Chinese translation must include aspect ratio description ({ar_display})
6. All "logo", "mark", "emblem" unified: "LOGO"
7. Output format: English prompt text {ar_param} <!--cn:Chinese translation:-->

## 【Output Format - PURE MARKDOWN】

| 镜头 | 景别/焦段 | 画面与动作描述 | 首帧提示词(Start) | 尾帧提示词(End) |
| 1 | ... | ... | prompt1 <!--cn:翻译1:--> | prompt2 <!--cn:翻译2:--> |

Start now:"""

    return prompt


# ==================== 启动 ====================
if __name__ == '__main__':
    init_database()
    model = os.getenv("MODEL_NAME", "gpt-4o")
    api_base = os.getenv("NEW_API_BASE_URL", "")
    print("=" * 50)
    print("  AI Storyboard Studio")
    print(f"  模型: {model}")
    print(f"  API:  {api_base}")
    print("  访问: http://localhost:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
