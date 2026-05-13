"""
AI 商业视频制片工作台 - 企业级重构版
"""
import os
import re
import json
import base64
import traceback
from datetime import datetime
from io import BytesIO

from flask import Flask, render_template, request, jsonify, Response, send_file
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

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

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
    """根据画幅比例构建好莱坞级别的专业分镜 system prompt"""
    ar_display = "16:9 Cinematic Widescreen" if aspect_ratio == "16:9" else "9:16 Vertical Mobile"
    ar_param = "--ar 16:9" if aspect_ratio == "16:9" else "--ar 9:16"

    return f"""You are a Hollywood Director of Photography (DP) with 20+ years of experience in commercial cinematography.

═══════════════════════════════════════════════════════════════
STRICT RULES - VIOLATION = REJECTION
═══════════════════════════════════════════════════════════════

【RULE #1: NO HALLUCINATION】
• Generate EXACTLY the same number of shots as the input table rows
• ONE row = ONE shot minimum
• If a row describes multiple actions, split into MULTIPLE shots
• NEVER invent or add shots not in the input table

【RULE #2: ANCHOR KEYWORDS MANDATORY】
• EVERY shot (both Start AND End) MUST begin with the anchor keywords
• Copy-paste anchor keywords VERBATIM - do not modify, translate, or paraphrase
• Anchor keywords = your product's visual identity

【RULE #3: PROFESSIONAL MIDJOURNEY TAGS REQUIRED】
• Start Frame = [Shot Type] + [Anchor Keywords] + [Initial State] + [Camera/Lighting] + {ar_param}
• End Frame = [Shot Type] + [Anchor Keywords] + [Final State] + [Camera/Lighting] + {ar_param}
• Must include professional tags: cinematic lighting, shot on 35mm, photorealistic, film grain, etc.
• Material and texture details are MANDATORY for the product

【RULE #4: TRANSLATION FORMAT - MANDATORY】
Every Start/End prompt cell MUST use this EXACT format:
`English prompt text with professional tags {ar_param} __CN__Precise Chinese translation including aspect ratio__ENDCN__`

Example:
`close-up product shot, metallic finish, soft shadows, cinematic lighting, shot on 35mm lens {ar_param} __CN__产品特写，金属质感，柔和阴影，电影级灯光，35mm镜头拍摄__ENDCN__`

【RULE #5: ASPECT RATIO SAFETY】
• Product MUST NOT be squashed, stretched, or deformed at any ratio
• Only adjust composition, background, and framing
• Always include {ar_param} at the END of every prompt

【RULE #6: LOGO STANDARD】
• All "logo", "mark", "emblem", "brand" = "LOGO" in English
• LOGO must be properly integrated into the visual composition

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════

Output ONLY a pure Markdown table:

| 镜头 | 景别/焦段 | 画面与动作描述 | 首帧提示词(Start) | 尾帧提示词(End) |
| 1 | wide shot | establishing view | Start prompt __CN__中文翻译__ENDCN__ | End prompt __CN__中文翻译__ENDCN__ |

DO NOT include any other text. Start generating now."""


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


@app.route('/api/export_excel', methods=['POST'])
def export_excel():
    """导出精美 Excel 报表"""
    if not OPENPYXL_AVAILABLE:
        return jsonify({'success': False, 'error': 'openpyxl 未安装'}), 500
    
    try:
        data = request.get_json()
        project_name = data.get('project_name', '未命名项目')
        product_name = data.get('product_name', '')
        aspect_ratio = data.get('aspect_ratio', '16:9')
        anchor_prompt = data.get('anchor_prompt', '')
        storyboard_content = data.get('storyboard_content', '')
        
        # 创建工作簿
        wb = Workbook()
        ws = wb.active
        ws.title = "分镜脚本"
        
        # 样式定义
        header_fill = PatternFill(start_color="1e293b", end_color="1e293b", fill_type="solid")
        header_font = Font(name='Microsoft YaHei', size=11, bold=True, color="FFFFFF")
        title_font = Font(name='Microsoft YaHei', size=14, bold=True, color="1e293b")
        info_font = Font(name='Microsoft YaHei', size=10, color="64748b")
        prompt_font = Font(name='JetBrains Mono', size=10, color="1e293b")
        cn_font = Font(name='Microsoft YaHei', size=9, color="64748b")
        thin_border = Border(
            left=Side(style='thin', color='e2e8f0'),
            right=Side(style='thin', color='e2e8f0'),
            top=Side(style='thin', color='e2e8f0'),
            bottom=Side(style='thin', color='e2e8f0')
        )
        
        # 第1行: 项目标题
        ws.merge_cells('A1:G1')
        ws['A1'] = f"分镜脚本 - {project_name}"
        ws['A1'].font = title_font
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[1].height = 30
        
        # 第2行: 项目信息
        ws.merge_cells('A2:G2')
        ar_text = "16:9 横屏" if aspect_ratio == "16:9" else "9:16 竖屏"
        info_text = f"产品: {product_name or '未命名'}  |  画幅: {ar_text}"
        ws['A2'] = info_text
        ws['A2'].font = info_font
        ws['A2'].alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[2].height = 22
        
        # 第3行: 锚定词
        ws.merge_cells('A3:G3')
        ws['A3'] = f"锚定词: {anchor_prompt[:100]}{'...' if len(anchor_prompt) > 100 else ''}"
        ws['A3'].font = Font(name='Microsoft YaHei', size=9, color="64748b", italic=True)
        ws['A3'].alignment = Alignment(horizontal='left', vertical='center')
        ws.row_dimensions[3].height = 18
        
        # 第4行: 表头
        headers = ['镜头', '景别/焦段', '画面与动作描述', '首帧提示词 (English)', '首帧翻译 (中文)', '尾帧提示词 (English)', '尾帧翻译 (中文)']
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=4, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = thin_border
        ws.row_dimensions[4].height = 28
        
        # 解析 Markdown 表格
        shots = parse_storyboard_md(storyboard_content)
        
        # 填充数据行
        start_row = 5
        for row_idx, shot in enumerate(shots, start_row):
            # 镜头编号
            cell = ws.cell(row=row_idx, column=1, value=shot.get('num', row_idx - start_row + 1))
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = thin_border
            
            # 景别/焦段
            cell = ws.cell(row=row_idx, column=2, value=shot.get('shot_type', ''))
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = thin_border
            
            # 画面描述
            cell = ws.cell(row=row_idx, column=3, value=shot.get('description', ''))
            cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
            cell.border = thin_border
            
            # 首帧英文
            cell = ws.cell(row=row_idx, column=4, value=shot.get('start_en', ''))
            cell.font = prompt_font
            cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
            cell.border = thin_border
            
            # 首帧中文
            cell = ws.cell(row=row_idx, column=5, value=shot.get('start_cn', ''))
            cell.font = cn_font
            cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
            cell.border = thin_border
            
            # 尾帧英文
            cell = ws.cell(row=row_idx, column=6, value=shot.get('end_en', ''))
            cell.font = prompt_font
            cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
            cell.border = thin_border
            
            # 尾帧中文
            cell = ws.cell(row=row_idx, column=7, value=shot.get('end_cn', ''))
            cell.font = cn_font
            cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
            cell.border = thin_border
            
            ws.row_dimensions[row_idx].height = 60
        
        # 列宽设置
        col_widths = [8, 12, 25, 45, 22, 45, 22]
        for col, width in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(col)].width = width
        
        # 生成文件
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        filename = f"分镜脚本_{project_name[:20]}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"Excel 导出错误: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


def parse_storyboard_md(content: str) -> list:
    """解析 Markdown 表格，提取分镜数据"""
    shots = []
    
    # 匹配表格行
    rows = re.findall(r'\|\s*(\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*(.+?)\s*\|\s*(.+?)\s*\|', content)
    
    for row in rows:
        num, shot_type, description, start_cell, end_cell = row
        
        # 解析首帧
        start_en, start_cn = parse_prompt_cell(start_cell)
        
        # 解析尾帧
        end_en, end_cn = parse_prompt_cell(end_cell)
        
        shots.append({
            'num': num.strip(),
            'shot_type': shot_type.strip(),
            'description': description.strip(),
            'start_en': start_en.strip(),
            'start_cn': start_cn.strip(),
            'end_en': end_en.strip(),
            'end_cn': end_cn.strip()
        })
    
    return shots


def parse_prompt_cell(cell: str) -> tuple:
    """解析提示词单元格，提取英文和中文"""
    # 移除 HTML 标签
    cell = re.sub(r'<[^>]+>', '', cell)
    
    # 匹配 __CN__...__ENDCN__ 格式（支持换行和所有标点）
    match = re.search(r'__CN__([\s\S]*?)__ENDCN__', cell)
    
    if match:
        chinese = match.group(1).strip()
        english = re.sub(r'__CN__[\s\S]*?__ENDCN__', '', cell).strip()
        return english, chinese
    
    return cell.strip(), ''


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
            accumulated = ''
            
            try:
                yield f"data: {json.dumps({'type': 'start', 'message': '正在分析产品...'})}\n\n"

                client = get_client()
                model = os.getenv("MODEL_NAME", "gpt-4o")
                
                messages = [
                    {"role": "system", "content": PRODUCT_ANALYSIS_SYSTEM},
                    {"role": "user", "content": message_content}
                ]
                
                try:
                    stream = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        max_tokens=500,
                        temperature=0.7,
                        stream=True
                    )
                    
                    for chunk in stream:
                        # 安全检查
                        try:
                            if not hasattr(chunk, 'choices') or not chunk.choices:
                                continue
                            delta = chunk.choices[0].delta
                            if delta and hasattr(delta, 'content') and delta.content:
                                content = delta.content
                                accumulated += content
                                yield f"data: {json.dumps({'type': 'chunk', 'content': content, 'accumulated': accumulated})}\n\n"
                        except Exception as chunk_err:
                            print(f"Chunk 处理错误: {chunk_err}")
                            continue
                            
                except Exception as api_err:
                    # API 调用本身的错误
                    print(f"API 调用错误: {api_err}")
                    yield f"data: {json.dumps({'type': 'error', 'message': f'API 错误: {str(api_err)[:100]}'})}\n\n"
                    return

                # 确保至少有一些内容
                if not accumulated:
                    accumulated = "metallic finish, minimalist design, clean lines, high quality materials, sleek appearance"
                    
                yield f"data: {json.dumps({'type': 'done', 'anchor_prompt': accumulated})}\n\n"

            except Exception as e:
                error_msg = str(e)
                print(f"="*50)
                print(f"分析错误: {error_msg}")
                print(f"traceback: {traceback.format_exc()}")
                print(f"="*50)
                # 如果已经有内容，发送 done 而不是 error
                if accumulated:
                    yield f"data: {json.dumps({'type': 'done', 'anchor_prompt': accumulated})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'message': f'分析失败: {error_msg[:100]}'})}\n\n"

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
        product_name = request.form.get('product_name', '未命名')
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
            accumulated = ''
            saved_project_id = None
            
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

                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        accumulated += content
                        yield f"data: {json.dumps({'type': 'chunk', 'content': content, 'accumulated': accumulated})}\n\n"

                # ========== 强制保存逻辑 ==========
                try:
                    if project_id:
                        # 更新已有项目
                        update_project(int(project_id), 
                                     storyboard_content=accumulated, 
                                     aspect_ratio=aspect_ratio)
                        saved_project_id = int(project_id)
                    else:
                        # 创建新项目
                        saved_project_id = create_project(
                            project_name=f"{product_name} - {datetime.now().strftime('%m%d %H:%M')}",
                            product_name=product_name,
                            anchor_prompt=anchor_prompt,
                            storyboard_content=accumulated,
                            aspect_ratio=aspect_ratio
                        )
                    
                    yield f"data: {json.dumps({'type': 'saved', 'project_id': saved_project_id, 'message': '已保存'})}\n\n"
                except Exception as save_err:
                    print(f"保存失败: {save_err}")
                    yield f"data: {json.dumps({'type': 'save_warning', 'message': str(save_err)})}\n\n"
                # =================================

                yield f"data: {json.dumps({'type': 'done', 'message': '生成完成', 'project_id': saved_project_id})}\n\n"

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
7. Output format: English prompt text {ar_param} __CN__Chinese translation__ENDCN__

## 【Output Format - PURE MARKDOWN】

| 镜头 | 景别/焦段 | 画面与动作描述 | 首帧提示词(Start) | 尾帧提示词(End) |
| 1 | ... | ... | prompt1 __CN__翻译1__ENDCN__ | prompt2 __CN__翻译2__ENDCN__ |

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
