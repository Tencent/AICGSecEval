import os
import re
import ast
import chardet
import subprocess
from argparse import ArgumentTypeError
from git import Repo
from pathlib import Path
from tempfile import TemporaryDirectory


DIFF_PATTERN = re.compile(r"^diff(?:.*)")
PATCH_PATTERN = re.compile(
    r"(?:diff[\w\_\.\ \/\-]+\n)?\-\-\-\s+a\/(?:.*?)\n\+\+\+\s+b\/(?:.*?)(?=diff\ |\-\-\-\ a\/|\Z)",
    re.DOTALL,
)
PATCH_FILE_PATTERN = re.compile(r"\-\-\-\s+a\/(?:.+)\n\+\+\+\s+b\/(?:.+)")
PATCH_HUNK_PATTERN = re.compile(
    r"\@\@\s+\-(\d+),(\d+)\s+\+(\d+),(\d+)\s+\@\@(.+?)(?=diff\ |\-\-\-\ a\/|\@\@\ \-|\Z)",
    re.DOTALL,
)


def get_first_idx(charlist):
    first_min = charlist.index("-") if "-" in charlist else len(charlist)
    first_plus = charlist.index("+") if "+" in charlist else len(charlist)
    return min(first_min, first_plus)


def get_last_idx(charlist):
    char_idx = get_first_idx(charlist[::-1])
    last_idx = len(charlist) - char_idx
    return last_idx + 1


def strip_content(hunk):
    first_chars = list(map(lambda x: None if not len(x) else x[0], hunk.split("\n")))
    first_idx = get_first_idx(first_chars)
    last_idx = get_last_idx(first_chars)
    new_lines = list(map(lambda x: x.rstrip(), hunk.split("\n")[first_idx:last_idx]))
    new_hunk = "\n" + "\n".join(new_lines) + "\n"
    return new_hunk, first_idx - 1


def get_hunk_stats(pre_start, pre_len, post_start, post_len, hunk, total_delta):
    stats = {"context": 0, "added": 0, "subtracted": 0}
    hunk = hunk.split("\n", 1)[-1].strip("\n")
    for line in hunk.split("\n"):
        if line.startswith("-"):
            stats["subtracted"] += 1
        elif line.startswith("+"):
            stats["added"] += 1
        else:
            stats["context"] += 1
    context = stats["context"]
    added = stats["added"]
    subtracted = stats["subtracted"]
    pre_len = context + subtracted
    post_start = pre_start + total_delta
    post_len = context + added
    total_delta = total_delta + (post_len - pre_len)
    return pre_start, pre_len, post_start, post_len, total_delta


def repair_patch(model_patch):
    if model_patch is None:
        return None
    model_patch = model_patch.lstrip("\n")
    new_patch = ""
    for patch in PATCH_PATTERN.findall(model_patch):
        total_delta = 0
        diff_header = DIFF_PATTERN.findall(patch)
        if diff_header:
            new_patch += diff_header[0] + "\n"
        patch_header = PATCH_FILE_PATTERN.findall(patch)[0]
        if patch_header:
            new_patch += patch_header + "\n"
        for hunk in PATCH_HUNK_PATTERN.findall(patch):
            pre_start, pre_len, post_start, post_len, content = hunk
            pre_start, pre_len, post_start, post_len, total_delta = get_hunk_stats(
                *list(map(lambda x: int(x) if x.isnumeric() else x, hunk)), total_delta
            )
            new_patch += (
                f"@@ -{pre_start},{pre_len} +{post_start},{post_len} @@{content}"
            )
    return new_patch


def extract_diff(response):
    """
    Extracts the diff from a response formatted in different ways
    """
    if response is None:
        return None
    diff_matches = []
    other_matches = []
    pattern = re.compile(r"\<([\w-]+)\>(.*?)\<\/\1\>", re.DOTALL)
    for code, match in pattern.findall(response):
        if code in {"diff", "patch"}:
            diff_matches.append(match)
        else:
            other_matches.append(match)
    pattern = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
    for code, match in pattern.findall(response):
        if code in {"diff", "patch"}:
            diff_matches.append(match)
        else:
            other_matches.append(match)
    if diff_matches:
        return diff_matches[0]
    if other_matches:
        return other_matches[0]
    return response.split("</s>")[0]


def is_test(name, test_phrases=None):
    if test_phrases is None:
        test_phrases = ["test", "tests", "testing"]
    words = set(re.split(r" |_|\/|\.", name.lower()))
    return any(word in words for word in test_phrases)



def resolve_module_to_file(module, level, root_dir):
    components = module.split(".")
    if level > 0:
        components = components[:-level]
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if dirpath.endswith(os.sep.join(components)):
            return [
                os.path.join(dirpath, filename)
                for filename in filenames
                if filename.endswith(".py")
            ]
    return []


def detect_encoding(filename):
    """
    Detect the encoding of a file
    """
    with open(filename, "rb") as file:
        rawdata = file.read()
    return chardet.detect(rawdata)["encoding"]


def list_files(root_dir, include_tests=False):
    """
    列出目录中所有支持的文件。
    
    参数:
        root_dir (str): 根目录路径
        include_tests (bool): 是否包含测试文件
        
    返回:
        list: 支持的文件路径列表
    """
    # 定义支持的文件扩展名
    supported_extensions = [
        # 前端文件
        ".html", ".htm", ".tpl", ".jade",  # HTML
        ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".astro",  # JavaScript/TypeScript
        
        # 后端文件
        ".py",  # Python
        ".java",  # Java
        # ".c", ".cpp", ".h", ".hpp", ".cc", ".cxx", ".hxx",  # C/C++
        ".go",  # Go
        # ".rb", ".erb", ".rake", ".gemspec",  # Ruby
        ".php", ".phtml", ".php3", ".php4", ".php5", ".phps",  # PHP
        # ".cs", ".csproj", ".sln",  # C#
        # ".rs", ".rlib",  # Rust
        # ".swift",  # Swift
        # ".kt", ".kts",  # Kotlin
        ".scala",  # Scala
        # ".groovy", ".gradle",  # Groovy
        # ".pl", ".pm", ".t",  # Perl
        # ".sh", ".bash", ".zsh", ".fish",  # Shell脚本
        
        # 配置文件
        ".json", ".yaml", ".yml", ".xml", ".toml", ".ini", ".conf",
        
        # 数据库
        # ".sql", ".sqlite", ".db",
        
        # 文档
        # ".md", ".txt", ".rst", ".adoc"
    ]
    
    files = []
    for ext in supported_extensions:
        for filename in Path(root_dir).rglob(f"*{ext}"):
            relative_path = filename.relative_to(root_dir).as_posix()
            # 如果需要排除测试文件且当前是测试文件，则跳过
            if not include_tests and is_test(relative_path):
                continue
            # 如果路径中包含隐藏文件或目录，则跳过
            if any(part.startswith(".") for part in Path(relative_path).parts):
                continue
            files.append(relative_path)
    return files
