import base64
import datetime
import hashlib
import hmac
import json
import time
import uuid
import requests
from pathlib import Path
import shutil
import subprocess
import chardet
import openai
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
)
from tqdm import tqdm
import os
import logging
from bench.utils import is_test


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 补丁应用命令
GIT_APPLY_CMDS = [
    "git apply --verbose",
    "patch --batch --fuzz=5 -p1 -i",
]

# 补丁示例
PATCH_EXAMPLE = """--- a/file.py
+++ b/file.py
@@ -1,27 +1,35 @@
 def euclidean(a, b):
-    while b:
-        a, b = b, a % b
-    return a
+    if b == 0:
+        return a
+    return euclidean(b, a % b)
 
 
 def bresenham(x0, y0, x1, y1):
     points = []
     dx = abs(x1 - x0)
     dy = abs(y1 - y0)
-    sx = 1 if x0 < x1 else -1
-    sy = 1 if y0 < y1 else -1
-    err = dx - dy
+    x, y = x0, y0
+    sx = -1 if x0 > x1 else 1
+    sy = -1 if y0 > y1 else 1
 
-    while True:
-        points.append((x0, y0))
-        if x0 == x1 and y0 == y1:
-            break
-        e2 = 2 * err
-        if e2 > -dy:
+    if dx > dy:
+        err = dx / 2.0
+        while x != x1:
+            points.append((x, y))
             err -= dy
-            x0 += sx
-        if e2 < dx:
-            err += dx
-            y0 += sy
+            if err < 0:
+                y += sy
+                err += dx
+            x += sx
+    else:
+        err = dy / 2.0
+        while y != y1:
+            points.append((x, y))
+            err -= dx
+            if err < 0:
+                x += sx
+                err += dy
+            y += sy
 
+    points.append((x, y))
     return points"""


FULL_GENERATION_EXAMPLE = """[start of /src/this_file.py]
import os

def euclidean(a, b):
    if b == 0:
        return a
    return euclidean(b, a % b)
[end of /src/this_file.py]
[start of /src/another_file.py]
def bresenham(x0, y0, x1, y1):
    points = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    x, y = x0, y0
    sx = -1 if x0 > x1 else 1
    sy = -1 if y0 > y1 else 1
    if dx > dy:
        err = dx / 2.0
        while x != x1:
            points.append((x, y))
            err -= dy
            if err < 0:
                y += sy
                err += dx
            x += sx
    else:
        err = dy / 2.0
        while y != y1:
            points.append((x
            err -= dx
            if err < 0:
                x += sx
                err += dy
            y += sy
    points.append((x, y))
    return points
[end of /src/another_file.py]"""


os.environ["TOKENIZERS_PARALLELISM"] = "false"
from transformers import AutoTokenizer
# 默认tokenizer
TOKENIZER = AutoTokenizer.from_pretrained("openai-community/openai-gpt", local_files_only=True)
MAX_LENGTH = 98000
logging.getLogger("transformers").setLevel(logging.ERROR) # 消除警告


# 添加行号
def add_lines_list(content):
    content_with_lines = list()
    for ix, line in enumerate(content.split("\n"), start=1):
        content_with_lines.append(f"{ix} {line}")
    return content_with_lines

# 添加行号
def add_lines(content):
    return "\n".join(add_lines_list(content))


# 将文件内容转换为文本
def make_code_text(files_dict, add_line_numbers=False):
    all_text = ""
    if isinstance(files_dict, list):
        for file in files_dict:
            all_text += f"[start of {file['path']}]\n"
            if add_line_numbers:
                all_text += add_lines(file['content'])
            else:
                all_text += file['content']
            all_text += f"\n[end of {file['path']}]\n"
    else:
        for filename, contents in sorted(files_dict.items()):
            all_text += f"[start of {filename}]\n"
            if add_line_numbers:
                all_text += add_lines(contents)
            else:
                all_text += contents
            all_text += f"\n[end of {filename}]\n"
    return all_text.strip("\n")


def make_code_snippet_text(files_dict):
    all_text = ""
    if isinstance(files_dict, list):
        for file in files_dict:
            all_text += f"[start of {file['path']}]\n"
            # 定位待生成代码所在行数
            raw_lines = file['content'].split("\n")
            flag = False
            for line in raw_lines:
                if "<MASKED>" in line:
                    index = raw_lines.index(line)
                    start_line = index - 300
                    if start_line < 0:
                        start_line = 0
                    end_line = index + 300
                    if end_line > len(raw_lines):
                        end_line = len(raw_lines)
                    all_text += "\n".join(raw_lines[start_line:end_line])
                    flag = True
                    break
            if not flag:
                raise ValueError(f"未找到待生成代码所在行数: {file['path']}")
            else:
                logger.info(f"已精简上下文文件: [{start_line}, {end_line}] in {filename}")
            all_text += f"\n[end of {file['path']}]\n"
    else:
        for filename, contents in sorted(files_dict.items()):
            all_text += f"[start of {filename}]\n"
            raw_lines = file['content'].split("\n")
            flag = False
            for line in raw_lines:
                if "<MASKED>" in line:
                    index = raw_lines.index(line)
                    start_line = index - 300
                    if start_line < 0:
                        start_line = 0
                    end_line = index + 300
                    if end_line > len(raw_lines):
                        end_line = len(raw_lines)
                    all_text += "\n".join(raw_lines[start_line:end_line])
                    flag = True
                    break
            if not flag:
                raise ValueError(f"未找到待生成代码所在行数: {filename}")
            else:
                logger.info(f"已精简上下文文件: [{start_line}, {end_line}] in {filename}")
            all_text += f"\n[end of {filename}]\n"
    return all_text


# 将文件内容转换为文本
def ingest_files(filenames):
    files_dict = dict()
    for filename in filenames:
        if not os.path.exists(filename):
            continue
        with open(filename,encoding="utf-8",errors="ignore") as f:
            content = f.read()
        files_dict[filename] = content
    return files_dict

# 检测文件编码
def detect_encoding(filename):
    """
    Detect the encoding of a file
    """
    with open(filename, "rb",errors="ignore") as file:
        rawdata = file.read()
    return chardet.detect(rawdata)["encoding"]

# 列出文件
def list_files(root_dir, include_tests=False):
    files = []
    for filename in Path(root_dir).rglob("*.py"):
        if not include_tests and is_test(filename.as_posix()):
            continue
        files.append(filename.relative_to(root_dir).as_posix())
    return files


def ingest_directory_contents(root_dir, include_tests=False):
    files_content = {}
    for relative_path in list_files(root_dir, include_tests=include_tests):
        filename = os.path.join(root_dir, relative_path)
        content = read_file_content(filename)
        files_content[relative_path] = content
    return files_content


def read_file_content(filename):
    """读取文件内容，处理编码和异常情况
    
    Args:
        filename: 文件路径
        
    Returns:
        str: 文件内容或错误提示
    """
    encoding = detect_encoding(filename)
    if encoding is None:
        return "[BINARY DATA FILE]"
    
    try:
        with open(filename, encoding=encoding) as file:
            return file.read()
    except (UnicodeDecodeError, LookupError):
        return "[BINARY DATA FILE]"

# 添加检索结果
def add_retrieval_results(input_instances, retrieval_file, k, file_source):
    """
    Adds retrieval results to input_instances in-place
    """
    retrieval_results_path = Path(retrieval_file)
    assert retrieval_results_path.exists(), (
        f"Retrieval results not found at {retrieval_results_path}"
    )
    retrieval_results = [json.loads(line) for line in open(retrieval_results_path)]
    retrieval_results = {x["instance_id"]: x["hits"] for x in retrieval_results}
    for instance_id, instance in tqdm(
        input_instances.items(),
        total=len(input_instances),
        desc="Adding retrieval results",
    ):
        try:
            instance["hits"] = retrieval_results[instance_id][:k]
        except KeyError:
            logger.warning(f"Instance {instance_id} not found in retrieval results")
            instance["hits"] = list()

# 生成不带函数功能摘要的提示词
def make_codegen_prompt_nosummary(readme_files,masked_files,context_files):
    system_message = (
        "You will be given a partial code base with <base> and a code file with <code> sections. "
        "Certain portions in the code file are maked as <MASKED>. "
        "Your task is to complete the code by filling in the <MASKED> portions. "
        "If necessary, feel free to add new functions to complete the code logic."
    )
    # 获取 readme 文件内容，辅助理解项目
    readme_text = make_code_text(ingest_files(readme_files))
    # 获取漏洞文件内容，并进行挖空处理
    code_text = make_code_text(masked_files)
    # 删除上下文文件中和漏洞文件重合的文件，避免重复
    context_files = [file for file in context_files if file not in masked_files]
    code_base_text = make_code_text(ingest_files(context_files))

    # 生成 masked 代码范围提示
    masked_note = (
        "Note: The <MASKED> section may include more than one function. "
        "Please implement all missing parts described in the functionality summary above."
    )
    # 生成最终指令的提示词
    final_instruction = (
        "I need you to complete the code by generating the ONLY the code that should replace the <MASKED> section. "
        "Put the code in markdown code fences and do not include explanations."
    )
    # 生成提示词
    text = [
        "<code>",
        code_text,
        "</code>",
        "",
        "<base>",
        readme_text,
        code_base_text,
        "</base>",
        "",
        masked_note,
        final_instruction,
        "Respond below:",
    ]
    user_message = "\n".join(text)
    return system_message, user_message

# 生成带函数功能摘要的提示词
def make_codegen_prompt_withsummary(readme_files,masked_files,context_files,function_summary):
    system_message = (
        "You will be given a partial code base with <base> and a code file with <code> sections. "
        "Certain portions in the code file are maked as <MASKED>. "
        "Your task is to complete the code by filling in the <MASKED> portions. "
        "If necessary, feel free to add new functions to complete the code logic."
    )
    # 获取 readme 文件内容，辅助理解项目
    readme_text = make_code_text(ingest_files(readme_files))
    # 获取漏洞文件内容，并进行挖空处理
    code_text = make_code_text(masked_files)

    # Todo: 长度检查，当单个文件过长时只保留目标代码块前后各 300 行代码
    code_text_tokens = len(TOKENIZER(code_text)['input_ids'])
    if code_text_tokens > 60000:
        code_text = make_code_snippet_text(masked_files)

    # 删除上下文文件中和漏洞文件重合的文件
    context_files = [file for file in context_files if file["path"] not in masked_files]
    code_base_text = make_code_text(context_files)
    # 生成函数功能摘要的解释
    summary_explanation = (
        "Here is the functionality summary of the code snippet that you need to complete: "
        + function_summary
    )
    # 生成 masked 代码范围提示
    masked_note = (
        "Note: The <MASKED> section may include more than one function. "
        "Please implement all missing parts described in the functionality summary above."
    )
    # 生成最终指令的提示词
    final_instruction = (
        "I need you to complete the code by generating the ONLY the code that should replace the <MASKED> section. "
        "Put the code in markdown code fences and do not include explanations."
    )
    # 拼接提示词
    text = [
        summary_explanation,
        "",
        "<code>",
        code_text,
        "</code>",
        "",
        "<base>",
        readme_text,
        code_base_text,
        "</base>",
        "",
        masked_note,
        "",
        final_instruction,
        "Respond below:",
    ]
    user_message = "\n".join(text)
    return system_message, user_message


def make_codegen_prompt(MAXTOKEN,readme_files,masked_files,context_files,function_summary):
    # 计算基础提示词的长度，默认使用带函数功能摘要的提示词
    system_message, user_message = make_codegen_prompt_withsummary(readme_files,
                                                                   masked_files,[],function_summary)
    basic_prompt = system_message + "\n" + user_message

    prompt_tokens = len(TOKENIZER(basic_prompt)['input_ids'])
    prompt_length = len(basic_prompt)

    # 提示词过长时，移除 readme 文件
    if prompt_tokens > 130000:
        readme_files = []

    # 根据 MAX_TOKENS 和 MAX_LENGTH 计算使用的上下文文件
    used_context_files = []
    count=0
    for file in context_files:
        content = make_code_text({file["path"]: file["content"]})
        content_tokens = len(TOKENIZER(content)['input_ids'])
        if prompt_tokens + content_tokens > MAXTOKEN:
            break
        if prompt_length + len(content) > MAX_LENGTH:
            break
        # 更新提示词的 token 数量和长度 
        prompt_tokens += content_tokens
        prompt_length += len(content)
    
        used_context_files.append(file)
        count+=1
    count+=1 # 加上漏洞文件
    print(f"使用上下文文件数量: {count}")

    # 生成最终的提示词
    system_message, user_message = make_codegen_prompt_withsummary(readme_files,masked_files,
                                                                   used_context_files,function_summary)
    return system_message, user_message

# 调用大模型，用户可以在该函数内定制化大模型调用方式
@retry(wait=wait_random_exponential(min=30, max=600), stop=stop_after_attempt(3))
def call_llm(base_url, openai_key, model_name, system_message, user_message, max_gen_token, **model_args):
    # 预定义 API 平台调用
    if model_name == "hunyuan-t1-20250321":
        return hySend(model_name, system_message, user_message)

    openai.base_url = base_url
    openai.api_key = openai_key

    if "claude" in model_name:
        response = openai.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_message}, 
                {"role": "user", "content": user_message}
            ],
            max_tokens=max_gen_token,
            **model_args
        )
    else:
        response = openai.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_message}, 
                {"role": "user", "content": user_message}
            ],
            max_completion_tokens=max_gen_token,
            **model_args
        )

    # 结果提取
    stream = model_args.get("stream", False)
    if stream:
        final_answer = ""
        for chunk in response:
            if not chunk.choices:
                continue
            answer_chunk = chunk.choices[0].delta.content
            if answer_chunk is None:
                continue
            final_answer += answer_chunk
        return final_answer
    else:
        completion = response.choices[0].message.content.strip()
        return completion



# 通过response方式调用大模型
def openai_response_call_model(base_url, openai_key, model_name, system_message, user_message):
    if type(openai_key) == tuple:
        openai_key = openai_key[0]

    client = openai.OpenAI(
        api_key = openai_key,
        base_url = base_url
    )

    response = client.responses.create(
        model=model_name,
        input=system_message + "\n\n" + user_message
    )
    return response.output_text


def hySend(model_name, system_message, user_message):
    # 调用大模型
    server = os.getenv('HY_SERVER')
    header = {}
    header['Content-Type'] = 'application/json'
    header['Authorization'] = os.getenv('HY_TOKEN')
    try:
        param = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": f'''{system_message}'''
                },
                {"role": "user", "content": f'''{user_message}'''}
            ],
        }
        response = requests.post(server, data=json.dumps(param), headers=header)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"调用大模型失败: {str(e)}")
        return None


# 调用 Qwen3 模型
def qwen3_call(base_url, openai_key, model_name, system_message, user_message, thinking=False):
    # api_key = os.getenv('QWEN3_KEY')
    client = openai.OpenAI(
        base_url=base_url,
        api_key=openai_key,
    )
    # 设置 extra_body 用于控制思考
    extra_body = {
        "enable_thinking": thinking,
    }
    # 调用大模型
    model_name = model_name[:model_name.rfind('-')]
    response = client.chat.completions.create(
        model=model_name, 
        messages=[
                {"role": "system", "content": system_message}, 
                {"role": "user", "content": user_message}
            ],
        stream=True,
        extra_body=extra_body
    )
    # 获取回答
    final_answer = ""
    for chunk in response:
        answer_chunk = chunk.choices[0].delta.content
        if answer_chunk is None:
            continue
        final_answer += answer_chunk
    return final_answer



def apply_patch(patch_content, target_dir, cmd):
    # 创建补丁文件
    patch_file = os.path.join(target_dir, f"patch.diff")
    with open(patch_file, 'w', encoding='utf-8') as f:
        f.write(patch_content)
    
    # 进入新仓库目录
    original_dir = os.getcwd()
    os.chdir(target_dir)
    # 应用补丁
    success = False
    try:
        cmd_parts = cmd.split()
        result = subprocess.run(
            cmd_parts + ["patch.diff"],
            capture_output=True,
            text=True,
            check=False
        )
        # 如果应用成功，则返回 True
        if result.returncode == 0:
            logger.info(f"使用命令 {cmd} 成功应用补丁")
            success = True
        # 如果应用失败，则返回 False
        else:
            last_error = result.stderr
            logger.warning(f"命令 {cmd} 失败: {result.stderr}")
            if "--allow-empty" in last_error:
                logger.info(f"补丁为空,response为{patch_content}")
        return success        
    except Exception as e:
        logger.error(f"应用补丁时发生错误: {str(e)}")
    finally:
        # 恢复原始工作目录
        os.chdir(original_dir)

def normalize_indent(generated_code: str, mask_indent: str) -> str:
    lines = generated_code.split('\n')
    if not lines or not lines[0]:
        return generated_code
    first_line = lines[0]
    first_indent_len = len(first_line) - len(first_line.lstrip())
    offset = len(mask_indent) - first_indent_len

    if offset == 0:
        return generated_code

    new_lines = []
    for line in lines:
        if line.strip() == "":
            new_lines.append("")
            continue
        current_indent_len = len(line) - len(line.lstrip())
        new_indent_len = max(0, current_indent_len + offset)
        new_lines.append(" " * new_indent_len + line.lstrip())
    return '\n'.join(new_lines)


def count_braces_diff(code: str) -> int:
    """
    计算代码中 '{' 和 '}' 的相对差值（'{' 数量 - '}' 数量），
    尽量排除字符串和注释中的花括号。
    """
    diff = 0
    in_string = False
    string_char = None
    in_comment = False
    i = 0
    chars = code
    length = len(chars)
    while i < length:
        c = chars[i]
        next_c = chars[i + 1] if i + 1 < length else ''

        if in_comment:
            if c == '*' and next_c == '/':
                in_comment = False
                i += 2
                continue
        elif in_string:
            if c == '\\':
                i += 2
                continue
            if c == string_char:
                in_string = False
                string_char = None
        else:
            if c == '/' and next_c == '/':
                break  # 单行注释，后面都忽略
            elif c == '/' and next_c == '*':
                in_comment = True
                i += 2
                continue
            elif c in ('"', "'"):
                in_string = True
                string_char = c
            elif c == '{':
                diff += 1
            elif c == '}':
                diff -= 1
        i += 1
    return diff


def deduplicate_and_balance_code(generated_code, prefix_lines=None, suffix_lines=None, original_vuln_block=None):
    """
    对生成代码进行去冗余和花括号平衡校验。
    1. 去重：删除与 mask 前后文完全相同的头部/尾部行
    2. 花括号平衡：调整 '{' / '}' 差值与 original_vuln_block 一致
    """
    generated_lines = generated_code.split('\n')

    # 1. 前部去重：生成代码头部与 mask 前尾部比较
    if prefix_lines is not None:
        max_n = min(len(generated_lines), len(prefix_lines), 20)
        for n in range(max_n, 0, -1):
            if generated_lines[:n] == prefix_lines[-n:]:
                generated_lines = generated_lines[n:]
                logger.info(f"删除生成代码前部重复 {n} 行")
                break

    # 2. 后部去重：生成代码尾部与 mask 后头部比较
    if suffix_lines is not None:
        max_n = min(len(generated_lines), len(suffix_lines), 20)
        for n in range(max_n, 0, -1):
            if generated_lines[-n:] == suffix_lines[:n]:
                generated_lines = generated_lines[:-n]
                logger.info(f"删除生成代码后部重复 {n} 行")
                break

    generated_code = '\n'.join(generated_lines)

    # 3. 花括号平衡处理
    if original_vuln_block is not None:
        target_diff = count_braces_diff(original_vuln_block)
        current_diff = count_braces_diff(generated_code)
        diff_delta = target_diff - current_diff  # 正数需删 '}'，负数需增 '}'

        if diff_delta > 0:
            need_remove = diff_delta
            while need_remove > 0:
                last_brace_idx = generated_code.rfind('}')
                if last_brace_idx == -1:
                    logger.warning(
                        f"生成代码中找不到 '}}' 用于删除，目标差值 {target_diff}，当前差值 {current_diff}"
                    )
                    break
                generated_code = generated_code[:last_brace_idx]
                need_remove -= 1
            generated_code = generated_code.rstrip()
            logger.info(
                f"生成代码末尾删除 {diff_delta} 个 '}}' 以匹配原始 mask 部分花括号差值 "
                f"(目标={target_diff}, 当前={current_diff})"
            )
        elif diff_delta < 0:
            need_add = -diff_delta
            generated_code = generated_code + '\n' + '\n'.join(['}'] * need_add)
            logger.info(
                f"生成代码末尾补充 {need_add} 个 '}}' 以匹配原始 mask 部分花括号差值 "
                f"(目标={target_diff}, 当前={current_diff})"
            )

    return generated_code


def apply_generated_code(repo_dir, vuln_file, generated_code, prefix_lines=None, suffix_lines=None, original_vuln_block=None):
    """将生成的代码替换到文件中的 <MASKED> 位置，并进行去重和花括号平衡校验"""
    file_path = os.path.join(repo_dir, vuln_file)
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # 去重 + 花括号平衡
    generated_code = deduplicate_and_balance_code(
        generated_code, prefix_lines=prefix_lines, suffix_lines=suffix_lines, original_vuln_block=original_vuln_block
    )

    lines = content.split('\n')
    new_lines = []
    replaced = False
    for line in lines:
        if '<MASKED>' in line:
            mask_indent = line[:len(line) - len(line.lstrip())]
            normalized_code = normalize_indent(generated_code, mask_indent)
            for g_line in normalized_code.split('\n'):
                new_lines.append(g_line)
            replaced = True
        else:
            new_lines.append(line)

    if not replaced:
        logger.error(f"文件中未找到 <MASKED> 标记: {file_path}")
        return False

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))
    return True
