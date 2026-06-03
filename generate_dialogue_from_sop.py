#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
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