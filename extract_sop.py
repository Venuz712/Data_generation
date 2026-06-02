import os
import json
import re
from openai import OpenAI

# ================== 配置 ==================
API_BASE_URL = "https://api.moark.com/v1"
API_KEY = "6QPX1SXYHFN9FWRRZHGLWFXIFICNMKVHANTLWP58"
MODEL_NAME = "Qwen3.5-122B-A10B"

client = OpenAI(
    base_url=API_BASE_URL,
    api_key=API_KEY,
    default_headers={"X-Failover-Enabled": "true"},
)

# ================== 文本分割函数（与原代码相同） ==================
def split_into_units(text, file_name):
    """根据文件内容结构精确分割单元，始终返回列表"""
    units = []

    if file_name == "甘蔗病虫害.txt":
        blocks = re.split(r'\n\n(?=\d+[．\.])', text)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.split('\n')
            if not lines:
                continue
            title = lines[0].strip()
            content = '\n'.join(lines[1:]).strip()
            unit_type = "insect" if "【形态特征】" in content else "disease"
            units.append({"title": title, "content": content, "type": unit_type})
        return units

    if file_name == "采收贮藏.txt":
        lines = text.split('\n')
        current_section = ""
        current_title = None
        current_content = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if re.match(r'^[一二]、', line):
                if current_title and current_content:
                    units.append({"title": f"{current_section}_{current_title}", "content": '\n'.join(current_content), "type": "disaster"})
                current_section = line
                current_title = None
                current_content = []
                continue
            match = re.match(r'^(\d+)[．\.]\s*(.*)', line)
            if match:
                if current_title and current_content:
                    units.append({"title": f"{current_section}_{current_title}", "content": '\n'.join(current_content), "type": "disaster"})
                current_title = f"{match.group(1)}.{match.group(2)}"
                current_content = []
            else:
                if current_title is not None:
                    current_content.append(line)
        if current_title and current_content:
            units.append({"title": f"{current_section}_{current_title}", "content": '\n'.join(current_content), "type": "disaster"})
        if not units:
            parts = re.split(r'(?=^[一二]、)', text, flags=re.MULTILINE)
            for part in parts:
                if part.strip():
                    title = part.split('\n')[0].strip()
                    units.append({"title": title, "content": part.strip(), "type": "disaster"})
        return units

    if file_name == "甘蔗操作规程.txt":
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        current_title = None
        current_content = []
        for para in paragraphs:
            first_line = para.split('\n')[0].strip()
            if re.match(r'^(\d+(?:\.\d+)?)[．\.]', first_line):
                if current_title and current_content:
                    units.append({"title": current_title, "content": '\n\n'.join(current_content), "type": "cultivation"})
                current_title = first_line[:100]
                current_content = [para]
            else:
                if current_title is not None:
                    current_content.append(para)
        if current_title and current_content:
            units.append({"title": current_title, "content": '\n\n'.join(current_content), "type": "cultivation"})
        if not units:
            sections = re.split(r'(?=整地与起垄|苗期管理|养分管理|植保)', text)
            for sec in sections:
                if sec.strip():
                    title = sec.strip().split('\n')[0][:50]
                    units.append({"title": title, "content": sec.strip(), "type": "cultivation"})
        return units

    else:
        lines = text.split('\n')
        current_title = None
        current_content = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            match = re.match(r'^([一二三四五六七八九十]+、|\d+\.)\s*(.*)', line)
            if match:
                if current_title and current_content:
                    units.append({"title": current_title, "content": '\n'.join(current_content), "type": "disaster"})
                current_title = match.group(1) + match.group(2)
                current_content = []
            else:
                if current_title is not None:
                    current_content.append(line)
        if current_title and current_content:
            units.append({"title": current_title, "content": '\n'.join(current_content), "type": "disaster"})
        if not units:
            paras = [p.strip() for p in text.split('\n\n') if len(p.strip()) > 50]
            for p in paras:
                units.append({"title": p[:40], "content": p, "type": "disaster"})
        return units

# ================== 辅助函数：提取并修复JSON ==================
def repair_json(text):
    """尝试修复常见的JSON格式错误"""
    # 移除代码块标记
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```', '', text)
    # 移除尾随逗号（对象和数组内）
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    # 修复单引号（可选，风险较低）
    # text = text.replace("'", '"')
    return text.strip()

def extract_json_from_text(text):
    """从模型返回文本中提取JSON对象"""
    # 先尝试直接解析整个文本
    text = text.strip()
    if text.startswith('{') and text.endswith('}'):
        try:
            return json.loads(text)
        except:
            pass
    # 尝试提取第一个完整的JSON对象
    match = re.search(r'(\{.*\})', text, re.DOTALL)
    if match:
        json_str = repair_json(match.group(1))
        try:
            return json.loads(json_str)
        except:
            pass
    return None

# ================== 复杂决策型JSON抽取（第一种JSON） ==================
def build_complex_prompt(unit_content, unit_type, source_file):
    base_instruction = """从甘蔗种植技术文本中提取信息，生成一个结构化的决策支持JSON。输出必须符合以下格式，未提及的字段用合理推断或"未提及"填充，对于需要条件判断的场景，请根据常见农业知识生成2-3个典型分支。

输出JSON结构：
{
  "meta": {
    "title": "甘蔗XXX标准操作程序",
    "crop": "甘蔗",
    "variety_suitability": ["推荐品种列表，若无则空数组"],
    "growth_stage": "适用生育期，若无则写"全生育期"",
    "source": "来源文件名",
    "version": "1.0"
  },
  "diagnosis_criteria": {
    "symptoms": ["症状列表（病害为病原与症状，虫害为形态特征，灾害为典型表现）"],
    "triggers": ["发生条件/生活习性/灾害诱因列表"],
    "reasoning_chain": "基于症状和条件的推理逻辑，例如：如果观察到X且环境Y，则可判定为Z。",
    "confidence": "高/中/低（根据症状典型性描述）"
  },
  "missing_info_strategy": {
    "key_entities": [
      {
        "name": "缺失的关键变量名称",
        "type": "categorical|boolean|numeric",
        "options": ["可能的值1", "值2"] (如果是categorical),
        "description": "变量含义描述",
        "why_important": "为什么需要知道这个信息"
      }
    ],
    "optional_entities": [
      {
        "name": "可选变量名称",
        "type": "text|categorical",
        "description": "变量含义",
        "why_important": "作用说明"
      }
    ],
    "clarification_templates": {
      "变量名": "向用户询问该变量的话术模板"
    }
  },
  "response_matrix": {
    "scenarios": [
      {
        "condition_checks": {
          "条件变量1": "条件值或列表",
          "条件变量2": "条件值"
        },
        "response_type": "complete_solution | partial_solution_with_clarification | alternative_solution",
        "content": "针对该条件的操作指导文本",
        "follow_up_question": "如果是partial类型，需要进一步询问的问题",
        "fallback_strategy": "备用方案（可选）"
      }
    ],
    "default_response": {
      "content": "当缺少关键信息时的默认回复",
      "response_type": "clarification_only"
    }
  }
}

要求：
- 对于病害/虫害，diagnosis_criteria中的symptoms和triggers根据原文内容填写。
- missing_info_strategy中，根据原文中未明确但重要的信息点（如病情阶段、环境条件、用药历史等）提炼key_entities。
- response_matrix中的scenarios至少生成2个合理分支，例如：初期轻症+环境有利 → 完整方案；重症+环境不利 → 部分方案+追问。
- 如果原文缺乏具体条件，请根据农业常识构建典型场景。

原文内容：
"""
    if unit_type == "disease":
        prompt = base_instruction + f"""
类型：甘蔗病害
原文：
{unit_content}

请输出JSON："""
    elif unit_type == "insect":
        prompt = base_instruction + f"""
类型：甘蔗虫害
原文：
{unit_content}

请输出JSON："""
    elif unit_type == "cultivation":
        prompt = base_instruction + f"""
类型：甘蔗栽培管理
注意：diagnosis_criteria中symptoms可改为"栽培要点描述"，triggers可改为"适宜条件或注意事项"。
原文：
{unit_content}

请输出JSON："""
    else:  # disaster
        prompt = base_instruction + f"""
类型：甘蔗灾害应对
原文：
{unit_content}

请输出JSON："""
    return prompt

def extract_complex_sop(unit_content, unit_type, source_file):
    # 输入验证：防止 None 或空内容
    if not isinstance(unit_content, str) or not unit_content.strip():
        print("  单元内容无效（为空或非字符串），跳过复杂抽取")
        return None
    prompt = build_complex_prompt(unit_content, unit_type, source_file)
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are an agricultural expert. Output only valid JSON. Do not wrap in markdown. Ensure no trailing commas."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=8000,  # 增加以防止截断
        )
        result_text = response.choices[0].message.content.strip()
        finish_reason = response.choices[0].finish_reason
        print(f"    复杂版返回长度: {len(result_text)} 字符, finish_reason: {finish_reason}")
        if finish_reason == "length":
            print("    警告：返回内容因长度限制被截断，考虑进一步增加 max_tokens")
        sop = extract_json_from_text(result_text)
        if sop is None:
            print(f"    无法解析复杂JSON，原始返回前200字符: {result_text[:200]}")
            return None
        # 确保source字段存在
        if "meta" in sop and "source" not in sop["meta"]:
            sop["meta"]["source"] = source_file
        elif "source" not in sop:
            sop["source"] = source_file
        return sop
    except Exception as e:
        print(f"    复杂版抽取异常: {e}")
        return None

# ================== 保存复杂SOP ==================
def complex_sop_to_markdown(sop):
    # 简单展示复杂JSON的核心内容
    md = f"# {sop.get('meta', {}).get('title', '甘蔗复杂决策SOP')}\n\n"
    md += f"**作物**：{sop.get('meta', {}).get('crop', '甘蔗')}  "
    md += f"**生育期**：{sop.get('meta', {}).get('growth_stage', '未提及')}  "
    md += f"**品种**：{', '.join(sop.get('meta', {}).get('variety_suitability', []))}\n\n"
    
    diag = sop.get('diagnosis_criteria', {})
    md += "## 诊断标准\n"
    md += f"**症状**：\n" + "\n".join([f"- {s}" for s in diag.get('symptoms', [])]) + "\n\n"
    md += f"**诱因/条件**：\n" + "\n".join([f"- {t}" for t in diag.get('triggers', [])]) + "\n\n"
    md += f"**推理链**：{diag.get('reasoning_chain', '未提及')}\n"
    md += f"**置信度**：{diag.get('confidence', '未提及')}\n\n"
    
    md += "## 响应方案矩阵\n"
    for i, sc in enumerate(sop.get('response_matrix', {}).get('scenarios', []), 1):
        md += f"### 场景 {i}\n"
        md += f"**条件**：{json.dumps(sc.get('condition_checks', {}), ensure_ascii=False)}\n"
        md += f"**响应类型**：{sc.get('response_type', '')}\n"
        md += f"**操作内容**：{sc.get('content', '')}\n"
        if sc.get('follow_up_question'):
            md += f"**追问**：{sc['follow_up_question']}\n"
        if sc.get('fallback_strategy'):
            md += f"**备用方案**：{sc['fallback_strategy']}\n"
        md += "\n"
    default = sop.get('response_matrix', {}).get('default_response', {})
    md += f"**默认回复**：{default.get('content', '')}\n\n"
    
    md += f"**来源**：{sop.get('meta', {}).get('source', sop.get('source', '未知'))}\n"
    return md

def save_complex_sop(sop, output_dir="output1", suffix=None):
    os.makedirs(output_dir, exist_ok=True)
    title = sop.get('meta', {}).get('title', 'untitled')
    title = title.replace('/', '_').replace(' ', '_')
    if suffix:
        title = f"{title}_{suffix}"
    with open(os.path.join(output_dir, f"{title}_complex.json"), "w", encoding="utf-8") as f:
        json.dump(sop, f, ensure_ascii=False, indent=2)
    with open(os.path.join(output_dir, f"{title}_complex.md"), "w", encoding="utf-8") as f:
        f.write(complex_sop_to_markdown(sop))
    print(f"  已保存复杂SOP: {title}")

# ================== 主流程 ==================
def main():
    raw_dir = "input_files"
    output_dir = "output2"
    if not os.path.exists(raw_dir):
        print("请创建 input_files 文件夹并将所有 .txt 文件放入其中")
        return

    txt_files = [f for f in os.listdir(raw_dir) if f.endswith('.txt')]
    for file_name in txt_files:
        print(f"\n处理文件: {file_name}")
        with open(os.path.join(raw_dir, file_name), 'r', encoding='utf-8') as f:
            text = f.read()
        units = split_into_units(text, file_name)
        if not units:
            print(f"  未分割出任何单元，跳过文件 {file_name}")
            continue
        print(f"分割得到 {len(units)} 个单元")
        for idx, unit in enumerate(units):
            # 安全获取标题
            title_display = unit.get('title', '无标题')[:50]
            print(f"  抽取单元 {idx+1}: {title_display}...")
            # 只抽取复杂版
            sop = extract_complex_sop(unit.get('content'), unit.get('type'), file_name)
            if sop:
                base_name = os.path.splitext(file_name)[0]
                suffix = f"{base_name}_{idx+1:03d}"
                save_complex_sop(sop, output_dir, suffix)
            else:
                print(f"    复杂版抽取失败，跳过单元")

    print("\n全部完成！")

if __name__ == "__main__":
    main()