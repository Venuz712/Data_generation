#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
import random
from urllib import request, error

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ====================== 配置 ======================
API_BASE_URL = os.getenv("AI_CENTOS_BASE_URL", "https://ai.centos.hk/v1")
API_KEY = os.getenv("AI_CENTOS_API_KEY", "")
MODEL_NAME = os.getenv("AI_CENTOS_MODEL", "deepseek-v4-pro")
MOCK_MODE = False
MAX_TURNS = 10                     # 最大对话轮数
SLEEP_BETWEEN_CALLS = 0.5
MAX_RETRIES = 3

FARMER_ROLE_CARDS = [
    {
        "role_id": "F01_new_returning_grower",
        "archetype": "新手返乡承包户",
        "experience_level": "novice",
        "production_context": "刚接手家里或亲戚的甘蔗地，种植经验少",
        "primary_goal": "先判断问题严重不严重，避免耽误农时",
        "decision_pressure": "担心自己判断错，描述会比较零散",
        "communication_style": "口语、直接、会承认不懂专业名词",
        "opening_bias": "先讲看到的异常和自己的担心",
        "detail_behavior": "不会一次性说完整背景，被问到才补充",
        "avoid": ["老乡", "老哥", "固定寒暄", "专家式诊断"],
    },
    {
        "role_id": "F02_practical_smallholder",
        "archetype": "经验型小农",
        "experience_level": "practical",
        "production_context": "多年种甘蔗，靠经验管理小块地",
        "primary_goal": "确认自己的经验判断是否靠谱",
        "decision_pressure": "想尽快处理，但不喜欢复杂方案",
        "communication_style": "凭经验说话，能说苗期、宿根、培土等常见词",
        "opening_bias": "先说自己以往见过的类似情况",
        "detail_behavior": "会跳过自己觉得是常识的背景，需要专家追问才说",
        "avoid": ["老乡", "老哥", "夸张方言", "逐项报表"],
    },
    {
        "role_id": "F03_coop_manager",
        "archetype": "合作社负责人",
        "experience_level": "advanced",
        "production_context": "负责多户或连片甘蔗地的统一管理",
        "primary_goal": "拿到能批量执行的处理建议",
        "decision_pressure": "关心成本、人员安排和统一作业窗口",
        "communication_style": "简洁、偏管理口吻，会提面积和执行效率",
        "opening_bias": "先讲影响范围、处理成本或是否需要统防统治",
        "detail_behavior": "信息相对完整，但不会主动说所有细节",
        "avoid": ["老乡", "老哥", "过度乡土化", "营销口吻"],
    },
    {
        "role_id": "F04_cost_sensitive_grower",
        "archetype": "成本敏感散户",
        "experience_level": "practical",
        "production_context": "种植面积不大，投入预算紧",
        "primary_goal": "找到便宜、够用、风险不大的办法",
        "decision_pressure": "担心药肥成本和人工成本过高",
        "communication_style": "先问有没有省钱办法，对复杂方案会追问必要性",
        "opening_bias": "先讲问题和成本顾虑",
        "detail_behavior": "资源限制常在专家建议后才补充",
        "avoid": ["老乡", "老哥", "固定寒暄", "自动接受所有建议"],
    },
    {
        "role_id": "F05_disaster_recovery_grower",
        "archetype": "灾后恢复户",
        "experience_level": "mixed",
        "production_context": "刚经历干旱、涝害、台风或霜冻影响",
        "primary_goal": "抢时间补救，减少损失",
        "decision_pressure": "天气窗口紧，语气更急",
        "communication_style": "急切但不专业，会描述现场混乱情况",
        "opening_bias": "先讲灾害经过和最明显损失",
        "detail_behavior": "会遗漏用药史、品种等不在眼前的信息",
        "avoid": ["老乡", "老哥", "夸张戏剧化", "编造精确数据"],
    },
    {
        "role_id": "F06_proxy_field_keeper",
        "archetype": "代管田块人员",
        "experience_level": "low_to_mixed",
        "production_context": "替亲戚、老板或合作社看田，掌握二手信息",
        "primary_goal": "把现场看到的问题问清楚，再回去处理",
        "decision_pressure": "很多历史信息不确定",
        "communication_style": "经常说大概、听说、没亲眼看完整",
        "opening_bias": "先讲自己刚看到的异常",
        "detail_behavior": "被问到历史管理时可能回答不确定",
        "avoid": ["老乡", "老哥", "专家式术语", "假装全知道"],
    },
]

EXPERT_ROLE_CARDS = [
    {
        "role_id": "E01_extension_officer",
        "archetype": "基层农技推广员",
        "expertise": "综合农技指导",
        "communication_style": "务实、通俗、少套话",
        "question_style": "只问会影响判断和处理建议的上下文",
        "recommendation_style": "先讲轻重缓急，再给可执行步骤",
        "avoid": ["老乡", "老哥", "为了给您出最准的方子", "问卷式连问"],
    },
    {
        "role_id": "E02_plant_protection_specialist",
        "archetype": "植保专家",
        "expertise": "病虫害识别与安全防治",
        "communication_style": "专业但不绕，重视诊断边界",
        "question_style": "围绕症状部位、发生程度、虫体/病斑特征自然追问",
        "recommendation_style": "强调药剂和操作必须有依据，不确定就建议拍照或现场确认",
        "avoid": ["老乡", "老哥", "保证治愈", "SOP外药剂剂量"],
    },
    {
        "role_id": "E03_cultivation_manager",
        "archetype": "栽培管理专家",
        "expertise": "水肥、培土、苗情和田间管理",
        "communication_style": "条理清楚，偏作业安排",
        "question_style": "围绕生育期、田间条件和最近操作追问",
        "recommendation_style": "把建议转成当天和后续几天能做的管理动作",
        "avoid": ["老乡", "老哥", "机械填槽", "泛泛而谈"],
    },
    {
        "role_id": "E04_disaster_response_advisor",
        "archetype": "灾害应急指导员",
        "expertise": "干旱、涝害、台风、霜冻应对",
        "communication_style": "冷静、直接、重视时间窗口",
        "question_style": "先区分灾害程度、恢复可能性和马上能做的事",
        "recommendation_style": "优先给安全、保守、可立即执行的补救建议",
        "avoid": ["老乡", "老哥", "拖延判断", "不说明风险"],
    },
]

if not MOCK_MODE and not API_KEY:
    raise RuntimeError("请先设置环境变量 AI_CENTOS_API_KEY")

if not MOCK_MODE and OpenAI is not None:
    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY, default_headers={"X-Failover-Enabled": "true"})
else:
    client = None


def create_chat_completion(messages, temperature=0.5, max_tokens=800):
    if client is not None:
        return client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = request.Request(
        f"{API_BASE_URL.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "sop-dialogue-generator/role-test",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc

# ====================== 安全的 API 调用函数 ======================
def call_llm(messages, temperature=0.5, max_tokens=800, retries=MAX_RETRIES):
    """统一的 API 调用函数，支持 Qwen 推理模型的 reasoning 回退"""
    if MOCK_MODE:
        print("  [MOCK] 调用 LLM 返回占位内容")
        return "这是一个模拟的回复。请检查 API 配置。"

    for attempt in range(retries):
        try:
            response = create_chat_completion(messages, temperature=temperature, max_tokens=max_tokens)
            if isinstance(response, dict):
                message = response.get("choices", [{}])[0].get("message", {})
                content = message.get("content")
                reasoning = message.get("reasoning") or message.get("reasoning_content")
                finish_reason = response.get("choices", [{}])[0].get("finish_reason")
            else:
                message = response.choices[0].message
                content = message.content
                reasoning = getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None)
                finish_reason = response.choices[0].finish_reason

            # 如果正常返回 content
            if isinstance(content, str) and content.strip():
                return content.strip()

            if reasoning:
                print(f"  [INFO] content 为空，忽略 reasoning 内容并重试 (长度 {len(reasoning)})")

            # 既无 content 也无 reasoning
            print(f"  API 返回空 content 且无 reasoning (finish_reason={finish_reason}, attempt {attempt+1})")
            if attempt < retries - 1:
                time.sleep(2)
            continue

        except Exception as e:
            print(f"  API 调用失败 (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2)
            else:
                print("  达到最大重试次数，返回空字符串")
                return ""
    return ""


def build_profile(sop: dict, sop_id: str, sample_idx: int = 0, attempt: int = 0) -> dict:
    """Build a lightweight role-driven profile for one synthetic dialogue."""
    farmer_role = random.choice(FARMER_ROLE_CARDS)
    title = sop.get("meta", {}).get("title", sop_id)
    source = sop.get("meta", {}).get("source", sop.get("source", "未知来源"))

    if any(word in title for word in ["灾", "旱", "涝", "台风", "霜冻", "倒伏"]):
        expert_pool = [r for r in EXPERT_ROLE_CARDS if r["role_id"] == "E04_disaster_response_advisor"]
    elif any(word in title for word in ["病", "虫", "螟", "蚜", "蝉", "蛾", "龟", "虱"]):
        expert_pool = [r for r in EXPERT_ROLE_CARDS if r["role_id"] == "E02_plant_protection_specialist"]
    elif any(word in title for word in ["培土", "追肥", "定植", "补苗", "栽培", "水", "养分"]):
        expert_pool = [r for r in EXPERT_ROLE_CARDS if r["role_id"] == "E03_cultivation_manager"]
    else:
        expert_pool = EXPERT_ROLE_CARDS

    expert_role = random.choice(expert_pool or EXPERT_ROLE_CARDS)
    diagnosis = sop.get("diagnosis_criteria", {})

    return {
        "profile_id": f"{farmer_role['role_id']}__{expert_role['role_id']}",
        "sample_idx": sample_idx,
        "attempt": attempt,
        "farmer_role": farmer_role,
        "expert_role": expert_role,
        "situation": {
            "crop": sop.get("meta", {}).get("crop", "甘蔗"),
            "problem_title": title,
            "growth_stage": sop.get("meta", {}).get("growth_stage", "未提及"),
            "source": source,
            "symptom_seeds": diagnosis.get("symptoms", [])[:4],
            "trigger_seeds": diagnosis.get("triggers", [])[:3],
            "generation_note": "情境只用于保持对话一致，不是逐项追问清单。",
        },
    }


def profile_prompt_block(profile: dict, audience: str) -> str:
    """Render role profile as compact prompt text."""
    farmer_role = profile.get("farmer_role", {})
    expert_role = profile.get("expert_role", {})
    situation = profile.get("situation", {})

    if audience == "farmer":
        payload = {
            "farmer_role": farmer_role,
            "situation": situation,
            "role_boundary": "角色只影响语气、关注点和信息披露习惯；不要创造事实，不要复述SOP。",
        }
    else:
        payload = {
            "farmer_role": farmer_role,
            "expert_role": expert_role,
            "situation": situation,
            "role_boundary": "角色只影响问法和表达；SOP是事实参考，不是模板答案或逐项追问清单。",
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def generate_initial_question(sop: dict) -> str:
    crop = sop["meta"]["crop"]
    title = sop["meta"]["title"]
    symptoms = sop["diagnosis_criteria"]["symptoms"][0] if sop["diagnosis_criteria"].get("symptoms") else "出现异常"
    system_prompt = "你是一位种植甘蔗的农民，提问要口语化、自然，并且故意缺少一些关键信息。"
    user_prompt = f"""背景：作物{crop}，问题{title}，典型症状{symptoms}。请生成一个口语化问题，不要一次性给出所有细节。只输出问题。"""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    return call_llm(messages, temperature=0.7, max_tokens=300)

def simulate_farmer_response(prev_question: str, expert_reply: str, sop: dict) -> str:
    system_prompt = "你是一位农民，正在和专家对话。请针对专家的提问，简短、口语化地回答，只提供专家问到的信息。"
    user_prompt = f"""专家刚才说：{expert_reply}\n农民上一轮问：{prev_question}\n请你作为农民回答专家的提问："""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    return call_llm(messages, temperature=0.7, max_tokens=300)

def expert_reply(sop: dict, history: list, current_user_msg: str) -> str:
    """如果关键信息未齐，只追问；齐了则输出 [FINAL_ANSWER] + 完整方案"""
    # 提取必须收集的关键信息字段
    key_entities = sop.get("missing_info_strategy", {}).get("key_entities", [])
    key_names = [e["name"] for e in key_entities]

    # 构建完整的对话历史（包括之前的专家回复和农民回复）
    full_history = []
    for turn in history:   # history 是 [{"user": "...", "assistant": "..."}, ...] 格式
        full_history.append(f"农民：{turn['user']}")
        if turn.get("assistant"):
            full_history.append(f"专家：{turn['assistant']}")
    # 加入最新农民消息（还没专家回复）
    full_history.append(f"农民：{current_user_msg}")
    history_text = "\n".join(full_history)

    system_prompt = """你是一位严谨的农业专家。你必须严格遵循以下工作流程：
1. 你的目标是根据SOP收集所有【必须知道的关键信息】。在收集齐之前，**绝对不能给出任何操作建议**（如用药、施肥等）。
2. 先分析对话历史，提取农民已经提供的所有信息（例如：症状部位、发生时间、天气、作物品种等）。
3. 每次只追问1-2个当前最缺失的信息，追问要口语化、具体。
4. 当你已经收集到所有关键信息后，你的回复必须以 `[FINAL_ANSWER]` 开头，然后给出完整、可执行的方案，该方案中不能有问句。
5. 不要使用问句之外的语句来提前给出方案。
"""

    user_prompt = f"""【SOP中必须收集的关键信息列表】{key_names}

【完整的对话历史】
{history_text}
农民最新说的话：{current_user_msg}
【SOP完整内容（供你参考诊断条件、响应方案等）】
{json.dumps(sop, ensure_ascii=False, indent=2)}

请根据当前信息状态，决定回复：
- 如果还缺信息，只输出追问（不要给方案）。
- 如果所有关键信息已齐，输出以 [FINAL_ANSWER] 开头的完整方案。
只输出回复内容。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    return call_llm(messages, temperature=0.3, max_tokens=600)

def generate_one_dialogue(sop: dict, sop_id: str) -> dict:
    history = []
    first_q = generate_initial_question(sop)
    if not first_q:
        first_q = "老师，我种的甘蔗有点问题，您帮我看看。"
    history.append({"user": first_q, "assistant": ""})

    for turn_idx in range(1, MAX_TURNS + 1):
        expert_msg = expert_reply(sop, history[:-1], history[-1]["user"])
        if not expert_msg:
            expert_msg = "抱歉，我无法确定。请再描述一下症状。"
        history[-1]["assistant"] = expert_msg
        time.sleep(SLEEP_BETWEEN_CALLS)

        # 检查是否结束：专家回复中包含 [FINAL_ANSWER] 即视为给出最终方案
        if "[FINAL_ANSWER]" in expert_msg:
            print(f"    第{turn_idx}轮专家给出最终方案，对话结束。")
            break

        # 如果专家没有追问（没有问句），可能是模型出错，强制结束
        if "?" not in expert_msg and "？" not in expert_msg:
            print(f"    第{turn_idx}轮专家未追问，视为对话结束。")
            break

        # 农民回答追问
        farmer_answer = simulate_farmer_response(history[-1]["user"], expert_msg, sop)
        if not farmer_answer:
            farmer_answer = "好的，我再看看。"
        history.append({"user": farmer_answer, "assistant": ""})
        time.sleep(SLEEP_BETWEEN_CALLS)

    # 如果最后一轮没有收到最终方案（即最终对话没有 [FINAL_ANSWER]），补一个默认结束语
    if "[FINAL_ANSWER]" not in history[-1]["assistant"]:
        history[-1]["assistant"] += "\n[感谢咨询，请参考以上建议。]"
    return {"sop_id": sop_id, "dialog": history}

def main():
    input_dir = "output2"
    output_dir = "dialogues2"
    os.makedirs(output_dir, exist_ok=True)
    json_files = [f for f in os.listdir(input_dir) if f.endswith("_complex.json")]
    if not json_files:
        print(f"在 {input_dir} 中没有找到任何 _complex.json 文件。")
        return

    print(f"找到 {len(json_files)} 个 SOP 文件，开始生成多轮对话...")

    # ---------- 统计变量 ----------
    success_count = 0          # 成功生成的对话条数
    fail_count = 0             # 失败的对话条数
    failures = []              # 列表元素: {"file": "xxx.json", "sop_id": "xxx", "reason": "错误信息"}

    for json_file in json_files:
        file_path = os.path.join(input_dir, json_file)
        print(f"\n处理: {json_file}")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                sop = json.load(f)
        except Exception as e:
            error_msg = f"读取JSON失败: {str(e)}"
            print(f"  {error_msg}，跳过")
            fail_count += 1
            failures.append({
                "file": json_file,
                "sop_id": "UNKNOWN",
                "reason": error_msg
            })
            continue

        sop_id = sop.get("meta", {}).get("title", json_file.replace("_complex.json", ""))
        num_dialogues = 1   # 每个 SOP 生成1条对话，可调整

        for i in range(num_dialogues):
            print(f"  生成第 {i+1} 条对话...")
            try:
                dialogue = generate_one_dialogue(sop, sop_id)
                out_file = os.path.join(output_dir, f"{sop_id.replace('/', '_')}_dialogue.jsonl")
                with open(out_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(dialogue, ensure_ascii=False) + "\n")
                print(f"    已追加到 {out_file}")
                success_count += 1
            except Exception as e:
                error_msg = f"生成对话时异常: {str(e)}"
                print(f"    {error_msg}")
                fail_count += 1
                failures.append({
                    "file": json_file,
                    "sop_id": sop_id,
                    "reason": error_msg
                })
            time.sleep(1)

    # ---------- 打印统计结果 ----------
    print("\n" + "="*50)
    print("生成统计报告")
    print("="*50)
    print(f"总尝试生成对话数: {success_count + fail_count}")
    print(f"✅ 成功: {success_count}")
    print(f"❌ 失败: {fail_count}")

    if failures:
        print("\n失败详情:")
        for idx, fail in enumerate(failures, 1):
            print(f"  {idx}. 文件: {fail['file']} | SOP标题: {fail['sop_id']}")
            print(f"     原因: {fail['reason']}")
    else:
        print("\n所有对话均生成成功！")

    print(f"\n对话文件保存在: {output_dir}/")

if __name__ == "__main__":
    main()