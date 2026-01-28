import os
import re
from pathlib import Path
from git import Repo
import logging
import openai
import shutil
import subprocess

from bench.generate_code import make_code_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)



class ContextManager:
    """
    A context manager for managing a Git repository at a specific commit.
    """

    def __init__(self, repo_path, base_commit, vuln_file=None, vuln_lines=None, branch_origin=None, verbose=False):
        self.repo_path = Path(repo_path).resolve().as_posix()
        self.base_commit = base_commit # commit hash 或 版本 tag 字符串，如"1.0.0"
        self.vuln_file = vuln_file
        self.vuln_lines = vuln_lines
        self.branch_origin = branch_origin
        self.verbose = verbose
        if self.base_commit != "HEAD":
            self.repo = Repo(self.repo_path)
        else:
            self.repo = None
        self.vulnerability_file_content = None
        self.masked_content = None

    def __enter__(self):
        if self.verbose:
            print(f"Switching to {self.base_commit}")
        try:
            if self.base_commit != "HEAD":
                if self.branch_origin:
                    self.repo.git.fetch("origin", self.branch_origin)
                
                self.repo.git.reset("--hard", self.base_commit)
                self.repo.git.clean("-fdxq")
            self.vulnerability_file_content = self.get_vulnerability_file_content()
        except Exception as e:
            logger.error(f"Failed to switch to {self.base_commit}")
            logger.error(e)
            raise e
        return self

    def get_readme_files(self):
        files = os.listdir(self.repo_path)
        files = list(filter(lambda x: os.path.isfile(x), files))
        files = list(filter(lambda x: x.lower().startswith("readme"), files))
        return files
    
    def get_vulnerability_info(self):
        # 返回漏洞文件和漏洞代码行号
        if self.vuln_file and self.vuln_lines:
            return {
                "vulnerable_file": self.vuln_file,
                "vulnerable_lines": self.vuln_lines
            }
        else:
            return None
        
    # 获取漏洞代码所在文件的所有内容
    def get_vulnerability_file_content(self):
        file_path = os.path.join(self.repo_path, self.vuln_file)
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            file_content = f.read()
        return file_content

    # 获取漏洞代码块
    def get_vulnerability_block(self, with_line_numbers: bool = True):
        """
        Return vulnerable block text.

        Args:
            with_line_numbers: keep original "line_no + space + code" formatting (default True).
                               For retrieval query, usually False is better.
        """
        all_lines = self.vulnerability_file_content.split('\n')

        if len(self.vuln_lines) != 2:
            raise ValueError("漏洞行信息出错，无法进行挖空处理")
        
        context_start = self.vuln_lines[0]
        context_end = self.vuln_lines[-1]
        
        block = list()
        for i in range(context_start, context_end + 1):
            if 0 <= i - 1 < len(all_lines):
                line_content = all_lines[i - 1]
                if with_line_numbers:
                    block.append(f"{i} {line_content}")
                else:
                    block.append(line_content)
        return "\n".join(block)

    def get_prefix_suffix(self, window: int = 120):
        """
        Extract prefix & suffix around vulnerable block for FIM-style prompting.

        window: number of lines kept before/after vulnerable region.
        Returns:
            prefix(str), suffix(str), vuln_block(str)  (all without line numbers)
        """
        if not self.vuln_lines or len(self.vuln_lines) != 2:
            return "", "", ""

        lines = (self.vulnerability_file_content or "").splitlines()
        start_line = self.vuln_lines[0]
        end_line = self.vuln_lines[-1]

        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), end_line)  # end is exclusive in python slice

        prefix_start = max(0, start_idx - window)
        suffix_end = min(len(lines), end_idx + window)

        prefix = "\n".join(lines[prefix_start:start_idx])
        vuln_block = "\n".join(lines[start_idx:end_idx])
        suffix = "\n".join(lines[end_idx:suffix_end])
        return prefix, suffix, vuln_block

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        if text is None:
            return ""
        t = text.strip()
        # remove ```lang ... ``` fences
        t = re.sub(r"^```[A-Za-z0-9_+-]*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
        # sometimes models wrap with <code> tags
        t = t.replace("<code>", "").replace("</code>", "")
        return t.strip()

    def generate_function_summary(self, base_url, openai_key, model_name: str = None): 
        """
        使用LLM为漏洞代码相关功能生成一句话摘要
        
        Returns:
            功能摘要字符串
        """
        logger.info("生成功能摘要...")

        if openai_key is None:
            raise ValueError(
                "Must provide an api key. Expected in LLM_API_KEY environment variable or --openai_key."
            )
        openai.base_url = base_url
        openai.api_key = openai_key

        # model selection: allow env override
        model = (
            model_name
            or os.getenv("NENGYONGAI_SUMMARY_MODEL")
            or os.getenv("NENGYONGAI_MODEL")
            or "claude-sonnet-4-20250514"
        )

        # 构建提示词
        system_messages = (
            "Given a code file and a code snippet, summarize the functionality "
            "of the snippet."
        )
        code_text = make_code_text({self.vuln_file: self.vulnerability_file_content})

        instructions = (
            "Please respond with a brief but clear summary that describes the main "
            "functionality of the code snippet, including any key operations or "
            "important logic. Keep the summary within 200 words."
        )
        text = [
            "<code>",
            code_text,
            "</code>",
            "",
            "<snippet>",
            self.get_vulnerability_block(with_line_numbers=True),
            "</snippet>",
            instructions,
        ]
        user_message =  "\n".join(text)
        response = openai.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_messages},
                    {"role": "user", "content": user_message},
                ]
            )
        function_summary = response.choices[0].message.content.strip()
        return function_summary

    def generate_hypothetical_patch(
        self,
        base_url: str,
        openai_key: str,
        model_name: str = None,
        window: int = 120,
        max_gen_token: int = 256,
        temperature: float = 0.2,
    ) -> str:
        """
        ProCC-style Hypothetical Line / Completion:
        Use <PRE>/<SUF>/<MID> prompt to generate a plausible secure replacement code
        for the vulnerable region, then return it as retrieval query text.

        Returns:
            str: hypothetical patch text (no markdown fences)
        """
        if openai_key is None:
            raise ValueError(
                "Must provide an api key. Expected in LLM_API_KEY environment variable or --openai_key."
            )
        openai.base_url = base_url
        openai.api_key = openai_key

        model = model_name or os.getenv("NENGYONGAI_MODEL") or "claude-sonnet-4-20250514"

        prefix, suffix, _vuln = self.get_prefix_suffix(window=window)

        system_messages = (
            "You are a senior software security engineer. "
            "Given a code prefix and suffix around a vulnerable region, "
            "write the secure replacement code that should fill the missing region. "
            "Output ONLY the code that belongs in <MID> (no explanations, no markdown)."
        )
        user_message = f"""<PRE>
{prefix}
<SUF>
{suffix}
<MID>
"""

        response = openai.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_messages},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_gen_token,
        )
        text = response.choices[0].message.content or ""
        text = self._strip_code_fences(text)

        # Truncate overly long outputs (helps Lucene maxClauseCount)
        if len(text) > 4000:
            text = text[:4000]

        return text.strip()
    

    def get_masked_vulnerability_file(self):
        """
        获取漏洞文件内容，但将漏洞行挖空（替换为占位符）。
        同时修改磁盘上的源文件。
        
        返回:
            str: 挖空漏洞行的文件内容
        """

        if self.masked_content is not None:
            return {self.vuln_file:self.masked_content}
            
        # 将文件内容分割为行
        lines = self.vulnerability_file_content.split('\n')
        
        # 创建挖空后的行列表
        masked_lines = []
        
        # 检查是否提供了漏洞行信息
        if not self.vuln_lines or len(self.vuln_lines) < 2:
            raise ValueError("漏洞行信息不完整，无法进行挖空处理")
            
        # 获取漏洞代码的起始行和终止行
        start_line = self.vuln_lines[0]
        end_line = self.vuln_lines[-1]
        
        # 遍历所有行，对漏洞行进行挖空处理
        for i, line in enumerate(lines, 1):
            if start_line <= i <= end_line:
                # 对于漏洞范围内的第一行，添加占位符
                if i == start_line:
                    # 保持原有缩进
                    first_non_whitespace = len(line) - len(line.lstrip())
                    original_indent = line[:first_non_whitespace]
                    masked_lines.append(original_indent + '<MASKED>')
                # 其他漏洞行不添加
            else:
                # 非漏洞行保持不变
                masked_lines.append(line)
                
        # 将行重新组合为文件内容
        self.masked_content = '\n'.join(masked_lines)
        
        # 修改磁盘上的源文件
        try:
            file_path = os.path.join(self.repo_path, self.vuln_file)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.masked_content)
            logger.info(f"已修改磁盘上的源文件: {file_path}")
        except Exception as e:
            logger.error(f"修改磁盘上的源文件失败: {str(e)}")
        
        return {self.vuln_file:self.masked_content}
        

    def reset_repo(self, raw_repo_dir, target_repo_dir):
        # 重置项目
        if self.repo is not None:
            with open(os.path.join(target_repo_dir, "response.txt"), "r") as f:
                response = f.read()
            raw_diff_file = os.path.join(target_repo_dir, "raw_patch.diff")
            flag = os.path.exists(raw_diff_file)
            if flag:
                with open(raw_diff_file, "r") as f:
                    raw_diff = f.read()
            
            if self.branch_origin:
                self.repo.git.fetch("origin", self.branch_origin)
            self.repo.git.reset("--hard", self.base_commit)
            self.repo.git.clean("-fdxq")
            
            with open(os.path.join(target_repo_dir, "response.txt"), "w") as f:
                f.write(response)
            if flag:
                with open(raw_diff_file, "w") as f:
                    f.write(raw_diff)
        else:
            # 重新复制原始目录
            target_dir_name = os.path.basename(os.path.normpath(target_repo_dir))
            target_repo_parent_dir = os.path.dirname(os.path.normpath(target_repo_dir))
            tmp_dir = os.path.join(target_repo_parent_dir, target_dir_name+"__tmp")
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir)
            os.rename(target_repo_dir, tmp_dir)
            shutil.copytree(raw_repo_dir, target_repo_dir)
            source_patch_file = os.path.join(tmp_dir, "patch.diff")
            target_patch_file = os.path.join(target_repo_dir, "patch.diff")
            shutil.copy(source_patch_file, target_patch_file)

            # 原始响应内容 & patch 拷贝
            raw_response_file = os.path.join(tmp_dir, "response.txt")
            raw_patch_file = os.path.join(tmp_dir, "raw_patch.diff")
            if os.path.exists(raw_response_file):
                target_response_file = os.path.join(target_repo_dir, "response.txt")
                shutil.copy(raw_response_file, target_response_file)
                print("拷贝文件了！！！！！")
            if os.path.exists(raw_patch_file):
                target_patch_file = os.path.join(target_repo_dir, "raw_patch.diff")
                shutil.copy(raw_patch_file, target_patch_file)

            shutil.rmtree(tmp_dir)
        # 重新挖空
        self.masked_content = None
        self.get_masked_vulnerability_file()


    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def get_context_base_info(
    repo_dir,
    instance,
    context_strategy: str = "file",
    base_url: str = None,
    openai_key: str = None,
    procc_model: str = None,
    procc_window: int = 120,
    procc_max_gen_token: int = 256,
    procc_temperature: float = 0.2,
):
    """
    Build retrieval query base info (context) using a selectable strategy.

    Strategies:
      - file:  use full vulnerable file content (current default, backward compatible)
      - block: use only vulnerable block (no line numbers)
      - procc: generate hypothetical replacement code using <PRE>/<SUF>/<MID> (ProCC completion view)
    """
    if "branch_origin" in instance:
        branch_origin = instance["branch_origin"]
    else:
        branch_origin = None

    strategy = (context_strategy or "file").lower().strip()

    with ContextManager(repo_dir, instance["base_commit"], instance["vuln_file"], instance["vuln_lines"], branch_origin) as cm:
        if strategy == "file":
            return cm.get_vulnerability_file_content()

        if strategy == "block":
            return cm.get_vulnerability_block(with_line_numbers=False)

        if strategy == "procc":
            # LLM config
            base_url = base_url or os.getenv("LLM_BASE_URL") or "https://ai.nengyongai.cn/v1/"
            openai_key = openai_key or os.getenv("LLM_API_KEY")
            model = procc_model or os.getenv("NENGYONGAI_MODEL") or "claude-sonnet-4-20250514"

            try:
                hypo = cm.generate_hypothetical_patch(
                    base_url=base_url,
                    openai_key=openai_key,
                    model_name=model,
                    window=int(procc_window),
                    max_gen_token=int(procc_max_gen_token),
                    temperature=float(procc_temperature),
                )
            except Exception as e:
                logger.error(f"ProCC hypothetical patch generation failed, fallback to file strategy. err={e}")
                hypo = ""

            if hypo is None or len(hypo.strip()) == 0:
                return cm.get_vulnerability_file_content()
            return hypo

        raise ValueError(f"Unknown context_strategy: {context_strategy}. Use one of: file, block, procc")


def get_function_summary(repo_dir, instance, base_url, openai_key, model_name: str = None):
    if "branch_origin" in instance:
        branch_origin = instance["branch_origin"]
    else:
        branch_origin = None
    with ContextManager(repo_dir, instance["base_commit"], instance["vuln_file"], instance["vuln_lines"], branch_origin) as cm:
        return cm.generate_function_summary(base_url, openai_key, model_name=model_name)
