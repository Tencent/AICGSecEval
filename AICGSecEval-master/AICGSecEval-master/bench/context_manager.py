import os
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

    def __init__(self, repo_path, base_commit, vuln_file=None, vuln_lines=None, verbose=False):
        self.repo_path = Path(repo_path).resolve().as_posix()
        self.base_commit = base_commit # commit hash 或 版本 tag 字符串，如"1.0.0"
        self.vuln_file = vuln_file
        self.vuln_lines = vuln_lines
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
    def get_vulnerability_block(self):
        all_lines = self.vulnerability_file_content.split('\n')
        
        context_start = self.vuln_lines[0]
        context_end = self.vuln_lines[-1]
        
        block = list()
        for i in range(context_start, context_end + 1):
            if 0 <= i - 1 < len(all_lines):
                line_content = all_lines[i - 1]
                block.append(f"{i} {line_content}")
        return "\n".join(block)

    def generate_function_summary(self): 
        """
        使用LLM为漏洞代码相关功能生成一句话摘要
            
        Returns:
            功能摘要字符串
        """
        logger.info("生成功能摘要...")

        openai_key = os.environ.get("LLM_API_KEY", None)
        if openai_key is None:
            raise ValueError(
                "Must provide an api key. Expected in OPENAI_API_KEY environment variable."
            )
        openai.base_url = "https://gnomic.nengyongai.cn/v1/"
        openai.api_key = openai_key

        # 构建提示词
        system_messages = (
            "Given a code file and a code snippet, summarize the functionality "
            "of the snippet in one sentence."
        )
        code_text = make_code_text({self.vuln_file: self.vulnerability_file_content})

        instructions = (
            "Please respond with a brief but clear summary that describes the main "
            "functionality of the code snippet, including any key operations or "
            "important logic. Keep the summary within 150 words."
        )
        text = [
            "<code>",
            code_text,
            "</code>",
            "",
            "<snippet>",
            self.get_vulnerability_block(),
            "</snippet>",
            instructions,
        ]
        user_message =  "\n".join(text)
        response = openai.chat.completions.create(
                model = "claude-opus-4-20250514", # 摘要生成用比较好的模型
                messages=[
                    {"role": "system", "content": system_messages},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.2,
                top_p=0.95,
            )
        function_summary = response.choices[0].message.content.strip()
        return function_summary
    

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
            self.repo.git.reset("--hard", self.base_commit)
            self.repo.git.clean("-fdxq")
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
            shutil.rmtree(tmp_dir)
        # 重新挖空
        self.masked_content = None
        self.get_masked_vulnerability_file()


    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def get_context_base_info(repo_dir, instance):
    with ContextManager(repo_dir, instance["base_commit"], instance["vuln_file"], instance["vuln_lines"]) as cm:
        # 策略 1： 直接返回漏洞文件内容
        return cm.get_vulnerability_file_content()

        # 策略 2： 返回漏洞代码块（前后扩展多行）
        # return cm.get_vulnerability_block()

def get_function_summary(repo_dir, instance):
    with ContextManager(repo_dir, instance["base_commit"], instance["vuln_file"], instance["vuln_lines"]) as cm:
        return cm.generate_function_summary()


