"""
AI 商业视频制片工作台 - Flask 后端
支持流式 SSE 输出，调用大模型生成专业分镜脚本
"""

import os
import json
from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime
import pandas as pd
import io
import math

from database import get_db

# 加载环境变量
load_dotenv()

# 初始化 Flask
app = Flask(__name__)
CORS(app)

# 初始化 OpenAI 客户端
_api_key = os.getenv("NEW_API_KEY")
_api_base = os.getenv("NEW_API_BASE_URL")

# 避免 httpx proxies 参数问题：如果使用默认 URL 则不设置 base_url
if _api_base and _api_base != "https://api.openai.com/v1":
    client = OpenAI(api_key=_api_key, base_url=_api_base)
else:
    client = OpenAI(api_key=_api_key)

MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o")

# 系统提示词 - 资深跨境电商视觉总监与好莱坞级灯光摄影指导
SYSTEM_PROMPT = """You are a senior cross-border e-commerce visual director and Hollywood-level lighting and photography director.

Your task is to generate professional commercial storyboard scripts based on user-provided product data and requirements table.

## CRITICAL CONSTRAINTS - YOU MUST FOLLOW STRICTLY:

1. **PHYSICAL ACCURACY**: You MUST respect the exact physical dimensions and proportions provided by the user. NEVER distort product size in any frame.

2. **BRAND INTEGRITY**: You MUST preserve all brand elements (logos, colors, distinctive markings) exactly as specified in the "red lines" (forbidden changes).

3. **PROMPT FORMAT**: All prompts MUST be:
   - Pure English
   - Comma-separated tags format
   - No sentences, only descriptive tags
   - Include: camera settings, lighting, composition, product details
   - Start with cinematic quality tags: "cinematic lighting, 8k resolution, photorealistic"

## OUTPUT FORMAT - You must generate a JSON array:

```json
[
  {
    "shot": 1,
    "time": "0s-3s",
    "framing": "Medium Shot",
    "lens": "50mm",
    "movement": "Static",
    "description": "Product displayed on clean white background, soft studio lighting",
    "start_frame": "cinematic lighting, 8k resolution, photorealistic, [PRODUCT NAME] placed center frame, clean white studio background, soft diffused lighting, product in pristine condition, brand logo visible, high-end commercial photography style, shallow depth of field, Sony A7IV camera",
    "end_frame": "cinematic lighting, 8k resolution, photorealistic, [PRODUCT NAME] center frame, product appearance unchanged, brand logo preserved, maintaining exact proportions, soft studio lighting, commercial product photography, do not change product color, do not alter logo, Sony A7IV camera",
    "notes": "中文备注：建立产品第一印象"
  }
]
```

## REQUIREMENTS TABLE FIELDS (if provided):
- 片段时长 (Segment Duration)
- 镜头语言 (Camera Language)
- 画面描述 (Visual Description)
- 核心动作 (Core Action)
- 核心卖点 (Core Selling Points)

## PRODUCT METADATA FIELDS (required):
- 产品名称 (Product Name)
- 核心材质与主色调 (Core Material & Main Color)
- 精确物理尺寸 (Exact Physical Dimensions - MANDATORY REFERENCE)
- 画面红线 (Visual Red Lines - Forbidden Changes)
- 产品功能 (Product Function)
- 卖点 (Selling Points)

## LIGHTING PHILOSOPHY:
- Primary: Cinematic three-point lighting with soft fill
- Product lighting: Edge lighting to highlight material texture
- Ambient: Subtle environmental lighting matching product aesthetic

## CAMERA ANGLES FOR COMMERCIAL:
- Hero Shot: 45-degree angle, medium distance
- Detail Shots: Close-up, macro capability
- Action Shots: Dynamic angles with movement

Generate a complete storyboard based on the provided data. Return ONLY valid JSON array, no other text.
"""


@app.route('/')
def index():
    """渲染主页面"""
    return render_template('index.html')


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """处理 CSV/Excel 文件上传，解析需求表"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': '没有文件上传'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': '文件名为空'}), 400

        # 读取文件内容
        file_content = file.read()

        # 根据文件扩展名解析
        filename = file.filename.lower()

        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(file_content))
        elif filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(io.BytesIO(file_content))
        else:
            return jsonify({'error': '不支持的文件格式，请上传 CSV 或 Excel 文件'}), 400

        # 清理 NaN 值
        df = df.fillna('')

        # 转换为字典列表，并清理所有值
        def clean_value(v):
            if pd.isna(v) or v is None:
                return ''
            if isinstance(v, float) and math.isnan(v):
                return ''
            return str(v).strip()

        data = []
        for _, row in df.iterrows():
            cleaned_row = {k: clean_value(v) for k, v in row.items()}
            data.append(cleaned_row)

        # 处理列名映射（中英文兼容）
        column_mapping = {
            '片段时长': 'duration',
            'duration': 'duration',
            '镜头语言': 'camera_language',
            'camera_language': 'camera_language',
            '画面描述': 'visual_description',
            'visual_description': 'visual_description',
            '核心动作': 'core_action',
            'core_action': 'core_action',
            '核心卖点': 'core_selling_point',
            'core_selling_point': 'core_selling_point'
        }

        normalized_data = []
        for row in data:
            normalized_row = {}
            for key, value in row.items():
                # 尝试匹配已知列名
                matched_key = column_mapping.get(key, key)
                normalized_row[matched_key] = value
            normalized_data.append(normalized_row)

        return jsonify({
            'success': True,
            'data': normalized_data,
            'columns': list(df.columns)
        })

    except Exception as e:
        return jsonify({'error': f'文件解析失败: {str(e)}'}), 500


@app.route('/api/generate', methods=['POST'])
def generate_storyboard():
    """
    接收产品数据和表格数据，调用 AI 生成流式分镜脚本
    使用 SSE (Server-Sent Events) 进行流式输出
    """
    # 先获取所有需要的数据
    data = request.get_json()
    product_metadata = data.get('productMetadata', {})
    table_data = data.get('tableData', [])

    def generate():
        try:
            # 构建用户提示
            user_prompt = build_user_prompt(product_metadata, table_data)

            # 发送开始信号
            yield f"data: {json.dumps({'type': 'start', 'message': '开始生成商业分镜...'})}\n\n"

            # 调用 AI 流式接口
            full_response = []

            stream = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                stream=True,
                temperature=0.7,
                max_tokens=4000
            )

            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response.append(content)

                    # 发送增量内容
                    yield f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"

            # 合并完整响应
            complete_response = ''.join(full_response)

            # 尝试解析 JSON
            try:
                # 提取 JSON（处理可能的 markdown 代码块）
                json_str = extract_json(complete_response)
                storyboard_data = json.loads(json_str)

                # 发送成功信号
                yield f"data: {json.dumps({'type': 'success', 'data': storyboard_data})}\n\n"

            except json.JSONDecodeError as e:
                # JSON 解析失败，发送原始内容
                yield f"data: {json.dumps({'type': 'error', 'message': 'AI 输出格式异常', 'raw': complete_response})}\n\n"

        except Exception as e:
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


def build_user_prompt(product_metadata: dict, table_data: list) -> str:
    """构建发送给 AI 的用户提示"""
    prompt_parts = []

    # 产品元数据
    prompt_parts.append("## PRODUCT METADATA (MUST RESPECT):")
    prompt_parts.append(f"- Product Name: {product_metadata.get('product_name', 'N/A')}")
    prompt_parts.append(f"- Core Material & Color: {product_metadata.get('material_color', 'N/A')}")
    prompt_parts.append(f"- Exact Dimensions (CRITICAL - DO NOT DISTORT): {product_metadata.get('dimensions', 'N/A')}")
    prompt_parts.append(f"- Visual Red Lines (FORBIDDEN TO CHANGE): {product_metadata.get('red_lines', 'N/A')}")
    prompt_parts.append(f"- Product Function: {product_metadata.get('function', 'N/A')}")
    prompt_parts.append(f"- Selling Points: {product_metadata.get('selling_points', 'N/A')}")

    # 需求表数据
    if table_data:
        prompt_parts.append("\n## REQUIREMENTS TABLE:")
        for i, row in enumerate(table_data, 1):
            prompt_parts.append(f"\nShot {i}:")
            prompt_parts.append(f"- Duration: {row.get('duration', 'N/A')}")
            prompt_parts.append(f"- Camera Language: {row.get('camera_language', 'N/A')}")
            prompt_parts.append(f"- Visual Description: {row.get('visual_description', 'N/A')}")
            prompt_parts.append(f"- Core Action: {row.get('core_action', 'N/A')}")
            prompt_parts.append(f"- Core Selling Point: {row.get('core_selling_point', 'N/A')}")
    else:
        prompt_parts.append("\n## NO REQUIREMENTS TABLE PROVIDED - Generate a standard 6-8 shot commercial storyboard.")

    prompt_parts.append("\n\nGenerate the storyboard in the exact JSON format specified in the system prompt.")

    return '\n'.join(prompt_parts)


def extract_json(text: str) -> str:
    """从文本中提取 JSON 内容"""
    # 尝试提取 markdown 代码块
    if '```json' in text:
        start = text.find('```json') + 7
        end = text.find('```', start)
        return text[start:end].strip()
    elif '```' in text:
        start = text.find('```') + 3
        end = text.find('```', start)
        return text[start:end].strip()

    # 尝试找到 JSON 数组/对象的开始和结束
    start_idx = text.find('[')
    if start_idx == -1:
        start_idx = text.find('{')

    if start_idx != -1:
        # 简单处理：返回从第一个 [ 或 { 开始的内容
        return text[start_idx:]

    return text


@app.route('/api/save', methods=['POST'])
def save_project():
    """保存项目到数据库"""
    try:
        data = request.get_json()
        project_name = data.get('project_name', f'项目_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        product_metadata = data.get('product_metadata', {})
        table_data = data.get('table_data', [])
        generated_script = data.get('generated_script', '')

        db = get_db()
        project_id = db.save_project(
            project_name=project_name,
            product_metadata=product_metadata,
            raw_table_data=table_data,
            generated_script=generated_script
        )

        return jsonify({
            'success': True,
            'project_id': project_id,
            'message': '项目保存成功'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/projects', methods=['GET'])
def get_projects():
    """获取所有项目历史"""
    try:
        db = get_db()
        projects = db.get_all_projects()
        return jsonify({'success': True, 'projects': projects})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/project/<int:project_id>', methods=['GET'])
def get_project(project_id):
    """获取单个项目详情"""
    try:
        db = get_db()
        project = db.get_project(project_id)

        if project:
            return jsonify({'success': True, 'project': project})
        else:
            return jsonify({'error': '项目不存在'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/project/<int:project_id>', methods=['DELETE'])
def delete_project(project_id):
    """删除项目"""
    try:
        db = get_db()
        deleted = db.delete_project(project_id)

        if deleted:
            return jsonify({'success': True, 'message': '项目已删除'})
        else:
            return jsonify({'error': '项目不存在'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/<int:project_id>', methods=['GET'])
def export_project(project_id):
    """导出项目脚本"""
    try:
        db = get_db()
        project = db.get_project(project_id)

        if project:
            return jsonify({
                'success': True,
                'data': {
                    'project_name': project['project_name'],
                    'created_at': project['created_at'],
                    'product_metadata': project['product_metadata'],
                    'generated_script': project['generated_script']
                }
            })
        else:
            return jsonify({'error': '项目不存在'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print(f"🚀 AI 商业视频制片工作台启动中...")
    print(f"📡 使用模型: {MODEL_NAME}")
    print(f"🌐 访问地址: http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
