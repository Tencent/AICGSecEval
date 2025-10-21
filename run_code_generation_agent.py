import datetime
import json
import os
import logging
from pathlib import Path
import time
import traceback
from tqdm import tqdm
import shutil
from bench.agent.manager import AgentBenchManager
from bench.context_manager import ContextManager
from bench.utils import clone_repo

# 设置日志
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_data(file_path):
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        data = json.loads(content)
    return data


async def process_instance(instance, agent_name, agent_class, agent_args):
    repo_dir = instance["repo_dir"]
    hits = instance["hits"]
    function_summary = instance["function_summary"]
    if "branch_origin" in instance:
        branch_origin = instance["branch_origin"]
    else:
        branch_origin = None

    with ContextManager(repo_dir, instance["base_commit"], instance["vuln_file"], instance["vuln_lines"], branch_origin) as cm:
        # 修改磁盘上的文件
        masked_vulnerability_file = cm.get_masked_vulnerability_file()
        masked_vulnerability_file_content = masked_vulnerability_file[instance["vuln_file"]]

        async with AgentBenchManager(agent_class, logger, repo_dir, agent_args) as agent:
            if not await agent.generate_code(
                file_path=instance["vuln_file"],
                function_summary=function_summary,
                context_file_list=list(set([hit["docid"] for hit in hits]))
            ):
                return False

        try:
            with open(os.path.join(repo_dir, instance["vuln_file"])) as f:
                patched_content = f.read()
            if patched_content == masked_vulnerability_file_content:
                logger.info(f"漏洞文件未被修改，生成失败")
                return False
            return True
        except Exception as e:
            logger.error(f"验证修复结果失败: {e}")

    return False


async def process_all_instances(raw_instances, retrieval_instances, agent_name, agent_class, agent_args, batch_id, github_token, raw_repo_dir, generated_code_dir, num_cycles):
    # 创建模型输出目录
    agent_output_dir = Path(generated_code_dir) / f"{agent_name}__{batch_id}"
    agent_output_dir.mkdir(parents=True, exist_ok=True)

    # 创建已处理实例的记录文件
    processed_instances_file = os.path.join(
        agent_output_dir, "processed_instances.json")
    processed_instances = {}

    # 如果记录文件存在，读取已处理的实例信息进行断点重连
    if os.path.exists(processed_instances_file):
        with open(processed_instances_file, 'r', encoding='utf-8') as f:
            processed_instances = json.load(f)
        logger.info(f"已加载处理记录，共 {len(processed_instances)} 个实例")

    # 过滤已处理的实例
    filtered_instances = filter_instances(
        raw_instances, processed_instances, num_cycles)
    if len(filtered_instances) < len(raw_instances):
        processed_sum = len(raw_instances) - len(filtered_instances)
        logger.info(
            f"共 {len(raw_instances)} 个实例，其中 {processed_sum} 个已被{agent_name}处理，{len(filtered_instances)} 个待处理")

    # 获取 seed 实例和 mutation 实例的映射
    CVE_map_instanceid, seed_instance_map_repo = get_seed_mutation_map(
        raw_instances)

    # 获取 seed 实例的 hits 和 function_summary
    seed_instance_map_hits = {}
    seed_instance_map_function_summary = {}
    for instance in retrieval_instances:
        seed_instance_map_hits[instance["instance_id"]] = instance["hits"]
        seed_instance_map_function_summary[instance["instance_id"]
                                           ] = instance["function_summary"]

    for instance in tqdm(filtered_instances, desc=f"处理 {agent_name} 的实例"):
        await process(instance, agent_name, agent_class, agent_args, github_token, raw_repo_dir, num_cycles, processed_instances, agent_output_dir,
                      CVE_map_instanceid, seed_instance_map_hits, seed_instance_map_function_summary, seed_instance_map_repo, processed_instances_file)


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
        if "seed" in instance and instance["seed"] == False:
            continue
        CVE_map_instanceid[instance["vuln_source"]] = instance["instance_id"]
        seed_instance_map_repo[instance["instance_id"]] = instance["repo"]
    return CVE_map_instanceid, seed_instance_map_repo


# 用于更新处理记录
def update_processed_record(cycle_dir_name, success, processed_instances, processed_instances_file, start_time):
    processed_instances[cycle_dir_name] = {
        "success": success,
        "time": time.time() - start_time
    }
    with open(processed_instances_file, 'w', encoding='utf-8') as f:
        json.dump(processed_instances, f, ensure_ascii=False, indent=2)


async def process(instance, agent_name, agent_class, agent_args, github_token, raw_repo_dir, num_cycles, processed_instances, agent_output_dir, CVE_map_instanceid, seed_instance_map_hits, seed_instance_map_function_summary, seed_instance_map_repo, processed_instances_file):
    instance_id = instance["instance_id"]
    # 从 retrival data 中获取 hits
    if "seed" in instance and instance["seed"] == False:
        cve_source = instance["vuln_source"]
        seed_instance_id = CVE_map_instanceid[cve_source]
    else:
        seed_instance_id = instance_id
    instance["hits"] = seed_instance_map_hits[seed_instance_id]
    instance["function_summary"] = seed_instance_map_function_summary[seed_instance_id]

    # 获取原始 repo
    repo = instance["repo"]
    repo_dir = Path(raw_repo_dir, f"{repo.replace('/', '__')}")
    clone_repo(repo, repo_dir, github_token, logger)

    # 为每个周期创建一个新的工作目录
    for cycle in range(1, num_cycles + 1):
        cycle_dir_name = f"{instance_id}_cycle{cycle}"

        # 检查是否已经处理过该周期
        if cycle_dir_name in processed_instances:
            continue

        logger.info(
            f" ========== 开始处理 {instance_id} -- {agent_name} -- cycle_{cycle}")
        cycle_dir = agent_output_dir / cycle_dir_name

        # 如果目录已存在，先删除
        if cycle_dir.exists():
            shutil.rmtree(cycle_dir)

        # 复制代码仓库到新目录
        if "seed" in instance and instance["seed"] == False:
            # 检查编译项目目录层级是否正确
            source_instance_id = CVE_map_instanceid[instance["vuln_source"]]
            source_repo = seed_instance_map_repo[source_instance_id]
            source_repo_name = source_repo.split("/")[-1]
            repo_files = [f for f in os.listdir(
                repo_dir) if not f.startswith('.')]
            if len(repo_files) == 1 and source_repo_name in repo_files:
                repo_dir = os.path.join(repo_dir, source_repo_name)

        shutil.copytree(repo_dir, cycle_dir, dirs_exist_ok=True, symlinks=True)
        logger.info(f"已复制 {repo_dir} 到 {cycle_dir}")

        # 处理实例
        instance["repo_dir"] = cycle_dir
        instance["raw_repo_dir"] = repo_dir
        try:
            start_time = time.time()
            success = await process_instance(instance, agent_name, agent_class, agent_args)
            update_processed_record(
                cycle_dir_name, success, processed_instances, processed_instances_file, start_time)
        except Exception as e:
            logger.error(f"处理实例 {instance_id} 失败: {str(e)}")
            print(traceback.format_exc())
            # 将错误信息追加到 error.log 文件中
            with open("agent_gencode_error.log", "a", encoding="utf-8") as error_file:
                error_file.write(
                    f"[{datetime.datetime.now()}] 处理实例 {instance_id} 失败: {str(e)}\n")
                error_file.write(f"模型: {agent_name}, 周期: {cycle}\n")
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


async def gen_code(agent_name, agent_class, agent_args, batch_id, github_token, dataset_path, retrieval_data_path, raw_repo_dir, generated_code_dir, num_cycles):
    with open(dataset_path, 'r', encoding='utf-8') as f:
        raw_instances = json.load(f)
    with open(retrieval_data_path, 'r', encoding='utf-8') as f:
        retrieval_instances = json.load(f)
    await process_all_instances(raw_instances, retrieval_instances, agent_name, agent_class,
                                agent_args, batch_id, github_token, raw_repo_dir, generated_code_dir, num_cycles)
