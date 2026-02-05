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
from bench.utils import list_files, clone_repo

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def file_name_and_contents(filename, relative_path):
    text = relative_path + "\n"
    with open(filename,encoding="utf-8",errors="ignore") as f:
        text += f.read()
    return text


DOCUMENT_ENCODING_FUNCTIONS = {
    "file_name_and_contents": file_name_and_contents,
}


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
    """
    if not output_file.exists():
        return instances
    
    instance_ids = set()
    with open(output_file,"r") as f:
        content = f.read()
        data = json.loads(content)
    instance_ids = {item["instance_id"] for item in data}
    if instance_ids:
        logger.info(f"Found {len(instance_ids)} existing instances in {output_file}. Will skip them.")
    
    res =  [instance for instance in instances if instance["instance_id"] not in instance_ids]

    if os.path.exists("data/rerun_instances.txt"):
        with open("data/rerun_instances.txt", "r") as f:
            rerun_instance_ids = f.readlines()
        rerun_instance_ids = [instance_id.strip() for instance_id in rerun_instance_ids]
        if len(rerun_instance_ids) > 0:
            logger.info(f"Found {len(rerun_instance_ids)} instances to rerun.")
            rerun_instances = [instance for instance in instances if instance["instance_id"] in rerun_instance_ids]
            res += rerun_instances
    return res

def search(instance, index_path):
    """
    Searches for relevant documents in the given index for the given instance.
    """
    
    instance_id = instance["instance_id"]
    searcher = LuceneSearcher(index_path.as_posix())
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
    return results


def search_indexes(remaining_instance, output_file, all_index_paths):
    """
    Searches the indexes for the given instances and writes the results to the output file.
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
    github_token,
    base_url,
    openai_key,
    context_strategy: str = "file",
    procc_model: str = None,
    procc_window: int = 120,
    procc_max_gen_token: int = 256,
    procc_temperature: float = 0.2,
    summary_model: str = None,
):
    index_path = None
    repo = instance["repo"]
    commit = instance["base_commit"]
    instance_id = instance["instance_id"]
    
    print(f"Cloning {repo} to {root_dir_name}")
    repo_dir = Path(root_dir_name, f"{repo.replace('/', '__')}")
    clone_repo(repo, repo_dir, logger, github_token)
    print(f"Cloned {repo} to {repo_dir}")
    instance["repo_dir"] = repo_dir

    instance["context_base_info"] = get_context_base_info(
        repo_dir,
        instance,
        context_strategy=context_strategy,
        base_url=base_url,
        openai_key=openai_key,
        procc_model=procc_model,
        procc_window=procc_window,
        procc_max_gen_token=procc_max_gen_token,
        procc_temperature=procc_temperature,
    )
    instance["function_summary"] = get_function_summary(repo_dir, instance, base_url, openai_key, model_name=summary_model)
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
    output_file: str,
    github_token: str,
    base_url: str,
    openai_key: str,
    context_strategy: str = "file",
    procc_model: str = None,
    procc_window: int = 120,
    procc_max_gen_token: int = 256,
    procc_temperature: float = 0.2,
    summary_model: str = None,
) -> dict[str, str]:
    all_index_paths = dict()
    error_file = Path("outputs", "bm25_error.log")
    for instance in tqdm(remaining_instances, desc="Indexing"):
        try:
            instance_id, index_path = get_index_paths_worker(
                instance=instance,
                root_dir_name=root_dir_name,
                document_encoding_func=document_encoding_func,
                python=python,
                github_token=github_token,
                base_url=base_url,
                openai_key=openai_key,
                context_strategy=context_strategy,
                procc_model=procc_model,
                procc_window=procc_window,
                procc_max_gen_token=procc_max_gen_token,
                procc_temperature=procc_temperature,
                summary_model=summary_model,
            )
            if index_path is None:
                continue
            all_index_paths[instance_id] = index_path
        except Exception as e:
            with open(error_file, "a") as f:
                f.write(f"{instance} \n {str(e)}\n")
    return all_index_paths


def get_root_dir(dataset_name, output_dir, document_encoding_style):
    root_dir = Path(output_dir, dataset_name, "indexes_"+document_encoding_style)
    if not root_dir.exists():
        root_dir.mkdir(parents=True, exist_ok=True)
    root_dir_name = root_dir
    return root_dir, root_dir_name


def load_data(file_path):
    data = []
    if not os.path.exists(file_path):
        return data
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def main(
    dataset_name,
    instances,
    document_encoding_style,
    output_dir,
    leave_indexes,
    github_token,
    base_url,
    openai_key,
    context_strategy: str = "file",
    procc_model: str = None,
    procc_window: int = 120,
    procc_max_gen_token: int = 256,
    procc_temperature: float = 0.2,
    summary_model: str = None,
):
    document_encoding_func = DOCUMENT_ENCODING_FUNCTIONS[document_encoding_style]

    python = subprocess.run("which python3", shell=True, capture_output=True)
    python = python.stdout.decode("utf-8").strip()
    output_file = Path(
        output_dir, dataset_name, document_encoding_style + ".retrieval.jsonl"
    )

    strategy = (context_strategy or "file").lower().strip()
    suffix = "" if strategy == "file" else f"_{strategy}"
    dst_file = Path("data", f"{dataset_name}_context_bm25{suffix}.jsonl")

    remaining_instances = get_remaining_instances(instances, dst_file)
    root_dir, root_dir_name = get_root_dir(
        dataset_name, output_dir, document_encoding_style
    )

    try:
        all_index_paths = get_index_paths(
            remaining_instances,
            root_dir_name,
            document_encoding_func,
            python,
            output_file,
            github_token,
            base_url,
            openai_key,
            context_strategy=context_strategy,
            procc_model=procc_model,
            procc_window=procc_window,
            procc_max_gen_token=procc_max_gen_token,
            procc_temperature=procc_temperature,
            summary_model=summary_model,
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

    search_indexes(remaining_instances, output_file, all_index_paths)
    logger.info(f"Saved retrieval results to {output_file}")

    output_data = load_data(output_file)
    
    if os.path.exists(dst_file):
        with open(dst_file,"r") as f:
            content = f.read()
            dst_data = json.loads(content)
    else:
        dst_data = []

    merged_dict = {}
    for item in dst_data:
        if isinstance(item, dict) and "instance_id" in item:
            merged_dict[item["instance_id"]] = item
    for item in output_data:
        if isinstance(item, dict) and "instance_id" in item:
            merged_dict[item["instance_id"]] = item
    dst_data = list(merged_dict.values())
    with open(dst_file, 'w', encoding='utf-8') as f:
        json.dump(dst_data, f, ensure_ascii=False, indent=2)

    shutil.rmtree(output_dir, ignore_errors=True)

    tmp_lock_file = Path(str(dst_file)+".lock")
    if tmp_lock_file.exists():
        tmp_lock_file.unlink()
