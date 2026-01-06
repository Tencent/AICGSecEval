import json
import logging
import os
import subprocess
import time
import traceback
import shutil
from pathlib import Path
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def scan_single_folder(folder, raw_data_map, generated_code_dir, result_dir): 
    # 获取对应的 SAST 镜像地址
    instance_source = folder.split("_cycle")[0]
    sast_image_url = raw_data_map[instance_source]['detected_tool']
    preprocess_file(os.path.join(generated_code_dir, folder, raw_data_map[instance_source]['vuln_file']))
    # 准备输入文件
    input_json_path = os.path.join(result_dir, f"{folder}_input.json")
        
    # 运行容器进行安全扫描
    try:
        input_data = {}
        # 将输入文件挂载到容器中并执行
        abs_repo_dir = os.path.abspath(generated_code_dir)
        if sast_image_url == "aiseceval/autopoc:latest":
            input_data['path'] = "/app/AutoPoC/data/"+folder
            docker_cmd = f"docker run --rm -it -v {abs_repo_dir}:/app/AutoPoC/data {sast_image_url} "
            docker_cmd += f"/bin/bash -c \"/bin/bash entry.sh /app/AutoPoC/data/sast_results/{folder}_input.json "
            docker_cmd += f"/app/AutoPoC/data/sast_results/{folder}_output.json\""
        elif sast_image_url == "aiseceval/ai_gen_code:latest":
            input_data['path'] = "/data/"+folder
            docker_cmd = f"docker run --rm -it -v {abs_repo_dir}:/data {sast_image_url} "
            docker_cmd += f"/bin/bash -c \"/pecker/entry.sh /data/sast_results/{folder}_input.json "
            docker_cmd += f"/data/sast_results/{folder}_output.json\""            
        
        input_data['language'] = raw_data_map[instance_source]['language']
        input_data['vuln_type'] = [fetch_vul_type(raw_data_map[instance_source]['vuln_type'])]
        with open(input_json_path, 'w', encoding='utf-8') as f:
            json.dump(input_data, f, ensure_ascii=False, indent=2)
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}执行命令: {docker_cmd}")
        # subprocess.run(docker_cmd, shell=True, check=True, text=True)
        subprocess.run(docker_cmd, shell=True, check=True, universal_newlines=True)
        
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}成功完成 {folder} 的安全扫描")
        return True
    except subprocess.CalledProcessError as e:
        # 打印 subprocess run 内异常的详细信息
        print(f"安全扫描 {folder} 失败，命令执行错误: {e}")
        print(f"错误码: {e.returncode}")
        print(f"标准输出: {e.stdout}")
        print(f"错误输出: {e.stderr}")
        return False

def preprocess_file(file_path):
    with open(file_path, "r") as f:
        lines = f.readlines()
    clear_lines = []
    count = 0
    for line in lines:
        if line.strip() != "<MASKED>":
            clear_lines.append(line)
        else:
            count += 1
    if count > 0:
        with open(file_path, "w") as f:
            f.write("".join(clear_lines))

def fetch_vul_type(vul_type_in_dataset):
    type_map = {
        "SQLI": "sql injection",
        "XSS": "xss",
        "Command Injection": "command injection",
        "Path Traversal": "path traversal",
    }
    if vul_type_in_dataset in type_map:
        return type_map[vul_type_in_dataset]
    else:
        raise ValueError(f"未找到 {vul_type_in_dataset} 对应的漏洞类型")



def prepare_sast_image(all_sast_image_urls):
    for sast_image_url in all_sast_image_urls:
        try:
            cmds = ["docker", "pull", sast_image_url]
            subprocess.run(cmds, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            logger.error(f"拉取SAST镜像失败: {e}")
            return False
    return True

# 解析 processed_instances.json 文件，获取成功处理的实例
def get_success_folders(res_file):
    success_folders = []
    with open(res_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for instance_id, result in data.items():
            if result['success']:
                success_folders.append(instance_id)
    return success_folders

def filter_instances(success_folders, raw_data_map):
    tmp_success_folders = []
    for folder in success_folders:
        instance_id = folder.split("_cycle")[0]
        if instance_id not in raw_data_map.keys():
            continue
        else:
            tmp_success_folders.append(folder)
    success_folders = tmp_success_folders
    return success_folders


# 提交扫描任务
def submit_scan_tasks(executor, folders, raw_data_map, generated_code_dir, result_dir):
    future_to_folder = {}
    for folder in folders:
        future = executor.submit(
            scan_single_folder, 
            folder, 
            raw_data_map, 
            generated_code_dir, 
            result_dir
        )
        future_to_folder[future] = folder
    return future_to_folder

# 处理扫描结果
def process_scan_result(future, folder):
    successful = 0
    failed = 0
    try:
        success = future.result()
        if success:
            successful = 1
        else:
            failed = 1
    except Exception as exc:
        # 输出异常详情
        logger.error(f"{folder} 安全扫描发生异常: {exc}")
        logger.error(f"异常类型: {type(exc).__name__}")
        logger.error(f"异常详情: {traceback.format_exc()}")
        failed = 1
    return successful, failed

# 处理键盘中断
def handle_keyboard_interrupt(future_to_folder, successful_scans, failed_scans):
    logger.info("用户中断了扫描过程，正在退出...")
    # 取消所有未完成的任务
    for future in future_to_folder:
        if not future.done():
            future.cancel()
    logger.info(f"已完成 {successful_scans} 个扫描，失败 {failed_scans} 个，剩余任务已取消")


def load_dataset(dataset_file):
    raw_data_map = {}
    all_sast_image_urls = []
    with open(dataset_file, 'r', encoding='utf-8') as f:
        dataset = json.load(f)
        for item in dataset:
            raw_data_map[item['instance_id']] = item
            all_sast_image_urls.append(item['detected_tool'])
    return raw_data_map, all_sast_image_urls


def filter_unscanned_projects(success_folders, result_dir, raw_data_map):
    for result_file in os.listdir(result_dir):
        if result_file.endswith("_output.json"):
            sasted_repo = result_file.split("_output.json")[0]

            res = parse_sast_output_file(result_dir, result_file)
            if res["detected_vul_num"] == -1:
                # 环境问题导致的失败，重跑
                if "error_message" in res:
                    error_message = res["error_message"]
                    if error_message.strip().startswith("[ERROR]: Multiple exceptions: [Errno 111]"):
                        print(f"删除 {result_dir}/{result_file} 因为检测结果为 -1 且错误原因为"
                              "Connect call failed ('127.0.0.1', 8989), [Errno 99] Cannot assign requested address")
                        os.remove(os.path.join(result_dir, result_file))
                        raw_file = os.path.join(result_dir,result_file+"_raw")
                        if os.path.exists(raw_file):
                            os.remove(raw_file)
                        continue
            
            if sasted_repo in success_folders:
                success_folders.remove(sasted_repo)

    return success_folders


# 等一个模型生成结束后批量扫描结果
def batch_scan(generated_code_dir, dataset_file, max_workers):
    # 读取合入成功情况，如果为false，则跳过，不进行扫描
    success_folders = get_success_folders(os.path.join(generated_code_dir, "processed_instances.json"))
    # 加载数据集并准备映射, 同时获取所有需要处理的 sast 镜像
    raw_data_map, all_sast_image_urls = load_dataset(dataset_file)
    # 过滤掉不在 dataset 中的实例
    success_folders = filter_instances(success_folders, raw_data_map)

    # 创建结果目录
    result_dir = os.path.join(generated_code_dir, "sast_results")
    os.makedirs(result_dir, exist_ok=True)

    # 获取所有需要处理的文件夹
    total_folders_num = len(success_folders)
    if total_folders_num == 0:
        logger.warning(f"警告: {generated_code_dir} 中没有找到需要扫描的项目")
        return
    logger.info(f"共 {total_folders_num} 个文件夹需要进行安全扫描")
    
    # 断点重连：扫描未检测成功的项目
    success_folders = filter_unscanned_projects(success_folders, result_dir, raw_data_map)
    logger.info(f"过滤掉已扫描完成的项目，剩余 {len(success_folders)} 个项目需要扫描")
    if len(success_folders) == 0:
        logger.info(f"所有项目均已扫描完成，跳过扫描")
        return

    # 裁剪部分 repo 减少扫描时间
    process_cut_repo_for_sast(success_folders, generated_code_dir)
    logger.info(f"裁剪部分 repo 减少扫描时间")

    # 下载所有 sast 镜像 
    res = prepare_sast_image(all_sast_image_urls)
    if not res:
        logger.error(f"拉取SAST镜像失败")
        return
    logger.info(f"拉取所有 sast 镜像完成")

    # 使用多线程并发执行扫描任务
    # 设置最大线程数
    max_workers = min(max_workers, len(success_folders)) 
    successful_scans = 0
    failed_scans = 0
    
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有扫描任务
            future_to_folder = submit_scan_tasks(executor, success_folders, 
                                                 raw_data_map, generated_code_dir, result_dir)
            
            # 使用tqdm显示进度
            for future in tqdm(as_completed(future_to_folder), total=len(future_to_folder), desc="扫描进度"):
                folder = future_to_folder[future]
                success_count, fail_count = process_scan_result(future, folder)
                successful_scans += success_count
                failed_scans += fail_count
    except KeyboardInterrupt:
        handle_keyboard_interrupt(future_to_folder, successful_scans, failed_scans)
    
    logger.info(f"本轮扫描完成: 成功 {successful_scans} 个, 失败 {failed_scans} 个")

    # 统计是否完全扫描成功
    count = 0
    for result_file in os.listdir(result_dir):
        if result_file.endswith("_output.json"):
            count += 1
    if count != total_folders_num:
        logger.warning(f"警告: 该模型累计成功扫描 {count} 个项目，但需要扫描 {total_folders_num} 个项目, 存在{total_folders_num-count}个未扫描成功的项目")
    else:
        logger.info(f"该模型累计成功扫描 {count} 个项目，全部扫描成功！")


def security_scan(generated_code_dir, llm_name, batchid, dataset_file, max_workers):
    logger.info(f"开始检测 {llm_name}__{batchid} 生成的代码...")
    code_dir = os.path.join(generated_code_dir, llm_name+"__"+batchid)

    try:
        count = 0
        while True:
            batch_scan(code_dir, dataset_file, max_workers)
            fail_sast_count = check_invalid_sast_results(code_dir)
            if fail_sast_count == 0:
                break
            logger.info(f"存在 {fail_sast_count} 个无效的 SAST 结果，重试中...")
            count += 1
            if count == 3:
                logger.error(f"重试3次后，仍存在 {fail_sast_count} 个无效的 SAST 结果，请调整 max_workers 参数为 1 后重试")
                exit(-1)
            time.sleep(3)
    except Exception as e:
        traceback.print_exc()
        # 将报错详情追加到 error.log 文件中
        with open("error.log", "a") as f:
            f.write(f"{llm_name}__{batchid} 安全扫描失败: {e}\n")
            f.write(traceback.format_exc())
            f.write("\n")
    finally:
        merge_sast_results(code_dir, dataset_file)
    
    logger.info(f"{llm_name}__{batchid} 的代码扫描完成")


def check_invalid_sast_results(code_dir):
    sast_result_dir = os.path.join(code_dir, "sast_results")
    count = 0
    for result_file in os.listdir(sast_result_dir):
        if result_file.endswith("_output.json"):
            sast_res = parse_sast_output_file(sast_result_dir, result_file)
            if sast_res["detected_vul_num"] == -1 and "error_message" in sast_res:
                error_message = sast_res["error_message"]
                if error_message.strip().startswith("[ERROR]: Multiple exceptions: [Errno 111]"):
                    count += 1
    return count

def merge_sast_results(code_dir, dataset_file):
    raw_data_map, all_sast_image_urls = load_dataset(dataset_file)
    instance_ids = raw_data_map.keys()

    # 合并结果
    sast_result_dir = os.path.join(code_dir, "sast_results")
    sast_res = []
    for result_file in os.listdir(sast_result_dir):
        if result_file.endswith("_output.json") and result_file.split("_cycle")[0] in instance_ids:
            sast_res.append(parse_sast_output_file(sast_result_dir, result_file))

    with open(os.path.join(code_dir, "sast_results.json"), 'w', encoding='utf-8') as f:
        json.dump(sast_res, f, ensure_ascii=False, indent=2)


def parse_sast_output_file(sast_result_dir, result_file):
    with open(os.path.join(sast_result_dir, result_file), 'r', encoding='utf-8') as f:
        data = json.load(f)
    res = data
    res["instance_id"] = result_file.split("_output.json")[0]
    return res

def process_cut_repo_for_sast(success_folders, generated_code_dir):
    cut_repo_info = read_cut_repo_info()
    for folder in success_folders:
        instance_id = folder.split("_cycle")[0]
        if instance_id not in cut_repo_info.keys():
            continue
        process_cut_repo(os.path.join(generated_code_dir, folder), cut_repo_info[instance_id])

def read_cut_repo_info():
    with open("data/cut_repos.json", "r") as f:
        repo_info = json.load(f)
    return repo_info

def process_cut_repo(target_repo_dir, file_list):
    # 创建备份目录
    backup_dir = Path(f"{target_repo_dir}_backup")
    
    # 检查备份是否已存在
    if not backup_dir.exists():
        # 如果备份不存在，则创建备份
        shutil.copytree(target_repo_dir, backup_dir, symlinks=False)

    # 删除当前项目
    if Path(target_repo_dir).exists():
        shutil.rmtree(target_repo_dir)

    # 创建新项目
    new_repo_dir = Path(target_repo_dir)
    new_repo_dir.mkdir(parents=True, exist_ok=True)
    
    # 将文件列表中的文件复制到新项目
    for file in file_list:
        # 确保目标文件的目录结构存在
        target_file_path = new_repo_dir / file
        target_file_dir = target_file_path.parent
        target_file_dir.mkdir(parents=True, exist_ok=True)
        # 复制文件
        shutil.copy(os.path.join(backup_dir, file), target_file_path)


