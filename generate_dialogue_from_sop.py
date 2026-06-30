#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
import random
import threading
from urllib import request, error
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ====================== 配置 ======================
USER_API_KEY = [
    "sk-Ph1f31wYAiS9KLdwP2i0PBAAZHmDjSKQiFDpmOUPEepuUaqQ",
    "sk-GqCfhDGSgRIJngw33xwoYgqKYob1DU11RxlJomtqoGxW77Gv",
    "sk-JlyVreJdzSs449K5I37ahlSNVE8TpR7qmifLE0T2DtRzzQdt",
    "sk-TNDJN3SVE6a3xQ8815hgOOIM37VBCF3hn9ROBZZgJENhcgSM",
    "sk-rwlAy6ZpcU7XmUybt4liZpWPmDomlSkT6HGmX2mdgk9Kpc3A",
    "sk-utfNouJ7l5lugvizt3JeuWUaodguPcDoNCZTnmENGlvDbC4O",
    "sk-WLtlSTgaj8Bl2QJGQ6JJBK2dQXNiGcUAc50PmBYoqgEtFMLr",
    "sk-zk5Dqz91epqjrXQvIUPjFJZ9eJhDnhvt28PoArhB4yg7RDM5",
    "sk-ZgzIaDVUOI9zZ4yNGyeCZUA08GvSgmGfbSkjil0RbmgyHvN3",
    "sk-zn1QORZYZfurB97Z7EMEw5hYvxx73Crx5CTJxfwIWJTzp5R5"
]   # 在这里填写

API_BASE_URL = os.getenv("AI_CENTOS_BASE_URL", "https://ai.centos.hk/v1")
API_KEY = USER_API_KEY or os.getenv("AI_CENTOS_API_KEY", "")
MODEL_NAME = os.getenv("AI_CENTOS_MODEL", "deepseek-v4-pro")
MOCK_MODE = False
MAX_TURNS = 10                     # 最大对话轮数
SLEEP_BETWEEN_CALLS = 0.5
MAX_RETRIES = 3
FINAL_TAG = "[FINAL_ANSWER]"
# 线程本地存储，用于保存每个线程自己的 OpenAI 客户端和模型名
_thread_local = threading.local()

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
    # 从线程本地存储获取 client 和 model_name
    client = getattr(_thread_local, 'client', None)
    model_name = getattr(_thread_local, 'model_name', MODEL_NAME)
    
    if client is not None:
        return client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    # 降级使用 urllib（如果 client 不存在）
    payload = json.dumps({
        "model": model_name,
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
    # 注意：不再需要传入 client 和 model_name，函数内部会从线程本地获取
    if MOCK_MODE:
        print("  [MOCK] 调用 LLM 返回占位内容")
        return "这是一个模拟的回复。请检查 API 配置。"

    for attempt in range(retries):
        try:
            response = create_chat_completion(messages, temperature=temperature, max_tokens=max_tokens)
            # 后续解析逻辑保持不变
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

            if isinstance(content, str) and content.strip():
                return content.strip()
            if reasoning:
                print(f"  [INFO] content 为空，忽略 reasoning 内容并重试 (长度 {len(reasoning)})")
            print(f"  API 返回空 content (finish_reason={finish_reason}, attempt {attempt+1})")
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

def extract_json_object(text: str) -> dict:
    """Extract a single JSON object from an LLM response."""
    text = (text or "").strip()
    if not text:
        raise ValueError("空响应")
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def route_expert_role(sop: dict, sop_id: str) -> dict:
    """Route one SOP to exactly one expert role using the chat API."""
    valid_roles = {role["role_id"]: role for role in EXPERT_ROLE_CARDS}
    diagnosis = sop.get("diagnosis_criteria", {})
    response_matrix = sop.get("response_matrix", {})
    route_payload = {
        "sop_id": sop_id,
        "title": sop.get("meta", {}).get("title", sop_id),
        "crop": sop.get("meta", {}).get("crop", "甘蔗"),
        "growth_stage": sop.get("meta", {}).get("growth_stage", ""),
        "symptoms": diagnosis.get("symptoms", [])[:8],
        "triggers": diagnosis.get("triggers", [])[:6],
        "reasoning_chain": diagnosis.get("reasoning_chain", ""),
        "key_entities": [
            entity.get("name", "")
            for entity in sop.get("missing_info_strategy", {}).get("key_entities", [])
            if entity.get("name")
        ],
        "scenario_summaries": [
            {
                "condition_checks": scenario.get("condition_checks", {}),
                "response_type": scenario.get("response_type", ""),
                "content": str(scenario.get("content", ""))[:500],
            }
            for scenario in response_matrix.get("scenarios", [])[:3]
        ],
    }
    role_payload = [
        {
            "role_id": role["role_id"],
            "archetype": role["archetype"],
            "expertise": role["expertise"],
        }
        for role in EXPERT_ROLE_CARDS
    ]
    system_prompt = """你是农业咨询数据生成流水线中的专家角色路由器。
你只能根据 SOP 内容选择一个最匹配的专家角色。
必须只输出一个 JSON 对象，不要输出解释、Markdown 或多余文本。
不要改写 SOP，不要生成咨询内容，不要使用规则说明。
"""
    user_prompt = f"""【可选专家角色】
{json.dumps(role_payload, ensure_ascii=False, indent=2)}

【待路由 SOP 摘要】
{json.dumps(route_payload, ensure_ascii=False, indent=2)}

输出格式必须严格为：
{{
  "expert_role_id": "E01_extension_officer 或 E02_plant_protection_specialist 或 E03_cultivation_manager 或 E04_disaster_response_advisor",
  "reason": "一句话说明选择依据"
}}
"""
    response = call_llm(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        temperature=0,
        max_tokens=500,
    )
    routed = extract_json_object(response)
    role_id = routed.get("expert_role_id")
    if role_id not in valid_roles:
        raise RuntimeError(f"专家角色API路由返回非法 role_id: {role_id!r}")
    return {
        "expert_role": valid_roles[role_id],
        "route": {
            "method": "api",
            "expert_role_id": role_id,
            "reason": routed.get("reason", ""),
        },
    }


def build_profile(sop: dict, sop_id: str, sample_idx: int = 0, attempt: int = 0) -> dict:
    """Build a lightweight role-driven profile for one synthetic dialogue."""
    farmer_role = random.choice(FARMER_ROLE_CARDS)
    title = sop.get("meta", {}).get("title", sop_id)
    source = sop.get("meta", {}).get("source", sop.get("source", "未知来源"))
    route_result = route_expert_role(sop, sop_id)
    expert_role = route_result["expert_role"]


    diagnosis = sop.get("diagnosis_criteria", {})

    return {
        "profile_id": f"{farmer_role['role_id']}__{expert_role['role_id']}",
        "sample_idx": sample_idx,
        "attempt": attempt,
        "farmer_role": farmer_role,
        "expert_role": expert_role,
        "expert_route": route_result["route"],
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


def generate_initial_question(sop: dict, profile: dict) -> str:
    crop = sop["meta"]["crop"]
    title = sop["meta"]["title"]
    symptoms = sop["diagnosis_criteria"].get("symptoms", [])[:3] or ["出现异常"]
    system_prompt = """你要扮演角色卡中的甘蔗种植户，向农技专家发起一次真实咨询。
要求：
1. 只输出农户第一句话或一小段话。
2. 像真实咨询：有观察、有担心、有不确定，不要一次性把信息说全。
3. 不要使用“老乡”“老哥”等固定称呼，也不要每次都用“专家您好我想咨询一下”。
4. 不要列字段，不要像问卷答案，不要复述SOP。
5. 角色只影响表达方式、关注点和信息披露习惯，不能创造SOP之外的农业事实。
"""
    user_prompt = f"""【角色与情境】
{profile_prompt_block(profile, "farmer")}

【作物与问题】
作物：{crop}
问题：{title}
可观察症状种子：{json.dumps(symptoms, ensure_ascii=False)}

    请按角色生成一个自然、不完整但具体的初始咨询问题。只输出农户发言。"""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    return call_llm(messages, temperature=0.7, max_tokens=500)

def simulate_farmer_response(prev_question: str, expert_reply: str, sop: dict, profile: dict, history: list) -> str:
    history_text = "\n".join(
        [f"农户：{turn.get('user', '')}\n专家：{turn.get('assistant', '')}" for turn in history if turn.get("assistant")]
    )
    system_prompt = """你继续扮演同一个甘蔗种植户。
要求：
1. 只回答专家刚问到的内容，可以自然补充一两个相关细节。
2. 不要为了让数据完整而主动补齐所有信息。
3. 如果角色不知道某个细节，可以说没注意、记不清、要回头看；不要猜。
4. 不要说“根据SOP”“按标准流程”等专家视角语言。
5. 不要使用“老乡”“老哥”等固定称呼。
"""
    user_prompt = f"""【角色与情境】
{profile_prompt_block(profile, "farmer")}

【已有对话】
{history_text}

【专家刚才说】
{expert_reply}

【农户上一轮发言】
{prev_question}

    请继续按同一角色自然回答专家刚问到的问题。只输出农户发言。"""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    return call_llm(messages, temperature=0.7, max_tokens=500)

def expert_reply(sop: dict, history: list, current_user_msg: str, profile: dict) -> str:
    """Generate the expert side of a natural diagnostic consultation."""
    # 这些信息点只作为诊断参考，不作为逐项填槽清单。
    key_entities = sop.get("missing_info_strategy", {}).get("key_entities", [])
    key_names = [e.get("name", "") for e in key_entities if e.get("name")]

    # 构建完整的对话历史（包括之前的专家回复和农民回复）
    full_history = []
    for turn in history:   # history 是 [{"user": "...", "assistant": "..."}, ...] 格式
        full_history.append(f"农民：{turn['user']}")
        if turn.get("assistant"):
            full_history.append(f"专家：{turn['assistant']}")
    # 加入最新农民消息（还没专家回复）
    full_history.append(f"农民：{current_user_msg}")
    history_text = "\n".join(full_history)

    system_prompt = f"""你扮演角色卡中的甘蔗农技专家，正在和真实农户多轮咨询。
要求：
1. SOP是事实参考和安全边界，不是模板答案，也不是逐项追问清单。
2. 先回应农户的具体担心，再判断当前信息是否足以给出建议。
3. 如果信息不足，只追问1-2个最影响判断或处理建议的问题，并简短说明为什么问。
4. 不要机械追问字段，不要连续列问卷，不要重复农户已经回答过的问题。
5. 建议必须落在SOP支持范围内；SOP不支持的具体药剂、剂量、时期、品种不要生成。
6. 不要使用“老乡”“老哥”“为了给您出最准的方子”等固定套话。
7. 当信息已经足够时，回复必须以 `{FINAL_TAG}` 开头，给出自然、可执行的最终方案；最终方案中不要再追问。
"""

    user_prompt = f"""【角色与情境】
{profile_prompt_block(profile, "expert")}

【SOP中可能影响判断的信息点（仅供参考，不要求逐项问完）】
{json.dumps(key_names, ensure_ascii=False)}

【完整的对话历史】
{history_text}
农民最新说的话：{current_user_msg}
【SOP完整内容（供你参考诊断条件、响应方案等）】
{json.dumps(sop, ensure_ascii=False, indent=2)}

请根据当前信息状态，决定回复：
- 如果还缺影响判断的关键信息，像真实专家一样自然追问1-2个问题。
- 如果信息已经足够，输出以 {FINAL_TAG} 开头的完整方案。
只输出回复内容。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    return call_llm(messages, temperature=0.3, max_tokens=1400)

def generate_one_dialogue(sop: dict, sop_id: str, sample_idx: int = 0, attempt: int = 0) -> dict:
    profile = build_profile(sop, sop_id, sample_idx=sample_idx, attempt=attempt)
    history = []
    first_q = generate_initial_question(sop, profile)
    if not first_q:
        raise RuntimeError("农户初始问题生成为空")
    history.append({"user": first_q, "assistant": ""})

    for turn_idx in range(1, MAX_TURNS + 1):
        expert_msg = expert_reply(sop, history[:-1], history[-1]["user"], profile)
        if not expert_msg:
            raise RuntimeError(f"第{turn_idx}轮专家回复为空")
        history[-1]["assistant"] = expert_msg
        time.sleep(SLEEP_BETWEEN_CALLS)

        # 检查是否结束：专家回复中包含 [FINAL_ANSWER] 即视为给出最终方案
        if FINAL_TAG in expert_msg:
            print(f"    第{turn_idx}轮专家给出最终方案，对话结束。")
            break

        # 如果专家没有追问（没有问句），候选样本不完整，交给上层失败处理
        if "?" not in expert_msg and "？" not in expert_msg:
            raise RuntimeError(f"第{turn_idx}轮专家未追问且未给出最终方案")

        # 农民回答追问
        farmer_answer = simulate_farmer_response(history[-1]["user"], expert_msg, sop, profile, history)
        if not farmer_answer:
            raise RuntimeError(f"第{turn_idx}轮农户回复为空")
        history.append({"user": farmer_answer, "assistant": ""})
        time.sleep(SLEEP_BETWEEN_CALLS)

    if FINAL_TAG not in history[-1]["assistant"]:
        raise RuntimeError(f"达到最大轮数 {MAX_TURNS} 后仍未给出最终方案")
    return {
        "schema_version": "dialogue_v1",
        "sop_id": sop_id,
        "profile": profile,
        "dialog": history,
    }

def main():
    input_dir = "output2"
    output_dir = "dialogues_role_100_2"
    os.makedirs(output_dir, exist_ok=True)
    json_files = [f for f in os.listdir(input_dir) if f.endswith("_complex.json")]
    if not json_files:
        print(f"在 {input_dir} 中没有找到任何 _complex.json 文件。")
        return

    num_dialogues_per_sop = 3   # 每个 SOP 生成 3 条对话
    num_keys = len(USER_API_KEY)
    print(f"找到 {len(json_files)} 个 SOP 文件，每个生成 {num_dialogues_per_sop} 条对话")
    print(f"使用 {num_keys} 个 API Key 并发处理")

    # 全局统计（线程安全）
    stats_lock = threading.Lock()
    success_count = 0
    fail_count = 0
    failures = []

    def process_one_file(json_file, api_key, key_index):
        """处理单个 SOP 文件的所有对话（串行生成 3 条）"""
        nonlocal success_count, fail_count, failures
        file_path = os.path.join(input_dir, json_file)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                sop = json.load(f)
        except Exception as e:
            with stats_lock:
                fail_count += 1
                failures.append({
                    "file": json_file,
                    "sop_id": "UNKNOWN",
                    "reason": f"读取JSON失败: {str(e)}"
                })
            print(f"[Key{key_index+1}] ✗ 读取失败: {json_file}")
            return

        sop_id = sop.get("meta", {}).get("title", json_file.replace("_complex.json", ""))
        
        # 为这个线程创建独立的 OpenAI 客户端
        from openai import OpenAI
        client = OpenAI(base_url=API_BASE_URL, api_key=api_key, default_headers={"X-Failover-Enabled": "true"})
        _thread_local.client = client
        _thread_local.model_name = MODEL_NAME
        # 生成该 SOP 的所有对话（串行，避免输出文件冲突）
        for i in range(num_dialogues_per_sop):
            try:
                dialogue = generate_one_dialogue(sop, sop_id, sample_idx=i)
                out_file = os.path.join(output_dir, f"{sop_id.replace('/', '_')}_dialogue.jsonl")
                with open(out_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(dialogue, ensure_ascii=False) + "\n")
                with stats_lock:
                    success_count += 1
                print(f"[Key{key_index+1}] ✓ {json_file} 第{i+1}条对话生成成功")
            except Exception as e:
                with stats_lock:
                    fail_count += 1
                    failures.append({
                        "file": json_file,
                        "sop_id": sop_id,
                        "reason": f"生成对话时异常: {str(e)}"
                    })
                print(f"[Key{key_index+1}] ✗ {json_file} 第{i+1}条对话失败: {e}")
            time.sleep(1)  # 避免过频请求

    # 使用线程池并发处理不同的 SOP 文件
    with ThreadPoolExecutor(max_workers=len(USER_API_KEY)) as executor:
        futures = []
        for idx, json_file in enumerate(json_files):
            api_key = USER_API_KEY[idx % num_keys]   # 轮询分配 Key
            futures.append(executor.submit(process_one_file, json_file, api_key, idx % num_keys))
        
        # 等待所有任务完成
        for future in as_completed(futures):
            future.result()  # 如果有异常会在这里抛出

    # 打印统计
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