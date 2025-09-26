import datetime
import json
import os
import logging
from pathlib import Path
import time
import traceback
from git import Repo
from tqdm import tqdm
import shutil

from bench import generate_code
from bench.generate_code import make_codegen_prompt
from bench.context_manager import ContextManager
from bench.utils import extract_diff, repair_patch

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_data(file_path):
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():  # 跳过空行
                data.append(json.loads(line))
    return data


def clone_repo(repo, save_repo_dir, token):
    if not save_repo_dir.exists():
        repo_url = f"https://{token}@github.com/{repo}.git"
        logger.info(f"Cloning {repo} {os.getpid()}")
        Repo.clone_from(repo_url, save_repo_dir)
    return save_repo_dir


def process_instance(instance, model_name, base_url, api_key, max_context_token, max_gen_token, **model_args):
    repo_dir = instance["repo_dir"]
    hits = instance["hits"]
    function_summary = instance["function_summary"]
    
    with ContextManager(repo_dir, instance["base_commit"], instance["vuln_file"], instance["vuln_lines"]) as cm:
        # 获取 instance 中的 system_message 和 user_message
        readme_files = cm.get_readme_files()
        # 修改磁盘上的文件
        masked_vulnerability_file = cm.get_masked_vulnerability_file()
        
        context_files = generate_code.ingest_files([os.path.join(repo_dir, x["docid"]) for x in hits])
        system_message, user_message = make_codegen_prompt(max_context_token, readme_files, 
                                                           masked_vulnerability_file, context_files, function_summary)
        
        # 调用 LLM 生成代码
        response = generate_code.call_llm(base_url, api_key, model_name, system_message, user_message, 
                                          max_gen_token, **model_args)
        model_patch = extract_diff(response)

        if model_patch is None or len(model_patch)==0:
            logger.error(f"模型生成补丁为空")
            print(response)
            return False
        
        # 尝试应用补丁
        success = try_patch(model_patch, repo_dir, cm, instance)
        return success


def try_patch(model_patch, repo_dir, cm, instance):
    # 应用补丁，每次尝试需要重置项目
    # 第一次尝试
    success = generate_code.apply_patch(model_patch, repo_dir, generate_code.GIT_APPLY_CMDS[0])
    if success:
        return True

    # 如果第一次尝试失败，则重置项目并尝试第二次
    cm.reset_repo(instance["raw_repo_dir"], repo_dir)
    success = generate_code.apply_patch(model_patch, repo_dir, generate_code.GIT_APPLY_CMDS[1])
    if success:
        return True

    # 如果第二次尝试失败，则重置项目，修复补丁，并尝试第三次
    cm.reset_repo(instance["raw_repo_dir"], repo_dir)
    logger.info(f"原始应用补丁失败，尝试修复补丁")
    repaired_patch = repair_patch(model_patch)
    if len(repaired_patch)==0:
        logger.error(f"修复后补丁为空")
        return False
    success = generate_code.apply_patch(repaired_patch, repo_dir, generate_code.GIT_APPLY_CMDS[0])
    if success:
        return True
    
    # 第四次尝试
    cm.reset_repo(instance["raw_repo_dir"], repo_dir)
    success = generate_code.apply_patch(repaired_patch, repo_dir, generate_code.GIT_APPLY_CMDS[1])
    if not success:
        logger.error(f"修复后应用补丁仍然失败")
        return False
    else:
        logger.info(f"修复后应用补丁成功")
        return True



def process_all_instances(raw_instances, retrieval_instances, model_name, batch_id, base_url, api_key, 
                          max_context_token, max_gen_token, 
                          github_token, raw_repo_dir, generated_code_dir, num_cycles, **model_args):
    # 创建模型输出目录
    model_output_dir = Path(generated_code_dir) / f"{model_name}__{batch_id}"
    model_output_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建已处理实例的记录文件
    processed_instances_file = os.path.join(model_output_dir, "processed_instances.json")
    processed_instances = {}
    
    # 如果记录文件存在，读取已处理的实例信息进行断点重连
    if os.path.exists(processed_instances_file):
        with open(processed_instances_file, 'r', encoding='utf-8') as f:
            processed_instances = json.load(f)
        logger.info(f"已加载处理记录，共 {len(processed_instances)} 个实例")
    
    # 过滤已处理的实例
    filtered_instances = filter_instances(raw_instances, processed_instances, num_cycles)
    if len(filtered_instances) < len(raw_instances):
        processed_sum = len(raw_instances) - len(filtered_instances)
        logger.info(f"共 {len(raw_instances)} 个实例，其中 {processed_sum} 个已被{model_name}处理，{len(filtered_instances)} 个待处理")

    # 获取 seed 实例和 mutation 实例的映射
    CVE_map_instanceid, seed_instance_map_repo = get_seed_mutation_map(raw_instances)

    # 获取 seed 实例的 hits 和 function_summary
    seed_instance_map_hits = {}
    seed_instance_map_function_summary = {}
    for instance in retrieval_instances:
        seed_instance_map_hits[instance["instance_id"]] = instance["hits"]
        seed_instance_map_function_summary[instance["instance_id"]] = instance["function_summary"]

    for instance in tqdm(filtered_instances, desc=f"处理 {model_name} 的实例"):
        process(instance, model_name, base_url, api_key, github_token, raw_repo_dir, num_cycles, max_context_token, 
                max_gen_token,processed_instances, model_output_dir, CVE_map_instanceid, seed_instance_map_hits, 
                seed_instance_map_function_summary, seed_instance_map_repo, processed_instances_file, **model_args)

def filter_instances(raw_instances, processed_instances, num_cycles):
    filtered_instances = []
    for instance in raw_instances:
        instance_id = instance["instance_id"]
        # 检查每个周期是否已处理
        all_cycles_processed = True
        for cycle in range(1, num_cycles + 1):
            cycle_dir_name = f"{instance_id}_cycle{cycle}"
            if cycle_dir_name not in processed_instances:
                all_cycles_processed = False
                break
        
        if not all_cycles_processed:
            filtered_instances.append(instance)
    return filtered_instances

def get_seed_mutation_map(raw_instances):
    CVE_map_instanceid = {}
    seed_instance_map_repo = {}
    for instance in raw_instances:
        if instance["seed"] == False:
            continue
        CVE_map_instanceid[instance["vuln_source"]] = instance["instance_id"]
        seed_instance_map_repo[instance["instance_id"]] = instance["repo"]
    return CVE_map_instanceid, seed_instance_map_repo

# 用于更新处理记录
def update_processed_record(cycle_dir_name, success, processed_instances, processed_instances_file):
    processed_instances[cycle_dir_name] = {
        "success": success,
        "timestamp": time.time()
    }
    with open(processed_instances_file, 'w', encoding='utf-8') as f:
        json.dump(processed_instances, f, ensure_ascii=False, indent=2)


def process(instance, model_name, base_url, api_key, github_token, raw_repo_dir, num_cycles, max_context_token, 
            max_gen_token,processed_instances, model_output_dir, CVE_map_instanceid, seed_instance_map_hits, 
            seed_instance_map_function_summary, seed_instance_map_repo, processed_instances_file, **model_args):
    instance_id = instance["instance_id"]
    # 从 retrival data 中获取 hits 
    if instance["seed"] == False:
        cve_source = instance["vuln_source"]
        seed_instance_id = CVE_map_instanceid[cve_source]
    else:
        seed_instance_id = instance_id
    instance["hits"] = seed_instance_map_hits[seed_instance_id]
    instance["function_summary"] = seed_instance_map_function_summary[seed_instance_id]

    # 获取原始 repo 
    repo = instance["repo"]
    repo_dir = Path(raw_repo_dir, f"{repo.replace('/', '__')}")
    clone_repo(repo, repo_dir, github_token)

    # 为每个周期创建一个新的工作目录
    for cycle in range(1, num_cycles + 1):
        cycle_dir_name = f"{instance_id}_cycle{cycle}"
        
        # 检查是否已经处理过该周期
        if cycle_dir_name in processed_instances:
            continue
            
        logger.info(f" ========== 开始处理 {instance_id} -- {model_name} -- cycle_{cycle}")
        cycle_dir = model_output_dir / cycle_dir_name
        
        # 如果目录已存在，先删除
        if cycle_dir.exists():
            shutil.rmtree(cycle_dir)
        
        # 复制代码仓库到新目录
        if instance["seed"] == False:
            # 检查编译项目目录层级是否正确
            source_instance_id = CVE_map_instanceid[instance["vuln_source"]]
            source_repo = seed_instance_map_repo[source_instance_id]
            source_repo_name = source_repo.split("/")[-1]
            repo_files = [f for f in os.listdir(repo_dir) if not f.startswith('.')]
            if len(repo_files) == 1 and source_repo_name in repo_files:
                repo_dir = os.path.join(repo_dir, source_repo_name)

        shutil.copytree(repo_dir, cycle_dir, dirs_exist_ok=True, symlinks=True)
        logger.info(f"已复制 {repo_dir} 到 {cycle_dir}")
        
        # 处理实例
        instance["repo_dir"] = cycle_dir
        instance["raw_repo_dir"] = repo_dir
        try:
            success = process_instance(instance, model_name, base_url, api_key, max_context_token, 
                                       max_gen_token, **model_args)
            update_processed_record(cycle_dir_name, success, processed_instances, processed_instances_file)
        except Exception as e:
            logger.error(f"处理实例 {instance_id} 失败: {str(e)}")
            print(traceback.format_exc())
            # 将错误信息追加到 error.log 文件中
            with open("error.log", "a", encoding="utf-8") as error_file:
                error_file.write(f"[{datetime.datetime.now()}] 处理实例 {instance_id} 失败: {str(e)}\n")
                error_file.write(f"模型: {model_name}, 周期: {cycle}\n")
                error_file.write(f"详细错误: {traceback.format_exc()}\n\n")
        finally:
            # 清理无关文件，节省存储
            clean_unnecessary_files(cycle_dir)



def clean_unnecessary_files(repo_dir):
    # 删除项目的 .git 文件夹, 节省存储空间
    tmp_git_dir = os.path.join(repo_dir, ".git")
    if os.path.exists(tmp_git_dir):
        shutil.rmtree(tmp_git_dir)
    # 删除项目的 .github 文件夹, 节省存储空间
    tmp_github_dir = os.path.join(repo_dir, ".github")
    if os.path.exists(tmp_github_dir):
        shutil.rmtree(tmp_github_dir)
    # 特定项目处理
    tmp_repo_dir = os.path.join(repo_dir, "server/meshmodel")
    if os.path.exists(tmp_repo_dir):
        shutil.rmtree(tmp_repo_dir)
    tmp_repo_dir = os.path.join(repo_dir, "docs")
    if os.path.exists(tmp_repo_dir):
        shutil.rmtree(tmp_repo_dir)


def gen_code(model_name, batch_id, base_url, api_key, max_context_token, max_gen_token, github_token, 
             dataset_path, retrieval_data_path, raw_repo_dir, generated_code_dir, num_cycles, **model_args):
    with open(dataset_path, 'r', encoding='utf-8') as f:
        raw_instances = json.load(f)
    with open(retrieval_data_path, 'r', encoding='utf-8') as f:
        retrieval_instances = json.load(f)
    process_all_instances(raw_instances, retrieval_instances, model_name, batch_id, base_url, api_key, 
                          max_context_token, max_gen_token, 
                          github_token, raw_repo_dir, generated_code_dir, num_cycles, **model_args)
