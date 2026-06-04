#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
import random
import re
import statistics
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter, defaultdict
from pathlib import Path
from urllib import error, request

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ====================== 配置 ======================
API_BASE_URL = os.getenv("AI_CENTOS_BASE_URL", "https://ai.centos.hk/v1")
API_KEY = os.getenv("AI_CENTOS_API_KEY", "")
API_KEYS_RAW = os.getenv("AI_CENTOS_API_KEYS", "")
MODEL_NAME = os.getenv("AI_CENTOS_MODEL", "deepseek-v4-pro")
MOCK_MODE = False
DEFAULT_MAX_TURNS = 6
DEFAULT_SLEEP_BETWEEN_CALLS = 0.5
MAX_RETRIES = 3
JSON_CONTENT_RETRIES = 2
API_TIMING_LOG_PATH = None
API_CALL_COUNTER = 0
API_KEY_CURSOR = 0
API_KEY_CURSOR_LOCK = threading.Lock()
API_KEY_LOCKS_LOCK = threading.Lock()
API_KEY_LOCKS = {}
CLIENTS_LOCK = threading.Lock()
FILE_WRITE_LOCK = threading.Lock()
NON_RETRYABLE_API_ERROR_MARKERS = (
    "model_not_found",
    "No available channel for model",
)
FORBIDDEN_PHRASES = [
    "[FINAL_ANSWER]",
    "FINAL_ANSWER",
    "老乡",
    "老哥",
    "为了给您出最准",
    "专家您好",
    "根据SOP",
    "按SOP",
    "根据 SOP",
    "按 SOP",
]
ASK_REPLY_TYPE = "ask"
FINAL_REPLY_TYPE = "final"
VALID_REPLY_TYPES = {ASK_REPLY_TYPE, FINAL_REPLY_TYPE}

clients_by_key_index = {}

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


def parse_api_keys() -> list[str]:
    raw_keys = []
    if API_KEYS_RAW.strip():
        raw_keys.extend(re.split(r"[\s,;]+", API_KEYS_RAW.strip()))
    elif API_KEY.strip():
        raw_keys.append(API_KEY.strip())
    return [key for key in raw_keys if key]


def next_api_key() -> tuple[str, int]:
    """Return the next API key and its zero-based rotation index."""
    global API_KEY_CURSOR
    keys = parse_api_keys()
    if not keys:
        raise RuntimeError("请先设置环境变量 AI_CENTOS_API_KEYS 或 AI_CENTOS_API_KEY")
    with API_KEY_CURSOR_LOCK:
        index = API_KEY_CURSOR % len(keys)
        API_KEY_CURSOR += 1
    return keys[index], index


def get_api_key_lock(key_index: int) -> threading.Lock:
    with API_KEY_LOCKS_LOCK:
        if key_index not in API_KEY_LOCKS:
            API_KEY_LOCKS[key_index] = threading.Lock()
        return API_KEY_LOCKS[key_index]


def lease_api_key() -> tuple[str, int, threading.Lock]:
    """Lease the next idle API key; block only when every key is currently busy."""
    global API_KEY_CURSOR
    keys = parse_api_keys()
    if not keys:
        raise RuntimeError("请先设置环境变量 AI_CENTOS_API_KEYS 或 AI_CENTOS_API_KEY")

    with API_KEY_CURSOR_LOCK:
        for _ in range(len(keys)):
            index = API_KEY_CURSOR % len(keys)
            API_KEY_CURSOR += 1
            key_lock = get_api_key_lock(index)
            if key_lock.acquire(blocking=False):
                return keys[index], index, key_lock

        index = API_KEY_CURSOR % len(keys)
        API_KEY_CURSOR += 1

    key_lock = get_api_key_lock(index)
    key_lock.acquire()
    return keys[index], index, key_lock


def get_client(api_key: str, key_index: int):
    """Create optional OpenAI SDK clients lazily so CLI inspection works without a key."""
    if MOCK_MODE:
        return None
    with CLIENTS_LOCK:
        if OpenAI is not None and key_index not in clients_by_key_index:
            clients_by_key_index[key_index] = OpenAI(
                base_url=API_BASE_URL,
                api_key=api_key,
                default_headers={"X-Failover-Enabled": "true"},
            )
        return clients_by_key_index.get(key_index)


def extract_response_meta(response):
    if isinstance(response, dict):
        choice = response.get("choices", [{}])[0]
        usage = response.get("usage", {}) or {}
        return {
            "finish_reason": choice.get("finish_reason"),
            "usage": usage,
        }

    choice = response.choices[0]
    usage_obj = getattr(response, "usage", None)
    usage = {}
    if usage_obj is not None:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(usage_obj, key, None)
            if value is not None:
                usage[key] = value
    return {
        "finish_reason": choice.finish_reason,
        "usage": usage,
    }


def log_api_timing(event: dict):
    if API_TIMING_LOG_PATH is None:
        return
    payload = {
        "ts": dt.datetime.now().isoformat(timespec="milliseconds"),
        **event,
    }
    append_jsonl(API_TIMING_LOG_PATH, payload)


def create_chat_completion(messages, temperature=0.5, max_tokens=800, api_key=None, api_key_index=None):
    if api_key is None or api_key_index is None:
        api_key, api_key_index = next_api_key()
    active_client = get_client(api_key, api_key_index)
    if active_client is not None:
        return active_client.chat.completions.create(
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
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "sop-dialogue-generator/run-based",
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
def call_llm(messages, temperature=0.5, max_tokens=800, retries=MAX_RETRIES, label="llm_call"):
    """统一的 API 调用函数；失败时返回空字符串，由上层显式失败处理。"""
    global API_CALL_COUNTER
    if MOCK_MODE:
        print("  [MOCK] 调用 LLM 返回占位内容")
        return "这是一个模拟的回复。请检查 API 配置。"

    for attempt in range(retries):
        api_key, api_key_index, api_key_lock = lease_api_key()
        with API_KEY_CURSOR_LOCK:
            call_id = API_CALL_COUNTER
            API_CALL_COUNTER += 1
        start_time = time.monotonic()
        try:
            response = create_chat_completion(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=api_key,
                api_key_index=api_key_index,
            )
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            response_meta = extract_response_meta(response)
            if isinstance(response, dict):
                choice = response.get("choices", [{}])[0]
                message = choice.get("message", {})
                content = message.get("content")
                reasoning = message.get("reasoning") or message.get("reasoning_content")
                finish_reason = choice.get("finish_reason")
            else:
                choice = response.choices[0]
                message = choice.message
                content = message.content
                reasoning = getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None)
                finish_reason = choice.finish_reason

            if isinstance(content, str) and content.strip():
                log_api_timing({
                    "call_id": call_id,
                    "label": label,
                    "attempt": attempt + 1,
                    "api_key_index": api_key_index,
                    "latency_ms": elapsed_ms,
                    "success": True,
                    "finish_reason": response_meta.get("finish_reason"),
                    "content_chars": len(content.strip()),
                    "reasoning_chars": len(reasoning or ""),
                    "usage": response_meta.get("usage", {}),
                })
                return content.strip()

            if reasoning:
                print(f"  [INFO] content 为空，忽略 reasoning 内容并重试 (长度 {len(reasoning)})")

            log_api_timing({
                "call_id": call_id,
                "label": label,
                "attempt": attempt + 1,
                "api_key_index": api_key_index,
                "latency_ms": elapsed_ms,
                "success": False,
                "finish_reason": finish_reason,
                "content_chars": 0,
                "reasoning_chars": len(reasoning or ""),
                "error": "empty_content",
                "usage": response_meta.get("usage", {}),
            })
            print(f"  API 返回空 content 且无 reasoning (finish_reason={finish_reason}, attempt {attempt + 1})")
            if attempt < retries - 1:
                time.sleep(2)
            continue

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            error_message = str(exc)
            non_retryable = any(marker in error_message for marker in NON_RETRYABLE_API_ERROR_MARKERS)
            log_api_timing({
                "call_id": call_id,
                "label": label,
                "attempt": attempt + 1,
                "api_key_index": api_key_index,
                "latency_ms": elapsed_ms,
                "success": False,
                "error": type(exc).__name__,
                "error_message": error_message[:500],
                "non_retryable": non_retryable,
            })
            print(f"  API 调用失败 (attempt {attempt + 1}/{retries}): {exc}")
            if non_retryable:
                if attempt < retries - 1:
                    continue
                raise RuntimeError(error_message)
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return ""
        finally:
            api_key_lock.release()
    return ""


def extract_json_object(text: str) -> dict:
    """Extract a single JSON object from an LLM response."""
    text = (text or "").strip()
    if not text:
        raise ValueError("空响应")

    code_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if code_match:
        text = code_match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def call_json_llm(messages, temperature=0.3, max_tokens=1000, label="JSON") -> dict:
    """Call the LLM for JSON content; invalid JSON is retried, never repaired into a sample."""
    last_error = ""
    repair_messages = list(messages)
    for attempt in range(JSON_CONTENT_RETRIES):
        response = call_llm(repair_messages, temperature=temperature, max_tokens=max_tokens, label=label)
        try:
            return extract_json_object(response)
        except Exception as exc:
            last_error = str(exc)
            repair_messages = list(messages) + [
                {
                    "role": "user",
                    "content": (
                        f"上一次输出无法解析为合法 JSON，错误是：{last_error}。\n"
                        "请重新输出一个合法 JSON 对象。不要输出解释、Markdown、换行列表或 JSON 之外的文字。"
                    ),
                }
            ]
    raise RuntimeError(f"{label} JSON解析失败: {last_error}")


def clean_text(text: str) -> str:
    return (text or "").strip()


def normalize_for_similarity(text: str) -> str:
    text = re.sub(r"\s+", "", text or "")
    text = re.sub(r"[，。！？、；：,.!?;:\"'“”‘’（）()【】\[\]{}<>《》]", "", text)
    return text


def text_similarity(a: str, b: str) -> float:
    a_norm = normalize_for_similarity(a)
    b_norm = normalize_for_similarity(b)
    if not a_norm or not b_norm:
        return 0.0
    return difflib.SequenceMatcher(None, a_norm, b_norm).ratio()


def contains_forbidden(text: str) -> list[str]:
    return [phrase for phrase in FORBIDDEN_PHRASES if phrase in (text or "")]


def get_code_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def append_jsonl(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with FILE_WRITE_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


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
    routed = call_json_llm(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        temperature=0,
        max_tokens=1200,
        label="专家角色路由",
    )
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


def sop_summary_for_prompt(sop: dict, sop_id: str) -> dict:
    diagnosis = sop.get("diagnosis_criteria", {})
    response_matrix = sop.get("response_matrix", {})
    return {
        "sop_id": sop_id,
        "title": sop.get("meta", {}).get("title", sop_id),
        "crop": sop.get("meta", {}).get("crop", "甘蔗"),
        "growth_stage": sop.get("meta", {}).get("growth_stage", ""),
        "symptoms": diagnosis.get("symptoms", [])[:8],
        "triggers": diagnosis.get("triggers", [])[:6],
        "key_entities": [
            entity.get("name", "")
            for entity in sop.get("missing_info_strategy", {}).get("key_entities", [])
            if entity.get("name")
        ],
        "response_summaries": [
            {
                "condition_checks": scenario.get("condition_checks", {}),
                "response_type": scenario.get("response_type", ""),
                "content": str(scenario.get("content", ""))[:600],
            }
            for scenario in response_matrix.get("scenarios", [])[:3]
        ],
    }


def generate_scenario_card(sop: dict, sop_id: str, sample_idx: int, attempt: int, farmer_role: dict) -> dict:
    """Generate one source-bounded scenario card for one dialogue."""
    system_prompt = """你是农业咨询数据生成流水线中的场景设计器。
你只能基于给定 SOP 摘要设计农户咨询场景。
场景只改变表达方式、信息缺口、约束和咨询入口，不得添加 SOP 外的农业事实、药剂、剂量、时期或地区适用性。
必须只输出一个 JSON 对象，不要输出 Markdown 或多余文本。
"""
    user_prompt = f"""【SOP 摘要】
{json.dumps(sop_summary_for_prompt(sop, sop_id), ensure_ascii=False, indent=2)}

【农户角色】
{json.dumps(farmer_role, ensure_ascii=False, indent=2)}

【样本编号】
sample_idx={sample_idx}, attempt={attempt}

请输出一个场景卡。所有字段都必须是单行短字符串，不要使用数组、换行列表或 Markdown。
格式严格如下：
{{
  "problem_entry": "症状诊断|预防管理|操作执行|灾后补救|效果不明显|误区纠正|成本约束|信息不确定",
  "opening_angle": "农户第一句话应从哪个真实担心切入",
  "known_context": "农户一开始可以知道并说出的1-3个事实，用分号隔开",
  "hidden_or_missing_info": "需要专家自然追问或农户后续才补充的信息，用分号隔开",
  "constraint": "缺药/缺工/预算/天气/临近采收/信息不确定等约束，没有则写无",
  "dialogue_goal": "专家最终应解决的咨询目标",
  "do_not_add": "不要添加 SOP 外药剂、剂量、时期、品种或地区适用性"
}}
"""
    scenario = call_json_llm(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        temperature=0.75,
        max_tokens=1400,
        label="场景卡",
    )
    required = ["problem_entry", "opening_angle", "known_context", "hidden_or_missing_info", "constraint", "dialogue_goal"]
    missing = [field for field in required if not scenario.get(field)]
    if missing:
        raise RuntimeError(f"场景卡缺少字段: {', '.join(missing)}")
    scenario["scenario_id"] = f"sc_{sample_idx:04d}_attempt_{attempt}"
    scenario["farmer_role_id"] = farmer_role["role_id"]
    return scenario


def build_profile(
    sop: dict,
    sop_id: str,
    sample_idx: int,
    attempt: int,
    farmer_role: dict,
    route_result: dict,
    scenario: dict,
) -> dict:
    """Build a lightweight role-driven profile for one synthetic dialogue."""
    title = sop.get("meta", {}).get("title", sop_id)
    source = sop.get("meta", {}).get("source", sop.get("source", "未知来源"))
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
            "scenario": scenario,
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
5. 角色和场景只影响表达方式、关注点和信息披露习惯，不能创造SOP之外的农业事实。
"""
    user_prompt = f"""【角色与情境】
{profile_prompt_block(profile, "farmer")}

【作物与问题】
作物：{crop}
问题：{title}
可观察症状种子：{json.dumps(symptoms, ensure_ascii=False)}

请按角色和场景生成一个自然、不完整但具体的初始咨询问题。只输出农户发言。"""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    return clean_text(call_llm(messages, temperature=0.7, max_tokens=500, label="farmer_initial_question"))


def simulate_farmer_response(expert_reply_text: str, sop: dict, profile: dict, history: list) -> str:
    history_text = "\n".join(
        [
            f"农户：{turn.get('user', '')}\n专家：{turn.get('assistant', '')}"
            for turn in history
            if turn.get("assistant")
        ]
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
{expert_reply_text}

请继续按同一角色自然回答专家刚问到的问题。只输出农户发言。"""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    return clean_text(call_llm(messages, temperature=0.7, max_tokens=500, label="farmer_followup_response"))


def expert_reply(sop: dict, history: list, current_user_msg: str, profile: dict) -> dict:
    """Generate the expert side as structured JSON without visible control tags."""
    key_entities = sop.get("missing_info_strategy", {}).get("key_entities", [])
    key_names = [entity.get("name", "") for entity in key_entities if entity.get("name")]

    full_history = []
    for turn in history:
        full_history.append(f"农民：{turn['user']}")
        if turn.get("assistant"):
            full_history.append(f"专家：{turn['assistant']}")
    full_history.append(f"农民：{current_user_msg}")
    history_text = "\n".join(full_history)

    system_prompt = """你扮演角色卡中的甘蔗农技专家，正在和真实农户多轮咨询。
必须只输出一个 JSON 对象，不要输出 Markdown 或 JSON 之外的文字。
JSON 格式只能是：
{"reply_type": "ask", "content": "自然追问内容"}
或：
{"reply_type": "final", "content": "完整最终方案"}

要求：
1. SOP是事实参考和安全边界，不是模板答案，也不是逐项追问清单。
2. 先回应农户的具体担心，再判断当前信息是否足以给出建议。
3. 如果信息不足，reply_type 必须为 ask；只追问1-2个最影响判断或处理建议的问题，并简短说明为什么问。
4. 如果信息已经足够，reply_type 必须为 final；content 给出自然、可执行的最终方案，且不要再追问。
5. 不要机械追问字段，不要连续列问卷，不要重复农户已经回答过的问题。
6. 建议必须落在SOP支持范围内；SOP不支持的具体药剂、剂量、时期、品种不要生成。
7. 不要使用“老乡”“老哥”“为了给您出最准的方子”等固定套话。
8. content 中不要出现 [FINAL_ANSWER] 或任何控制标签。
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

请根据当前信息状态输出 JSON。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    payload = call_json_llm(messages, temperature=0.3, max_tokens=2200, label="专家结构化回复")
    reply_type = payload.get("reply_type")
    content = clean_text(payload.get("content", ""))
    if reply_type not in VALID_REPLY_TYPES:
        raise RuntimeError(f"专家结构化回复 reply_type 非法: {reply_type!r}")
    if not content:
        raise RuntimeError("专家结构化回复 content 为空")
    return {"reply_type": reply_type, "content": content}


def generate_one_dialogue(
    sop: dict,
    sop_id: str,
    sop_file: str,
    run_id: str,
    task_id: str,
    sample_idx: int,
    attempt: int,
    route_result: dict,
    max_turns: int,
    sleep_between_calls: float,
    rng: random.Random | None = None,
) -> dict:
    active_rng = rng or random
    farmer_role = active_rng.choice(FARMER_ROLE_CARDS)
    scenario = generate_scenario_card(sop, sop_id, sample_idx, attempt, farmer_role)
    profile = build_profile(
        sop=sop,
        sop_id=sop_id,
        sample_idx=sample_idx,
        attempt=attempt,
        farmer_role=farmer_role,
        route_result=route_result,
        scenario=scenario,
    )
    history = []
    first_q = generate_initial_question(sop, profile)
    if not first_q:
        raise RuntimeError("农户初始问题生成为空")
    history.append({"user": first_q, "assistant": "", "assistant_reply_type": ""})

    final_turn_index = None
    for turn_idx in range(1, max_turns + 1):
        expert_payload = expert_reply(sop, history[:-1], history[-1]["user"], profile)
        expert_msg = expert_payload["content"]
        reply_type = expert_payload["reply_type"]
        history[-1]["assistant"] = expert_msg
        history[-1]["assistant_reply_type"] = reply_type
        time.sleep(sleep_between_calls)

        if reply_type == FINAL_REPLY_TYPE:
            final_turn_index = len(history) - 1
            print(f"    第{turn_idx}轮专家给出最终方案，对话结束。")
            break

        if "?" not in expert_msg and "？" not in expert_msg:
            raise RuntimeError(f"第{turn_idx}轮专家未追问且未给出最终方案")

        farmer_answer = simulate_farmer_response(expert_msg, sop, profile, history)
        if not farmer_answer:
            raise RuntimeError(f"第{turn_idx}轮农户回复为空")
        history.append({"user": farmer_answer, "assistant": "", "assistant_reply_type": ""})
        time.sleep(sleep_between_calls)

    if final_turn_index is None:
        raise RuntimeError(f"达到最大轮数 {max_turns} 后仍未给出最终方案")

    assistant_reply_types = [turn.get("assistant_reply_type", "") for turn in history]
    return {
        "schema_version": "dialogue_run_v2",
        "run_id": run_id,
        "task_id": task_id,
        "sop_id": sop_id,
        "sop_file": sop_file,
        "sample_idx": sample_idx,
        "attempt": attempt,
        "scenario": scenario,
        "profile": profile,
        "dialog": history,
        "final_turn_index": final_turn_index,
        "assistant_reply_types": assistant_reply_types,
    }


def validate_dialogue_structure(record: dict, max_turns: int) -> tuple[bool, str]:
    dialog = record.get("dialog", [])
    if not dialog:
        return False, "dialog 为空"
    if len(dialog) > max_turns:
        return False, f"turn 数超过限制: {len(dialog)} > {max_turns}"
    final_turn_index = record.get("final_turn_index")
    if final_turn_index != len(dialog) - 1:
        return False, "final_turn_index 不是最后一轮"
    reply_types = record.get("assistant_reply_types", [])
    if not reply_types or reply_types[-1] != FINAL_REPLY_TYPE:
        return False, "最后一轮不是 final"
    if any(reply_type == FINAL_REPLY_TYPE for reply_type in reply_types[:-1]):
        return False, "final 后仍存在后续对话"

    ask_texts = []
    for idx, turn in enumerate(dialog):
        user_text = clean_text(turn.get("user", ""))
        assistant_text = clean_text(turn.get("assistant", ""))
        reply_type = turn.get("assistant_reply_type", "")
        if not user_text or not assistant_text:
            return False, f"第{idx + 1}轮存在空回复"
        if reply_type not in VALID_REPLY_TYPES:
            return False, f"第{idx + 1}轮 assistant_reply_type 非法: {reply_type!r}"
        forbidden = contains_forbidden(user_text + assistant_text)
        if forbidden:
            return False, f"出现禁止短语: {', '.join(sorted(set(forbidden)))}"
        if reply_type == ASK_REPLY_TYPE:
            if "?" not in assistant_text and "？" not in assistant_text:
                return False, f"第{idx + 1}轮 ask 回复没有追问"
            for previous in ask_texts:
                if text_similarity(previous, assistant_text) >= 0.82:
                    return False, "专家重复追问"
            ask_texts.append(assistant_text)
    return True, "pass"


def is_duplicate_candidate(record: dict, accepted_for_sop: list[dict]) -> tuple[bool, str]:
    first_user = record["dialog"][0]["user"]
    final_answer = record["dialog"][-1]["assistant"]
    for previous in accepted_for_sop:
        first_sim = text_similarity(first_user, previous["first_user"])
        final_sim = text_similarity(final_answer, previous["final_answer"])
        if first_sim >= 0.88:
            return True, f"首问近重复 similarity={first_sim:.3f}"
        if final_sim >= 0.86:
            return True, f"最终方案近重复 similarity={final_sim:.3f}"
        if first_sim >= 0.80 and final_sim >= 0.78:
            return True, f"首问和最终方案组合近重复 first={first_sim:.3f}, final={final_sim:.3f}"
    return False, "pass"


def judge_dialogue_against_sop(sop: dict, record: dict) -> dict:
    """Use an LLM judge only to pass/retry/drop; never repair generated content."""
    judge_dialog = [
        {
            "user": turn.get("user", ""),
            "assistant": turn.get("assistant", ""),
            "assistant_reply_type": turn.get("assistant_reply_type", ""),
        }
        for turn in record.get("dialog", [])
    ]
    system_prompt = """你是农业合成数据质量审稿员。
你只能判断样本是否可放行，不能改写、补全或修复样本。
请只输出 JSON 对象，不要输出 Markdown。

判定标准：
- pass：对话自然，最终方案完整，且没有明显超出 SOP 支持范围。
- retry：存在风格、结构、追问或轻度事实边界问题，适合重新生成。
- drop：存在严重事实风险，例如引入 SOP 外具体药剂、剂量、时期、品种，或最终方案明显错误。
"""
    user_prompt = f"""【SOP】
{json.dumps(sop, ensure_ascii=False, indent=2)}

【待审对话】
{json.dumps(judge_dialog, ensure_ascii=False, indent=2)}

请输出：
{{
  "verdict": "pass|retry|drop",
  "reason": "一句话说明原因"
}}
"""
    result = call_json_llm(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        temperature=0,
        max_tokens=1000,
        label="LLM质检",
    )
    verdict = result.get("verdict")
    if verdict not in {"pass", "retry", "drop"}:
        raise RuntimeError(f"质检 judge verdict 非法: {verdict!r}")
    return {"verdict": verdict, "reason": clean_text(result.get("reason", ""))}


def make_task_id(run_id: str, sop_file: str, sample_idx: int) -> str:
    sop_hash = hashlib.sha1(sop_file.encode("utf-8")).hexdigest()[:8]
    return f"{run_id}:{sop_hash}:sample_{sample_idx:04d}"


def p95(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int((len(ordered) - 1) * 0.95)
    return ordered[index]


def build_quality_summary(
    run_id: str,
    config: dict,
    accepted_records: list[dict],
    task_records: list[dict],
    failure_records: list[dict],
    duplicate_rejections: int,
    api_timing_summary: dict,
    judge_sample_records: list[dict],
) -> dict:
    turn_counts = [len(record["dialog"]) for record in accepted_records]
    per_sop = Counter(record["sop_id"] for record in accepted_records)
    role_distribution = Counter(record["profile"]["profile_id"] for record in accepted_records)
    expert_distribution = Counter(record["profile"]["expert_role"]["role_id"] for record in accepted_records)
    farmer_distribution = Counter(record["profile"]["farmer_role"]["role_id"] for record in accepted_records)
    forbidden_counts = Counter()
    for record in accepted_records:
        for turn in record["dialog"]:
            for phrase in contains_forbidden(turn.get("user", "") + turn.get("assistant", "")):
                forbidden_counts[phrase] += 1

    failures_by_reason = Counter(record["reason"] for record in failure_records)
    final_complete = sum(
        1
        for record in accepted_records
        if record.get("final_turn_index") == len(record.get("dialog", [])) - 1
        and record.get("assistant_reply_types", [])[-1:] == [FINAL_REPLY_TYPE]
    )

    samples = []
    for record in accepted_records[:5]:
        samples.append({
            "task_id": record["task_id"],
            "sop_id": record["sop_id"],
            "first_user": record["dialog"][0]["user"],
            "final_answer": record["dialog"][-1]["assistant"],
        })

    return {
        "run_id": run_id,
        "config": config,
        "target_tasks": len(task_records),
        "accepted_count": len(accepted_records),
        "failed_task_count": sum(1 for record in task_records if record["status"] == "failed"),
        "failure_attempt_count": len(failure_records),
        "retry_count": sum(max(0, record.get("attempts", 1) - 1) for record in task_records),
        "duplicate_rejections": duplicate_rejections,
        "judge_sample_count": len(judge_sample_records),
        "judge_sample_verdicts": dict(Counter(record.get("verdict", "unknown") for record in judge_sample_records)),
        "per_sop_accepted": dict(sorted(per_sop.items())),
        "turn_stats": {
            "avg": statistics.mean(turn_counts) if turn_counts else None,
            "min": min(turn_counts) if turn_counts else None,
            "max": max(turn_counts) if turn_counts else None,
            "p95": p95(turn_counts),
        },
        "forbidden_phrase_counts": dict(forbidden_counts),
        "final_complete_rate": final_complete / len(accepted_records) if accepted_records else 0,
        "near_duplicate_rejection_rate": duplicate_rejections / max(1, len(failure_records)),
        "role_distribution": dict(role_distribution),
        "expert_role_distribution": dict(expert_distribution),
        "farmer_role_distribution": dict(farmer_distribution),
        "failures_by_reason": dict(failures_by_reason.most_common(30)),
        "api_timing": api_timing_summary,
        "sample_dialogues": samples,
    }


def write_sha256sums(run_dir: Path):
    entries = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            rel = path.relative_to(run_dir)
            entries.append(f"{file_sha256(path)}  {rel.as_posix()}")
    (run_dir / "SHA256SUMS").write_text("\n".join(entries) + "\n", encoding="utf-8")


def summarize_api_timings(timing_path: Path) -> dict:
    if not timing_path.exists():
        return {
            "call_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "by_label": {},
            "by_key_index": {},
        }

    events = [json.loads(line) for line in timing_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_label = defaultdict(list)
    by_key = Counter()
    success_count = 0
    for event in events:
        by_label[event.get("label", "unknown")].append(event.get("latency_ms", 0))
        by_key[str(event.get("api_key_index", "unknown"))] += 1
        if event.get("success"):
            success_count += 1

    label_summary = {}
    for label, values in sorted(by_label.items()):
        label_summary[label] = {
            "count": len(values),
            "avg_ms": statistics.mean(values) if values else None,
            "min_ms": min(values) if values else None,
            "max_ms": max(values) if values else None,
            "p95_ms": p95(values),
        }

    return {
        "call_count": len(events),
        "success_count": success_count,
        "failure_count": len(events) - success_count,
        "by_label": label_summary,
        "by_key_index": dict(sorted(by_key.items())),
    }


def safe_model_name(model_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", model_name).strip("-") or "model"


def parse_args():
    parser = argparse.ArgumentParser(description="Generate high-confidence role-driven SOP dialogues.")
    parser.add_argument("--input-dir", default="output2", help="Directory containing *_complex.json SOP files.")
    parser.add_argument("--output-root", default="runs", help="Root directory for run outputs.")
    parser.add_argument("--run-id", default="", help="Optional run id. Defaults to timestamp_model_commit_dialogue-v2.")
    parser.add_argument("--samples-per-sop", type=int, default=10, help="Accepted dialogue target per SOP.")
    parser.add_argument("--max-generation-attempts", type=int, default=2, help="Attempts per SOP sample before dropping.")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help="Maximum dialogue turns.")
    parser.add_argument("--strict", action="store_true", help="Run LLM fact-boundary judge before accepting samples.")
    parser.add_argument(
        "--judge-sample-rate",
        type=float,
        default=0.0,
        help="Optional non-gating LLM judge sample rate for accepted records when --strict is off.",
    )
    parser.add_argument("--seed", type=int, default=20260604, help="Random seed.")
    parser.add_argument("--limit-sops", type=int, default=0, help="Limit number of SOP files, useful for smoke tests.")
    parser.add_argument("--concurrency", type=int, default=1, help="Number of SOP files to process concurrently.")
    parser.add_argument("--sleep-between-calls", type=float, default=DEFAULT_SLEEP_BETWEEN_CALLS)
    return parser.parse_args()


def main():
    global API_TIMING_LOG_PATH
    args = parse_args()
    if args.samples_per_sop < 1:
        raise ValueError("--samples-per-sop 必须 >= 1")
    if args.max_generation_attempts < 1:
        raise ValueError("--max-generation-attempts 必须 >= 1")
    if args.max_turns < 1:
        raise ValueError("--max-turns 必须 >= 1")
    if args.concurrency < 1:
        raise ValueError("--concurrency 必须 >= 1")
    if args.judge_sample_rate < 0 or args.judge_sample_rate > 1:
        raise ValueError("--judge-sample-rate 必须在 0 到 1 之间")

    random.seed(args.seed)
    input_dir = Path(args.input_dir)
    output_root = Path(args.output_root)
    code_commit = get_code_commit()
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = args.run_id or f"{timestamp}_{safe_model_name(MODEL_NAME)}_{code_commit}_dialogue-v2"
    run_dir = output_root / run_id
    if run_dir.exists() and any(run_dir.iterdir()):
        raise RuntimeError(f"run 目录已存在且非空: {run_dir}")

    reports_dir = run_dir / "reports"
    logs_dir = run_dir / "logs"
    reports_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    API_TIMING_LOG_PATH = logs_dir / "api_calls.jsonl"
    dialogues_path = run_dir / "dialogues.jsonl"
    tasks_path = run_dir / "tasks.jsonl"
    failures_path = run_dir / "failures.jsonl"
    judge_samples_path = reports_dir / "judge_samples.jsonl"

    json_files = sorted(input_dir.glob("*_complex.json"))
    if args.limit_sops:
        json_files = json_files[:args.limit_sops]
    if not json_files:
        print(f"在 {input_dir} 中没有找到任何 _complex.json 文件。")
        return

    config = {
        "run_id": run_id,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "input_dir": str(input_dir),
        "output_root": str(output_root),
        "model": MODEL_NAME,
        "api_base_url": API_BASE_URL,
        "code_commit": code_commit,
        "samples_per_sop": args.samples_per_sop,
        "max_generation_attempts": args.max_generation_attempts,
        "max_turns": args.max_turns,
        "strict": args.strict,
        "judge_sample_rate": args.judge_sample_rate,
        "seed": args.seed,
        "limit_sops": args.limit_sops,
        "concurrency": args.concurrency,
        "sop_file_count": len(json_files),
        "api_key_count": len(parse_api_keys()),
        "forbidden_phrases": FORBIDDEN_PHRASES,
    }
    write_json(run_dir / "config.json", config)

    print(f"run_id: {run_id}")
    print(f"输出目录: {run_dir}")
    print(f"找到 {len(json_files)} 个 SOP 文件，目标每个 SOP {args.samples_per_sop} 条 accepted 对话。")

    accepted_records = []
    task_records = []
    failure_records = []
    judge_sample_records = []
    duplicate_rejections = 0

    def process_json_file(item: tuple[int, Path]) -> dict:
        file_index, json_file = item
        rng = random.Random(args.seed + file_index * 1009)
        local_accepted_records = []
        local_task_records = []
        local_failure_records = []
        local_judge_sample_records = []
        local_duplicate_rejections = 0
        accepted_for_sop = []
        relative_sop_file = str(json_file)
        print(f"\n处理: {json_file.name}")
        try:
            with json_file.open("r", encoding="utf-8") as handle:
                sop = json.load(handle)
        except Exception as exc:
            for sample_idx in range(args.samples_per_sop):
                task_id = make_task_id(run_id, json_file.name, sample_idx)
                reason = f"读取JSON失败: {exc}"
                failure = {
                    "task_id": task_id,
                    "file": relative_sop_file,
                    "sop_id": "UNKNOWN",
                    "sample_idx": sample_idx,
                    "attempt": 0,
                    "reason": reason,
                }
                append_jsonl(failures_path, failure)
                local_failure_records.append(failure)
                task = {"task_id": task_id, "file": relative_sop_file, "sop_id": "UNKNOWN", "sample_idx": sample_idx, "status": "failed", "attempts": 0, "reason": reason}
                append_jsonl(tasks_path, task)
                local_task_records.append(task)
            return {
                "file_index": file_index,
                "accepted_records": local_accepted_records,
                "task_records": local_task_records,
                "failure_records": local_failure_records,
                "judge_sample_records": local_judge_sample_records,
                "duplicate_rejections": local_duplicate_rejections,
            }

        sop_id = sop.get("meta", {}).get("title", json_file.name.replace("_complex.json", ""))
        try:
            print("  路由专家角色...")
            route_result = route_expert_role(sop, sop_id)
        except Exception as exc:
            reason = f"专家角色路由失败: {exc}"
            print(f"  {reason}")
            for sample_idx in range(args.samples_per_sop):
                task_id = make_task_id(run_id, json_file.name, sample_idx)
                failure = {
                    "task_id": task_id,
                    "file": relative_sop_file,
                    "sop_id": sop_id,
                    "sample_idx": sample_idx,
                    "attempt": 0,
                    "reason": reason,
                }
                append_jsonl(failures_path, failure)
                local_failure_records.append(failure)
                task = {"task_id": task_id, "file": relative_sop_file, "sop_id": sop_id, "sample_idx": sample_idx, "status": "failed", "attempts": 0, "reason": reason}
                append_jsonl(tasks_path, task)
                local_task_records.append(task)
            return {
                "file_index": file_index,
                "accepted_records": local_accepted_records,
                "task_records": local_task_records,
                "failure_records": local_failure_records,
                "judge_sample_records": local_judge_sample_records,
                "duplicate_rejections": local_duplicate_rejections,
            }

        for sample_idx in range(args.samples_per_sop):
            task_id = make_task_id(run_id, json_file.name, sample_idx)
            accepted = False
            final_reason = ""
            attempts_used = 0
            for attempt in range(args.max_generation_attempts):
                attempts_used = attempt + 1
                print(f"  生成 sample {sample_idx + 1}/{args.samples_per_sop}, attempt {attempt + 1}/{args.max_generation_attempts}...")
                try:
                    record = generate_one_dialogue(
                        sop=sop,
                        sop_id=sop_id,
                        sop_file=relative_sop_file,
                        run_id=run_id,
                        task_id=task_id,
                        sample_idx=sample_idx,
                        attempt=attempt,
                        route_result=route_result,
                        max_turns=args.max_turns,
                        sleep_between_calls=args.sleep_between_calls,
                        rng=rng,
                    )
                    ok, reason = validate_dialogue_structure(record, args.max_turns)
                    if not ok:
                        raise RuntimeError(f"结构/风格校验失败: {reason}")

                    duplicate, duplicate_reason = is_duplicate_candidate(record, accepted_for_sop)
                    if duplicate:
                        local_duplicate_rejections += 1
                        raise RuntimeError(f"近重复样本: {duplicate_reason}")

                    if args.strict:
                        judge = judge_dialogue_against_sop(sop, record)
                        record["validation"] = {
                            "status": judge["verdict"],
                            "reason": judge["reason"],
                            "validator": "llm_judge",
                        }
                        if judge["verdict"] != "pass":
                            final_reason = f"LLM质检未通过: {judge['verdict']} - {judge['reason']}"
                            failure = {
                                "task_id": task_id,
                                "file": relative_sop_file,
                                "sop_id": sop_id,
                                "sample_idx": sample_idx,
                                "attempt": attempt,
                                "reason": final_reason,
                            }
                            append_jsonl(failures_path, failure)
                            local_failure_records.append(failure)
                            if judge["verdict"] == "drop":
                                break
                            continue
                    else:
                        record["validation"] = {
                            "status": "pass",
                            "reason": "strict judge disabled; structural/style/dedup validators passed",
                            "validator": "local_validators",
                        }
                        if args.judge_sample_rate and random.random() < args.judge_sample_rate:
                            try:
                                judge = judge_dialogue_against_sop(sop, record)
                                judge_record = {
                                    "task_id": task_id,
                                    "sop_id": sop_id,
                                    "sample_idx": sample_idx,
                                    "attempt": attempt,
                                    "verdict": judge["verdict"],
                                    "reason": judge["reason"],
                                }
                            except Exception as exc:
                                judge_record = {
                                    "task_id": task_id,
                                    "sop_id": sop_id,
                                    "sample_idx": sample_idx,
                                    "attempt": attempt,
                                    "verdict": "judge_error",
                                    "reason": str(exc),
                            }
                            append_jsonl(judge_samples_path, judge_record)
                            local_judge_sample_records.append(judge_record)

                    append_jsonl(dialogues_path, record)
                    local_accepted_records.append(record)
                    accepted_for_sop.append({
                        "first_user": record["dialog"][0]["user"],
                        "final_answer": record["dialog"][-1]["assistant"],
                    })
                    task = {
                        "task_id": task_id,
                        "file": relative_sop_file,
                        "sop_id": sop_id,
                        "sample_idx": sample_idx,
                        "status": "accepted",
                        "attempts": attempts_used,
                    }
                    append_jsonl(tasks_path, task)
                    local_task_records.append(task)
                    accepted = True
                    print("    accepted")
                    break

                except Exception as exc:
                    final_reason = str(exc)
                    print(f"    失败: {final_reason}")
                    failure = {
                        "task_id": task_id,
                        "file": relative_sop_file,
                        "sop_id": sop_id,
                        "sample_idx": sample_idx,
                        "attempt": attempt,
                        "reason": final_reason,
                    }
                    append_jsonl(failures_path, failure)
                    local_failure_records.append(failure)
                    time.sleep(1)

            if not accepted:
                task = {
                    "task_id": task_id,
                    "file": relative_sop_file,
                    "sop_id": sop_id,
                    "sample_idx": sample_idx,
                    "status": "failed",
                    "attempts": attempts_used,
                    "reason": final_reason,
                }
                append_jsonl(tasks_path, task)
                local_task_records.append(task)

        return {
            "file_index": file_index,
            "accepted_records": local_accepted_records,
            "task_records": local_task_records,
            "failure_records": local_failure_records,
            "judge_sample_records": local_judge_sample_records,
            "duplicate_rejections": local_duplicate_rejections,
        }

    def collect_result(result: dict):
        nonlocal duplicate_rejections
        accepted_records.extend(result["accepted_records"])
        task_records.extend(result["task_records"])
        failure_records.extend(result["failure_records"])
        judge_sample_records.extend(result["judge_sample_records"])
        duplicate_rejections += result["duplicate_rejections"]

    work_items = list(enumerate(json_files))
    worker_count = min(args.concurrency, len(work_items))
    if worker_count == 1:
        for item in work_items:
            collect_result(process_json_file(item))
    else:
        print(f"并发处理: {worker_count} 个 SOP worker")
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_item = {executor.submit(process_json_file, item): item for item in work_items}
            for future in as_completed(future_to_item):
                collect_result(future.result())

    accepted_records.sort(key=lambda record: (record.get("sop_id", ""), record.get("sample_idx", 0), record.get("attempt", 0)))
    task_records.sort(key=lambda record: (record.get("sop_id", ""), record.get("sample_idx", 0), record.get("attempts", 0)))
    failure_records.sort(key=lambda record: (record.get("sop_id", ""), record.get("sample_idx", 0), record.get("attempt", 0)))

    summary = build_quality_summary(
        run_id=run_id,
        config=config,
        accepted_records=accepted_records,
        task_records=task_records,
        failure_records=failure_records,
        duplicate_rejections=duplicate_rejections,
        api_timing_summary=summarize_api_timings(API_TIMING_LOG_PATH),
        judge_sample_records=judge_sample_records,
    )
    write_json(reports_dir / "quality_summary.json", summary)
    write_sha256sums(run_dir)

    print("\n" + "=" * 50)
    print("生成统计报告")
    print("=" * 50)
    print(f"目标任务数: {len(task_records)}")
    print(f"accepted: {summary['accepted_count']}")
    print(f"failed tasks: {summary['failed_task_count']}")
    print(f"failure attempts: {summary['failure_attempt_count']}")
    print(f"duplicate rejections: {duplicate_rejections}")
    print(f"api calls: {summary['api_timing']['call_count']} (failures: {summary['api_timing']['failure_count']})")
    for label, stats in summary["api_timing"]["by_label"].items():
        print(f"  {label}: count={stats['count']} avg_ms={stats['avg_ms']:.0f} max_ms={stats['max_ms']}")
    print(f"对话文件: {dialogues_path}")
    print(f"质量报告: {reports_dir / 'quality_summary.json'}")


if __name__ == "__main__":
    main()
