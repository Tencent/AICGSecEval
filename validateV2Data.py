import argparse
import fcntl
import json
import logging
import os
import shutil
from pathlib import Path
import sys
from multiprocessing.pool import Pool
from git import Repo
from docker_helper import DockerHelper
from run_security_scan import run_command_and_validate, run_case_and_validate

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")


def validate_single_case(case_data: dict, output_file: str, dump_dir: str, remove_container: bool):
    if "instance_id" not in case_data:
        logging.error(f"非法数据，没有找到 \"instance_id\" 字段")
        return

    trace = case_data["instance_id"]
    logging.info(f"[{trace}] 开始验证")

    try:
        dump_dir = os.path.join(dump_dir, trace)
        os.makedirs(dump_dir, exist_ok=True)
    except Exception as e:
        logging.error(f"[{trace}] 创建目录 {dump_dir} 失败：{e}")
        return

    if "base_commit" in case_data and "patch_commit" not in case_data and \
            isinstance(case_data["base_commit"], str) and \
            case_data["base_commit"].endswith("^"):
        patch_commit = case_data["base_commit"][:-1]
    elif "patch_commit" in case_data and isinstance(case_data["patch_commit"], str):
        patch_commit = case_data["patch_commit"]
    else:
        patch_commit = None

    basic_result = validate_basic_info(case_data)
    # 如果基础检查未通过，不启动后续验证
    # passed = True
    # for key in basic_result:
    #     if not basic_result[key]:
    #         passed = False
    #         break
    # if not passed:
    #     logging.info(f"[{trace}] 基础检查未通过, 未启动后续验证")
    #     result = {
    #         "instance_id": trace,
    #         **basic_result,
    #     }
    #     try:
    #         with open(output_file, "a", encoding="utf-8") as f:
    #             fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    #             f.write(json.dumps(result) + "\n")
    #     except Exception as e:
    #         logging.error(f"[{trace}] 保存验证结果失败：{e}")
    

    if "privileged" in case_data and case_data["privileged"]:
        privileged = True
    else:
        privileged = False
    
    result = {
        "instance_id": trace,
        **basic_result,
        "inner_path_check": False,
        "base_commit": {
            "commit": case_data.get("base_commit", None),
            "checkout": False,
            "image_status_check": False,
            "test_case_check": False,
            "poc_check": False,
        },
        "patch_commit": {
            "commit": patch_commit,
            "checkout": False,
            "image_status_check": False,
            "test_case_check": False,
            "poc_check": False,
        },
    }
    
    try:
        with DockerHelper(
            trace=trace,
            image=case_data["image"],
            command=case_data["image_run_cmd"],
            remove_container=patch_commit is None,
            privileged=privileged
        ) as docker:

            # inner path 检查
            container_inner_path = case_data["image_inner_path"]+"/"+case_data["vuln_file"]
            if not docker.check_file_exists(container_inner_path):
                result["inner_path_check"] = False
                result["inner_path_check_failed_reason"] = f"路径不存在: {container_inner_path}"
            else:
                result["inner_path_check"] = True

            # 切换到基准版本
            result["base_commit"]["checkout"] = basic_result["base_commit_checkout"]
            run_command_and_validate(
                    trace=trace,
                    docker=docker,
                    case_name="切换代码为基准版本",
                    command=f"bash -c \"git checkout {case_data['base_commit']}'\"",
                    timeout=60,
                    environment={"LANG": "en_US"},
                    workdir=case_data["image_inner_path"],
                    check_output=f" ",
                    output_file=f"{dump_dir}/base_commit.checkout.log"
                )

            result["base_commit"]["image_status_check"] = run_case_and_validate(
                trace=trace,
                docker=docker,
                case_data=case_data,
                case_key="image_status_check_cmd",
                case_name="基准版本软件状态检查",
                default_timeout=900,
                check_output="[A.S.E] image startup successfully",
                output_file=f"{dump_dir}/base_commit.image_status_check.log"
            )

            if not result["base_commit"]["image_status_check"]:
                raise ValueError(f"软件状态检查未通过，不再进行测试用例和漏洞PoC验证")

            result["base_commit"]["test_case_check"] = run_case_and_validate(
                trace=trace,
                docker=docker,
                case_data=case_data,
                case_key="test_case_cmd",
                case_name="基准版本测试用例验证",
                default_timeout=120,
                check_output="[A.S.E] test case passed",
                output_file=f"{dump_dir}/base_commit.test_case.log"
            )

            result["base_commit"]["poc_check"] = run_case_and_validate(
                trace=trace,
                docker=docker,
                case_data=case_data,
                case_key="poc_cmd",
                case_name="基准版本漏洞PoC验证",
                default_timeout=120,
                check_output="[A.S.E] vulnerability found",
                output_file=f"{dump_dir}/base_commit.poc.log"
            )

    except Exception as e:
        logging.error(f"[{trace}] 基准版本扫描异常：{e}")

    if patch_commit is not None:
        try:
            with DockerHelper(
                trace=trace,
                image=case_data["image"],
                command=case_data["image_run_cmd"],
                remove_container=remove_container,
                privileged=privileged
            ) as docker:
                result["patch_commit"]["checkout"] = run_command_and_validate(
                    trace=trace,
                    docker=docker,
                    case_name="切换代码为修复版本",
                    command=f"bash -c \"git checkout {patch_commit} && git log -1 --format='[A.S.E]%H'\"",
                    timeout=60,
                    environment={"LANG": "en_US"},
                    workdir=case_data["image_inner_path"],
                    check_output=f"{patch_commit}", # 不检查 [A.S.E] tag, 只检查 commit hash，因为有些数据使用的 hash 不完整
                    output_file=f"{dump_dir}/patch_commit.checkout.log"
                )

                if not result["patch_commit"]["checkout"]:
                    raise ValueError(f"切换代码为修复版本失败，不再进行后续验证")

                result["patch_commit"]["image_status_check"] = run_case_and_validate(
                    trace=trace,
                    docker=docker,
                    case_data=case_data,
                    case_key="image_status_check_cmd",
                    case_name="修复版本软件状态检查",
                    default_timeout=900,
                    check_output="[A.S.E] image startup successfully",
                    output_file=f"{dump_dir}/patch_commit.image_status_check.log"
                )

                if not result["patch_commit"]["image_status_check"]:
                    raise ValueError(f"软件状态检查未通过，不再进行测试用例和漏洞PoC验证")

                result["patch_commit"]["test_case_check"] = run_case_and_validate(
                    trace=trace,
                    docker=docker,
                    case_data=case_data,
                    case_key="test_case_cmd",
                    case_name="修复版本测试用例验证",
                    default_timeout=120,
                    check_output="[A.S.E] test case passed",
                    output_file=f"{dump_dir}/patch_commit.test_case.log"
                )

                result["patch_commit"]["poc_check"] = run_case_and_validate(
                    trace=trace,
                    docker=docker,
                    case_data=case_data,
                    case_key="poc_cmd",
                    case_name="修复版本漏洞PoC验证",
                    default_timeout=120,
                    check_output="[A.S.E] vulnerability not found",
                    output_file=f"{dump_dir}/patch_commit.poc.log"
                )

        except Exception as e:
            logging.error(f"[{trace}] 修复版本扫描异常：{e}")

    logging.info(f"[{trace}] 验证结束：{result}")

    try:
        with open(output_file, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(json.dumps(result) + "\n")
    except Exception as e:
        logging.error(f"[{trace}] 保存验证结果失败：{e}")


def case_validator(input_data):
    return validate_single_case(case_data=input_data["data"],
                                output_file=input_data["args"].output_file,
                                dump_dir=input_data["args"].dump_dir,
                                remove_container=input_data["args"].remove_container)

def load_validate_result(output_file: str):
    result = list()
    with open(output_file, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            result.append(data)
    return result


def clone_repo(repo, repo_dir):
    if not repo_dir.exists():
        # 如果 repo 是 gitlab 地址，则使用 gitlab 地址
        if repo.startswith("https://gitlab"):
            repo_url = repo
        else:
            repo_url = f"https://github.com/{repo}.git"
        print(f"Cloning {repo} (pid={os.getpid()})")
        Repo.clone_from(repo_url, repo_dir)
    return repo_dir


# 对各个字段进行检查
def validate_basic_info(case_data: dict):
    result = dict()
    
    # 检查 repo 是否能成功 clone
    repo_dir = Path(f"{case_data['instance_id']}")
    try:
        clone_repo(case_data["repo"],repo_dir)
    except Exception as e:
        result["repo"] = False
        result["repo_clone_failed_reason"] = f"无法 clone 仓库: {e}"
        return result
    result["repo"] = True

    # 检查 base_commit 是否能成功 checkout
    base_commit = case_data["base_commit"]
    from git import Repo, GitCommandError
    try:
        repo = Repo(repo_dir)
        if "branch_origin" in case_data:
            repo.git.fetch("origin", case_data["branch_origin"])
        repo.git.checkout(base_commit)
        logging.info(f"[{case_data.get('instance_id', base_commit)}] git checkout {base_commit} 成功")
        checkout_success = True
    except GitCommandError as e:
        logging.error(f"[{case_data.get('instance_id', base_commit)}] git checkout {base_commit} 失败: {str(e)}")
        checkout_success = False
    except Exception as e:
        logging.error(f"执行 git checkout 发生异常: {e}")
        checkout_success = False
    result["base_commit_checkout"] = checkout_success
    if not checkout_success:
        result["base_commit_checkout_failed_reason"] = "无法 checkout 切换到 base_commit"

    # 检查 vuln_file 是否存在（路径是否正确）
    vuln_file_path = repo_dir / case_data['vuln_file']
    result["vuln_file"] = vuln_file_path.exists()
    if not result["vuln_file"]:
        result["vuln_file_failed_reason"] = f"路径不存在: {vuln_file_path}"

    # 检查 vuln_lines
    if len(case_data["vuln_lines"]) != 2:
        result["vuln_lines"] = False
        result["vuln_lines_failed_reason"] = f"漏洞代码行数应包含起始行和结束行两个值"
    elif case_data["vuln_lines"][1] - case_data["vuln_lines"][0] <= 3:
        result["vuln_lines"] = False
        result["vuln_lines_failed_reason"] = f"漏洞代码行数太短, 请增加代码片段长度"
    else:
        result["vuln_lines"] = True

    # 删除 repo 目录
    try:
        shutil.rmtree(repo_dir)
    except Exception as e:
        logging.warning(f"删除目录 {repo_dir} 时出错: {e}")
    return result



def main(args: list[str]) -> int:
    parser = argparse.ArgumentParser(description="V2 Data Validator")
    parser.add_argument("-i", "--input-file", type=str,
                        required=True, help="Path to input file")
    parser.add_argument("-o", "--output-file", type=str,
                        required=True, help="Path to output file")
    parser.add_argument("-d", "--dump-dir", type=str, required=True,
                        help="Path to runtime dump directory")
    parser.add_argument("-w", "--worker-count", type=int,
                        default=1, help="Number of workers")
    parser.add_argument("--remove-container", type=bool, action=argparse.BooleanOptionalAction,
                        default=True, help="Remove container after validation")
    args = parser.parse_args(args)

    try:
        with open(args.input_file, "r") as f:
            case_data_list = json.load(f)
    except Exception as e:
        logging.error(f"读取输入文件 \"{args.input_file}\" 失败：{e}")
        return -1

    if not isinstance(case_data_list, list):
        logging.error(f"输入文件 \"{args.input_file}\" 格式错误，必须是列表")
        return -1
    if len(case_data_list) == 0:
        logging.error(f"输入文件 \"{args.input_file}\" 没有任何数据")
        return -1

    validate_success_result = list()    # 已经验证成功的结果
    validate_success_result_instance_id = set()    # 已经验证成功的基准版本结果
    try:
        if os.path.exists(args.output_file):
            exist_result = load_validate_result(args.output_file)
            for item in exist_result:
                if item["repo"] and item["base_commit_checkout"] and item["vuln_file"] and item["inner_path_check"] and item["base_commit"]["image_status_check"] and item["base_commit"]["test_case_check"] and item["base_commit"]["poc_check"] and item["patch_commit"]["checkout"] and item["patch_commit"]["image_status_check"] and item["patch_commit"]["test_case_check"] and item["patch_commit"]["poc_check"]:
                    validate_success_result.append(item)
                    validate_success_result_instance_id.add(item["instance_id"])
            os.remove(args.output_file)
    except Exception as e:
        logging.error(f"删除输出文件 \"{args.output_file}\" 失败：{e}")
        return -1

    # 将成功的结果先写入
    if validate_success_result:
        with open(args.output_file, "w", encoding="utf-8") as f:
            for item in validate_success_result:
                f.write(json.dumps(item) + "\n")

    data_to_validate = list()
    for case in case_data_list:
        if case["instance_id"] in validate_success_result_instance_id:
            continue
        data_to_validate.append(case)
    case_data_list = data_to_validate

    logging.info(f"一共有 {len(case_data_list)} 条数据需要验证")

    validator_input_data = [{"data": case_data, "args": args}
                            for case_data in case_data_list]

    with Pool(processes=args.worker_count) as pool:
        pool.map(case_validator, validator_input_data)

    logging.info(f"验证完成")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
