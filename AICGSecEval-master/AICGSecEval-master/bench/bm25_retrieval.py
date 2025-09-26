import json
import os
import ast
import shutil
import traceback
import subprocess
from filelock import FileLock
from typing import Any
from pyserini.search.lucene import LuceneSearcher
from git import Repo
from pathlib import Path
from tqdm.auto import tqdm
from argparse import ArgumentParser


from bench.context_manager import ContextManager, get_context_base_info, get_function_summary
from bench.utils import list_files

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def file_name_and_contents(filename, relative_path):
    text = relative_path + "\n"
    with open(filename,encoding="utf-8",errors="ignore") as f:
        text += f.read()
    return text


# def file_name_and_documentation(filename, relative_path):
#     text = relative_path + "\n"
#     try:
#         with open(filename) as f:
#             node = ast.parse(f.read())
#         data = ast.get_docstring(node)
#         if data:
#             text += f"{data}"
#         for child_node in ast.walk(node):
#             if isinstance(
#                 child_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
#             ):
#                 data = ast.get_docstring(child_node)
#                 if data:
#                     text += f"\n\n{child_node.name}\n{data}"
#     except Exception as e:
#         logger.error(e)
#         logger.error(f"Failed to parse file {str(filename)}. Using simple filecontent.")
#         with open(filename) as f:
#             text += f.read()
#     return text


DOCUMENT_ENCODING_FUNCTIONS = {
    "file_name_and_contents": file_name_and_contents,
    # "file_name_and_documentation": file_name_and_documentation,
}


def clone_repo(repo, root_dir, token):
    """
    Clones a GitHub repository to a specified directory.

    Args:
        repo (str): The GitHub repository to clone.
        root_dir (str): The root directory to clone the repository to.
        token (str): The GitHub personal access token to use for authentication.

    Returns:
        Path: The path to the cloned repository directory.
    """
    repo_dir = Path(root_dir, f"{repo.replace('/', '__')}")

    if not repo_dir.exists():
        repo_url = f"https://{token}@github.com/{repo}.git"
        logger.info(f"Cloning {repo} {os.getpid()}")
        Repo.clone_from(repo_url, repo_dir)
    return repo_dir


def build_documents(repo_dir, commit, document_encoding_func):
    """
    Builds a dictionary of documents from a given repository directory and commit.
    """
    documents = dict()

    filenames = list_files(repo_dir, include_tests=False)
    for relative_path in filenames:
        filename = os.path.join(repo_dir, relative_path)
        if not os.path.exists(filename) or os.path.isdir(filename):
            continue
        text = document_encoding_func(filename, relative_path)
        documents[relative_path] = text
    return documents


def make_index(
    repo_dir,
    root_dir,
    commit,
    document_encoding_func,
    python,
    instance_id,
):
    """
    Builds an index for a given set of documents using Pyserini.

    Args:
        repo_dir (str): The path to the repository directory.
        root_dir (str): The path to the root directory.
        query (str): The query to use for retrieval.
        commit (str): The commit hash to use for retrieval.
        document_encoding_func (function): The function to use for encoding documents.
        python (str): The path to the Python executable.
        instance_id (int): The ID of the current instance.

    Returns:
        index_path (Path): The path to the built index.
    """
    index_path = Path(root_dir, f"index__{str(instance_id)}", "index")
    if index_path.exists():
        return index_path
    thread_prefix = f"(pid {os.getpid()}) "

    documents_path = Path(root_dir, instance_id, "documents.jsonl")
    if not documents_path.parent.exists():
        documents_path.parent.mkdir(parents=True)
    documents = build_documents(repo_dir, commit, document_encoding_func)
    with open(documents_path, "w") as docfile:
        for relative_path, contents in documents.items():
            print(
                json.dumps({"id": relative_path, "contents": contents}),
                file=docfile,
                flush=True,
            )
    cmd = [
        python,
        "-m",
        "pyserini.index.lucene",
        "--collection",
        "JsonCollection",
        "--generator",
        "DefaultLuceneDocumentGenerator",
        "--threads",
        "2",
        "--input",
        documents_path.parent.as_posix(),
        "--index",
        index_path.as_posix(),
        "--storePositions",
        "--storeDocvectors",
        "--storeRaw",
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        output, error = proc.communicate()
    except KeyboardInterrupt:
        proc.kill()
        raise KeyboardInterrupt
    if proc.returncode == 130:
        logger.warning(thread_prefix + "Process killed by user")
        raise KeyboardInterrupt
    if proc.returncode != 0:
        logger.error(f"return code: {proc.returncode}")
        raise Exception(
            thread_prefix
            + f"Failed to build index for {instance_id} with error {error}"
        )
    return index_path


def get_remaining_instances(instances, output_file):
    """
    Filters a list of instances to exclude those that have already been processed and saved in a file.

    Args:
        instances (List[Dict]): A list of instances, where each instance is a dictionary with an "instance_id" key.
        output_file (Path): The path to the file where the processed instances are saved.

    Returns:
        List[Dict]: A list of instances that have not been processed yet.
    """
    # 如果输出文件不存在，直接返回所有实例
    if not output_file.exists():
        return instances
    
    # 读取已处理的实例ID
    instance_ids = set()
    with FileLock(output_file.as_posix() + ".lock"):
        with open(output_file) as f:
            instance_ids = {json.loads(line)["instance_id"] for line in f}
        
        if instance_ids:
            logger.warning(
                f"Found {len(instance_ids)} existing instances in {output_file}. Will skip them."
            )
    
    # 过滤出未处理的实例
    return [instance for instance in instances if instance["instance_id"] not in instance_ids]


def search(instance, index_path):
    """
    Searches for relevant documents in the given index for the given instance.

    Args:
        instance (dict): The instance to search for.
        index_path (str): The path to the index to search in.

    Returns:
        dict: A dictionary containing the instance ID and a list of hits, where each hit is a dictionary containing the
        document ID and its score.
    """
    
    instance_id = instance["instance_id"]
    searcher = LuceneSearcher(index_path.as_posix())
    # 提取上下文的基础信息
    query = "Functionality Summary: "
    query+=instance["function_summary"]+"\n"
    query+=instance["context_base_info"]
    cutoff = len(query)
    while True:
        try:
            hits = searcher.search(
                query[:cutoff],
                k=20,
                remove_dups=True,
            )
        except Exception as e:
            if "maxClauseCount" in str(e):
                cutoff = int(round(cutoff * 0.8))
                continue
            else:
                raise e
        break
    results = {"instance_id": instance_id, "hits": []}
    for hit in hits:
        results["hits"].append({"docid": hit.docid, "score": hit.score})
    results["function_summary"] = instance["function_summary"]
    
    # 获取上下文查询的输出信息
    return results


def search_indexes(remaining_instance, output_file, all_index_paths):
    """
    Searches the indexes for the given instances and writes the results to the output file.

    Args:
        remaining_instance (list): A list of instances to search for.
        output_file (str): The path to the output file to write the results to.
        all_index_paths (dict): A dictionary mapping instance IDs to the paths of their indexes.
    """
    for instance in tqdm(remaining_instance, desc="Retrieving"):
        instance_id = instance["instance_id"]
        if instance_id not in all_index_paths:
            continue
        index_path = all_index_paths[instance_id]
        results = search(instance, index_path)
        if results is None:
            continue
        with FileLock(output_file.as_posix() + ".lock"):
            with open(output_file, "a") as out_file:
                print(json.dumps(results), file=out_file, flush=True)


def get_missing_ids(instances, output_file):
    with open(output_file) as f:
        written_ids = set()
        for line in f:
            instance = json.loads(line)
            instance_id = instance["instance_id"]
            written_ids.add(instance_id)
    missing_ids = set()
    for instance in instances:
        instance_id = instance["instance_id"]
        if instance_id not in written_ids:
            missing_ids.add(instance_id)
    return missing_ids


def get_index_paths_worker(
    instance,
    root_dir_name,
    document_encoding_func,
    python,
    token,
):
    index_path = None
    repo = instance["repo"]
    commit = instance["base_commit"]
    instance_id = instance["instance_id"]
    
    print(f"Cloning {repo} to {root_dir_name}")
    repo_dir = clone_repo(repo, root_dir_name, token)
    print(f"Cloned {repo} to {repo_dir}")
    instance["repo_dir"] = repo_dir
    # 切换到对应 commit 后，获取上下文查询的输出信息
    instance["context_base_info"] = get_context_base_info(repo_dir, instance)
    instance["function_summary"] = get_function_summary(repo_dir, instance)
    print(f"Got function summary for {repo}/{commit} (instance {instance_id})")
    index_path = make_index(
        repo_dir=repo_dir,
        root_dir=root_dir_name,
        commit=commit,
        document_encoding_func=document_encoding_func,
        python=python,
        instance_id=instance_id,
    )
    
    return instance_id, index_path


def get_index_paths(
    remaining_instances: list[dict[str, Any]],
    root_dir_name: str,
    document_encoding_func: Any,
    python: str,
    token: str,
    output_file: str,
) -> dict[str, str]:
    """
    Retrieves the index paths for the given instances using multiple processes.

    Args:
        remaining_instances: A list of instances for which to retrieve the index paths.
        root_dir_name: The root directory name.
        document_encoding_func: A function for encoding documents.
        python: The path to the Python executable.
        token: The token to use for authentication.
        output_file: The output file.
        num_workers: The number of worker processes to use.

    Returns:
        A dictionary mapping instance IDs to index paths.
    """
    all_index_paths = dict()
    for instance in tqdm(remaining_instances, desc="Indexing"):
        instance_id, index_path = get_index_paths_worker(
            instance=instance,
            root_dir_name=root_dir_name,
            document_encoding_func=document_encoding_func,
            python=python,
            token=token,
        )
        if index_path is None:
            continue
        all_index_paths[instance_id] = index_path
    return all_index_paths


def get_root_dir(dataset_name, output_dir, document_encoding_style):
    root_dir = Path(output_dir, dataset_name, "indexes_"+document_encoding_style)
    if not root_dir.exists():
        root_dir.mkdir(parents=True, exist_ok=True)
    root_dir_name = root_dir
    return root_dir, root_dir_name


def main(
    dataset_name,
    instances,
    document_encoding_style,
    token,
    output_dir,
    leave_indexes,
):
    document_encoding_func = DOCUMENT_ENCODING_FUNCTIONS[document_encoding_style]

    # 环境检查
    python = subprocess.run("which python3", shell=True, capture_output=True)
    python = python.stdout.decode("utf-8").strip()
    output_file = Path(
        output_dir, dataset_name, document_encoding_style + ".retrieval.jsonl"
    )

    dst_file = Path("data",dataset_name+"_retrieval.jsonl")
    # 断点重连
    remaining_instances = get_remaining_instances(instances, dst_file)
    root_dir, root_dir_name = get_root_dir(
        dataset_name, output_dir, document_encoding_style
    )

    # 代码索引生成与检索
    try:
        # code indexing 
        all_index_paths = get_index_paths(
            remaining_instances,
            root_dir_name,
            document_encoding_func,
            python,
            token,
            output_file,
        )
    except KeyboardInterrupt:
        logger.info(f"Cleaning up {root_dir}")
        del_dirs = list(root_dir.glob("repo__*"))
        if leave_indexes:
            index_dirs = list(root_dir.glob("index__*"))
            del_dirs += index_dirs
        for dirname in del_dirs:
            shutil.rmtree(dirname, ignore_errors=True)
    logger.info(f"Finished indexing {len(all_index_paths)} instances")
    # 检索索引
    search_indexes(remaining_instances, output_file, all_index_paths)
    # 获取未检索的索引
    missing_ids = get_missing_ids(instances, output_file)
    logger.warning(f"Missing indexes for {len(missing_ids)} instances.")
    logger.info(f"Saved retrieval results to {output_file}")

    # 拷贝索引结果到 data 目录
    shutil.copy2(output_file, dst_file)

    # 清理所有中间数据
    shutil.rmtree(output_dir, ignore_errors=True)

    # 仅清理索引，不清理 repo 目录
    # del_dirs = list(root_dir.glob("repo__*"))
    # logger.info(f"Cleaning up {root_dir}")
    # if leave_indexes:
    #     index_dirs = list(root_dir.glob("index__*"))
    #     del_dirs += index_dirs
    # for dirname in del_dirs:
    #     shutil.rmtree(dirname, ignore_errors=True)
