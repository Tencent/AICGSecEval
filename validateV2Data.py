import argparse
import fcntl
import json
import logging
import os
import sys
from multiprocessing.pool import Pool
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

    if "base_commit" in case_data and \
            isinstance(case_data["base_commit"], str) and \
            case_data["base_commit"].endswith("^"):
        patch_commit = case_data["base_commit"][:-1]
    elif "patch_commit" in case_data and isinstance(case_data["patch_commit"], str):
        patch_commit = case_data["patch_commit"]
    else:
        patch_commit = None

    result = {
        "base_commit": {
            "commit": case_data.get("base_commit", None),
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
            remove_container=patch_commit is None
        ) as docker:
            result["base_commit"]["image_status_check"] = run_case_and_validate(
                trace=trace,
                docker=docker,
                case_data=case_data,
                case_key="image_status_check_cmd",
                case_name="基准版本软件状态检查",
                default_timeout=300,
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
                remove_container=remove_container
            ) as docker:
                result["patch_commit"]["checkout"] = run_command_and_validate(
                    trace=trace,
                    docker=docker,
                    case_name="切换代码为修复版本",
                    command=f"bash -c \"git checkout {patch_commit} && git log -1 --format='[A.S.E]%H'\"",
                    timeout=60,
                    environment={"LANG": "en_US"},
                    workdir=case_data["image_inner_path"],
                    check_output=f"[A.S.E]{patch_commit}",
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
                    default_timeout=600,
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
        with open(output_file, "a") as f:
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
    validate_success_result_base_commit = set()    # 已经验证成功的基准版本结果
    try:
        if os.path.exists(args.output_file):
            exist_result = load_validate_result(args.output_file)
            for item in exist_result:
                if item["base_commit"]["image_status_check"] and item["base_commit"]["test_case_check"] and item["base_commit"]["poc_check"] and item["patch_commit"]["checkout"] and item["patch_commit"]["image_status_check"] and item["patch_commit"]["test_case_check"] and item["patch_commit"]["poc_check"]:
                    validate_success_result.append(item)
                    validate_success_result_base_commit.add(item["base_commit"]["commit"])
            os.remove(args.output_file)
    except Exception as e:
        logging.error(f"删除输出文件 \"{args.output_file}\" 失败：{e}")
        return -1

    # 将成功的结果先写入
    with open(args.output_file, "w") as f:
        for item in validate_success_result:
            f.write(json.dumps(item) + "\n")

    data_to_validate = list()
    for case in case_data_list:
        if case["base_commit"] in validate_success_result_base_commit:
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
