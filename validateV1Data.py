import os
from pathlib import Path
import shutil
import subprocess
import sys
import json

import docker
from git import Repo, GitCommandError


def validate_single_case(case_data: dict):
    result = dict()
    
    if not os.path.exists("validate_results"):
        os.makedirs("validate_results")
    # 检查 repo 是否能成功 clone
    repo_dir = Path(f"validate_results/{case_data['instance_id']}")
    try:
        clone_repo(case_data["repo"],repo_dir)
        print(f"::info 成功 clone 仓库: {case_data['repo']}")
    except Exception as e:
        print(f"::error 无法 clone 仓库: {e}, 请修正 repo 字段")
        return -1

    # 检查 base_commit 是否能成功 checkout
    base_commit = case_data["base_commit"]
    try:
        repo = Repo(repo_dir)
        if "branch_origin" in case_data:
            repo.git.fetch("origin", case_data["branch_origin"])
        repo.git.checkout(base_commit)
        checkout_success = True
        print(f"::info 成功 checkout 切换到 base_commit: {base_commit}")
    except GitCommandError as e:
        checkout_success = False
    except Exception as e:
        checkout_success = False
    if not checkout_success:
        print(f"::error checkout 切换到 base_commit 失败: {e}, 请修正 base_commit 字段并更新 vuln_file & vuln_lines 字段")
        return -1

    # 检查 vuln_file 是否存在（路径是否正确）
    vuln_file_path = repo_dir / case_data['vuln_file']
    if not vuln_file_path.exists():
        print(f"::error vuln_file 路径在当前版本的 repo 中不存在: {case_data['vuln_file']}, 请修正 vuln_file 字段或检查 base_commit 是否正确")
        return -1
    print(f"::info vuln_file 路径检查通过")

    # 检查 vuln_lines
    if len(case_data["vuln_lines"]) != 2:
        print(f"::error vuln_lines 应包含起始行和结束行两个值, 请修正 vuln_lines 字段")
        return -1
    elif case_data["vuln_lines"][1] - case_data["vuln_lines"][0] <= 3:
        print(f"::error vuln_lines 太短, 请增加代码片段长度, 请修正 vuln_lines 字段")
        return -1
    print(f"::info vuln_lines 检查通过")

    # 检查 SAST 镜像是否能下载
    docker_image = case_data["detected_tool"]
    try:
        docker.from_env().images.pull(docker_image)
        print(f"::info 成功下载 SAST 镜像: {docker_image}")
    except Exception as e:
        print(f"::error 无法下载 SAST 镜像: {e}, 请修正 detected_tool 字段")
        return -1

    # 检查 SAST 工具运行后输出 detected_vul_num 是否和元数据中的匹配，且不为 -1
    sast_data_dir = Path("validate_results") / f"{case_data['instance_id']}_sast"
    if not os.path.exists(sast_data_dir):
        os.makedirs(sast_data_dir)
    input_data = {
        "path": case_data["image_inner_repopath"],
    }
    with open(sast_data_dir / "input.json", "w", encoding="utf-8") as f:
        json.dump(input_data, f, ensure_ascii=False, indent=2)

    abs_repo_dir = os.path.abspath(repo_dir)
    abs_sast_data_dir = os.path.abspath(sast_data_dir)
    docker_cmd = f"docker run --rm -v {abs_repo_dir}:{case_data['image_inner_repopath']} -v {abs_sast_data_dir}/input.json:{case_data['image_inner_inputfile']} -v {abs_sast_data_dir}/output.json:{case_data['image_inner_outputfile']} {docker_image} {case_data['image_inner_inputfile']} {case_data['image_inner_outputfile']}"
    print(f"::info 执行命令: {docker_cmd}")
    try:
        subprocess.run(docker_cmd, shell=True, check=True, universal_newlines=True)
        with open(sast_data_dir / "output.json", "r", encoding="utf-8") as f:
            sast_data = json.load(f)
        if sast_data["detected_vul_num"] != case_data["detected_vul_num"]:
            print(f"::error SAST 工具运行后输出 detected_vul_num 不匹配: {sast_data['detected_vul_num']} != {case_data['detected_vul_num']}, 请检查并修正")
            return -1
        if sast_data["detected_vul_num"] == -1:
            print(f"::error SAST 工具运行后输出 detected_vul_num 为 -1, 运行失败，请检查并修正")
            return -1
    except subprocess.CalledProcessError as e:
        print(f"::error SAST 工具运行失败: {e}, 请检查并修正")
        return -1
    print(f"::info {case_data['instance_id']} 数据成功通过验证！！")
    return 0


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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validateV1Data.py <input_json_file>")
        sys.exit(1)

    param_name = sys.argv[1]
    with open(param_name, "r", encoding="utf-8") as f:
        data = json.load(f)

    validate_single_case(data)
