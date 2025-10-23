import argparse
import asyncio
import datetime
import json
import logging
import os
import re
from pathlib import Path
import traceback
from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions
from bench.utils import clone_repo
from tqdm import tqdm
from git import Repo

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")


SYSTEM_PROMPT_CN = """
你是一个代码分析专家，分析完整项目中的代码并提供解读。
"""

USER_PROMPT_TEMPLATE_CN = """
我要重构文件 {filename} 第 {startline}-{endline} 行，请先给出关于这段代码的功能描述，然后给出理解这段代码需要的其它上下文代码，包括函数调用关系、全局变量、类属性、自定义类型等，涉及函数时需要输出整个函数的代码。你需要假定我在重构代码时只能访问你给的文件、代码片段。
你的输出需要包括以下内容：（1）关于这段代码的功能描述；（2）重构这段代码所需要的上下文所对应的文件路径，并给出具体的行号，涉及多行时给出起始和结束行号，输出顺序根据关联程度从高到低，文件路径要求相对项目根目录的相对路径。
请按照如下格式输出，不要包含其他无关信息和思考过程：
<description>
这里输出代码的功能描述
</description>

<context>
文件1的路径: 起始行号-结束行号
文件2的路径: 起始行号-结束行号
文件N的路径: 起始行号-结束行号
</context>
"""

SYSTEM_PROMPT = """
You are a code analysis expert. Analyze the code in the complete project and provide interpretations.
"""

USER_PROMPT_TEMPLATE = """
I want to refactor {filename}, lines {startline}-{endline}. First, provide a functional description of this code segment. Then provide all additional context needed to understand it, including function call relationships, global variables, class properties, and custom types. If any functions are involved, output the entire function code. Assume that during refactoring I can only access the files and code snippets you provide.

Your output must include: (1) a functional description of the code; (2) the file paths for all context required to refactor this code, with exact line numbers (use start–end ranges for multi-line spans). Order the files by relevance from highest to lowest. File paths must be relative to the project root.

Output strictly in this format, with no extra information or reasoning:
<description>
Write the functional description of the code here.
</description>

<context>
path/to/file1: start_line-end_line
path/to/file2: start_line-end_line
path/to/fileN: start_line-end_line
</context>
"""


async def query_claude_code(instance_id: str, repo_dir: str, vuln_filename: str, vuln_startline: int, vuln_endline: int, model: str):
    result_message = None

    async with ClaudeSDKClient(
        options=ClaudeCodeOptions(
            system_prompt=SYSTEM_PROMPT.strip(),
            max_turns=None,
            allowed_tools=["Read", "Grep"],
            disallowed_tools=["Bash(rm*)", "Write"],
            model=model,
            cwd=repo_dir,
            permission_mode="plan",
        )
    ) as client:
        prompt = USER_PROMPT_TEMPLATE.format(
            filename=vuln_filename,
            startline=vuln_startline,
            endline=vuln_endline,
        )
        await client.query(prompt)

        async for message in client.receive_messages():
            logging.info(f"收到消息：{message}")
            if type(message).__name__ == "ResultMessage":
                result_message = message.result
                break

    if not result_message:
        logging.error("没有收到结果消息")
        return

    try:
        description = re.search(
            r"<description>(.*?)</description>", result_message, re.DOTALL).group(1).strip()
        if description:
            logging.info(f"解析出功能描述：{description}")
        else:
            logging.error("没有解析出功能描述")
            return
    except Exception as e:
        logging.error(f"解析功能描述失败：{e}")
        return

    try:
        context = []
        raw_context = re.search(
            r"<context>(.*?)</context>", result_message, re.DOTALL).group(1).splitlines()
        for line in raw_context:
            line = line.strip()
            if not line:
                continue

            parts = line.split(":")
            if len(parts) != 2:
                continue

            filename = parts[0].strip()
            filepath = Path(repo_dir, filename)
            if not filepath.exists():
                logging.error(f"解析出文件 \"{filename}\"，但文件不存在，跳过")
                continue

            fileline = parts[1].strip().split("-")
            if len(fileline) == 1:
                startline = int(fileline[0])
                endline = int(fileline[0])
            else:
                startline = int(fileline[0])
                endline = int(fileline[1])
            if startline < 1 or endline < 1:
                logging.error(
                    f"解析出文件 \"{filename}\"，但起始行号（{startline}）或结束行号（{endline}）无效，跳过")
                continue
            if startline > endline:
                logging.error(
                    f"解析出文件 \"{filename}\"，但起始行号（{startline}）大于结束行号（{endline}），跳过")
                continue

            try:
                with open(filepath, "r") as f:
                    totallines = len(f.readlines())
                if startline > totallines or endline > totallines:
                    logging.error(
                        f"解析出文件 \"{filename}\"，但起始行号（{startline}）或结束行号（{endline}）超出文件范围（{totallines}），跳过")
                    continue
            except Exception as e:
                logging.error(f"解析出文件 \"{filename}\"，但读取文件失败，跳过，失败原因：{e}")
                continue

            context.append({
                "docid": filename,
                "startline": startline,
                "endline": endline,
            })

        if len(context) == 0:
            logging.error("没有解析出上下文")
            return

        logging.info(f"解析出上下文：{context}")

    except Exception as e:
        logging.error(f"解析上下文失败：{e}")
        return

    return {
        "instance_id": instance_id,
        "hits": context,
        "function_summary": description,
    }


async def main(dataset_path: str, retrieval_data_path: str, temp_dir: str, model: str, github_token: str):
    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        with open(retrieval_data_path, "r") as f:
            retrieval_data = json.load(f)
    except Exception as e:
        retrieval_data = []

    finish_instance_id = set([instance["instance_id"]
                             for instance in retrieval_data])

    rerun_instance_ids = []
    if os.path.exists("data/rerun_instances.txt"):
        with open("data/rerun_instances.txt", "r") as f:
            rerun_instance_ids = f.readlines()
        rerun_instance_ids = [instance_id.strip() for instance_id in rerun_instance_ids]
        if len(rerun_instance_ids) > 0:
            logging.info(f"Found {len(rerun_instance_ids)} instances to rerun.")
            for instance_id in rerun_instance_ids:
                if instance_id in finish_instance_id:
                    finish_instance_id.remove(instance_id)
            rerun_instances = [instance for instance in retrieval_data if instance["instance_id"] in rerun_instance_ids]
            for instance in rerun_instances:
                retrieval_data.remove(instance)

    dataset = []
    with open(dataset_path, "r") as f:
        for instance in json.load(f):
            if "instance_id" not in instance:
                continue
            if instance["instance_id"] in finish_instance_id:
                logging.info(f"数据集 \"{instance['instance_id']}\" 已经完成，跳过")
                continue
            dataset.append(instance)

    if len(dataset) == 0:
        logging.info("没有需要处理的数据集，退出")
        return

    
    failed_instances = []
    for instance in tqdm(dataset, desc="Claude Code Context Retrieval"):
        try:
            instance_id = instance["instance_id"]
            logging.info(f"开始处理数据集 \"{instance_id}\"")
            repo = instance["repo"]
            repo_dir = Path(temp_dir, f"{repo.replace('/', '__')}")
            clone_repo(repo, repo_dir, github_token, logging.getLogger())

            if instance["base_commit"] != "HEAD":
                logging.info(f"重置仓库到 {instance['base_commit']}")
                try:
                    git_repo = Repo(repo_dir)
                    if "branch_origin" in instance:
                        git_repo.git.fetch("origin", instance["branch_origin"])
                    git_repo.git.reset("--hard", instance["base_commit"])
                    git_repo.git.clean("-fdxq")
                except Exception as e:
                    logging.error(f"重置仓库失败，失败原因：{e}")
                    continue

            instance_data = await query_claude_code(
                instance_id=instance_id,
                repo_dir=repo_dir,
                vuln_filename=instance["vuln_file"],
                vuln_startline=instance["vuln_lines"][0],
                vuln_endline=instance["vuln_lines"][1] if len(
                    instance["vuln_lines"]) > 1 else instance["vuln_lines"][0],
                model=model
            )
            if not instance_data:
                failed_instances.append(instance_id)
                logging.error(f"数据集 \"{instance_id}\" 提取上下文失败，跳过")
                continue
            retrieval_data.append(instance_data)
        except Exception as e:
            logging.error(f"处理数据集 \"{instance_id}\" 失败，失败原因：{e}")
            print(traceback.format_exc())
            with open("outputs/claude_code_context_error.log", "a", encoding="utf-8") as error_file:
                error_file.write(
                    f"[{datetime.datetime.now()}] 处理数据集 \"{instance_id}\" 失败，失败原因：{e}\n")
                error_file.write(f"详细错误: {traceback.format_exc()}\n\n")
            continue
    
    with open(retrieval_data_path, "w") as f:
        json.dump(retrieval_data, f, indent=2)
    with open("outputs/claude_code_context_failed_instances.txt", "w", encoding="utf-8") as f:
        for instance_id in failed_instances:
            f.write(f"{instance_id}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--dataset_path", type=str, required=True)
    parser.add_argument("-r", "--retrieval_data_path", type=str, required=True)
    parser.add_argument("--temp_dir", type=str,
                        default="./outputs/data_retrieval_claude_code")
    parser.add_argument("-m", "--model", type=str,
                        default="claude-sonnet-4-20250514")
    parser.add_argument("--api-url", type=str,
                        default="https://ai.nengyongai.cn")
    parser.add_argument("--api-key", type=str, required=True)
    parser.add_argument("--github-token", type=str, default="git")
    args = parser.parse_args()

    os.environ["ANTHROPIC_BASE_URL"] = args.api_url
    os.environ["ANTHROPIC_AUTH_TOKEN"] = args.api_key

    asyncio.run(main(
        dataset_path=args.dataset_path,
        retrieval_data_path=args.retrieval_data_path,
        temp_dir=args.temp_dir,
        model=args.model,
        github_token=args.github_token
    ))
