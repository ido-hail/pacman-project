#!/usr/bin/env python3

import json
import shutil
import subprocess
import sys
from pathlib import Path


EXPECTED_ACCOUNT_ID = "506456084249"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "pacman-dev"

STATE_BUCKET = (
    "pacman-terraform-state-506456084249-us-east-1"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = PROJECT_ROOT / "terraform"


def check_tool(name):
    path = shutil.which(name)

    if path is None:
        print(
            f"ERROR: Required tool '{name}' "
            "was not found."
        )
        sys.exit(1)

    return path


def run(command, allow_failure=False):
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0 and not allow_failure:
        print(
            f"ERROR: Command failed: "
            f"{' '.join(command)}"
        )

        if result.stdout.strip():
            print(result.stdout.strip())

        if result.stderr.strip():
            print(result.stderr.strip())

        sys.exit(1)

    return result


def aws_json(args, allow_failure=False):
    result = run(
        [
            "aws",
            *args,
            "--region",
            AWS_REGION,
            "--output",
            "json",
            "--no-cli-pager",
        ],
        allow_failure=allow_failure,
    )

    if result.returncode != 0:
        return None

    output = result.stdout.strip()

    return json.loads(output) if output else {}


def verify_aws_identity():
    result = run(
        [
            "aws",
            "sts",
            "get-caller-identity",
            "--output",
            "json",
            "--no-cli-pager",
        ]
    )

    identity = json.loads(result.stdout)

    account_id = identity["Account"]
    arn = identity["Arn"]

    print(f"AWS account : {account_id}")
    print(f"AWS identity: {arn}")
    print(f"AWS region  : {AWS_REGION}")

    if account_id != EXPECTED_ACCOUNT_ID:
        print()
        print(
            "ERROR: AWS account does not match "
            "the Pac-Man project account."
        )

        sys.exit(1)

    print("AWS account verification passed.")


def verify_state_bucket():
    result = run(
        [
            "aws",
            "s3api",
            "head-bucket",
            "--bucket",
            STATE_BUCKET,
        ],
        allow_failure=True,
    )

    if result.returncode != 0:
        print(
            "ERROR: Terraform state bucket "
            "was not found or is inaccessible."
        )
        print(f"Bucket: {STATE_BUCKET}")

        sys.exit(1)

    print(
        f"Terraform state bucket: {STATE_BUCKET}"
    )
    print("State bucket verification passed.")


def get_project_cluster():
    data = aws_json(
        [
            "eks",
            "list-clusters",
        ]
    )

    clusters = data.get("clusters", [])

    return [
        cluster
        for cluster in clusters
        if cluster == CLUSTER_NAME
    ]


def get_project_instances():
    data = aws_json(
        [
            "ec2",
            "describe-instances",
            "--include-managed-resources",
            "--filters",
            (
                "Name=tag:eks:eks-cluster-name,"
                f"Values={CLUSTER_NAME}"
            ),
            (
                "Name=instance-state-name,"
                "Values=pending,running,stopping,stopped"
            ),
        ]
    )

    instances = []

    for reservation in data.get("Reservations", []):
        instances.extend(
            reservation.get("Instances", [])
        )

    return instances


def get_project_ebs():
    data = aws_json(
        [
            "ec2",
            "describe-volumes",
            "--include-managed-resources",
            "--filters",
            (
                "Name=tag:eks:eks-cluster-name,"
                f"Values={CLUSTER_NAME}"
            ),
        ]
    )

    return data.get("Volumes", [])


def verify_runtime_is_off():
    print()
    print("=== AWS Runtime Safety Check ===")

    clusters = get_project_cluster()
    instances = get_project_instances()
    volumes = get_project_ebs()

    print(f"EKS clusters : {len(clusters)}")
    print(f"EC2 instances: {len(instances)}")
    print(f"EBS volumes  : {len(volumes)}")

    if clusters or instances or volumes:
        print()
        print(
            "ERROR: Pac-Man runtime resources "
            "already exist."
        )
        print(
            "This preview script will not "
            "modify them."
        )

        sys.exit(1)

    print()
    print(
        "No Pac-Man EKS, EC2, or EBS "
        "runtime resources detected."
    )


def terraform_init():
    print()
    print("=== Terraform Init ===")

    result = run(
        [
            "terraform",
            f"-chdir={TERRAFORM_DIR}",
            "init",
            "-input=false",
            "-no-color",
        ]
    )

    for line in result.stdout.splitlines():
        if "successfully initialized" in line.lower():
            print(line.strip())

    print("Terraform initialization passed.")


def terraform_fmt_check():
    print()
    print("=== Terraform Format Check ===")

    result = run(
        [
            "terraform",
            f"-chdir={TERRAFORM_DIR}",
            "fmt",
            "-check",
            "-recursive",
        ],
        allow_failure=True,
    )

    if result.returncode != 0:
        print(
            "ERROR: Terraform formatting check failed."
        )

        if result.stdout.strip():
            print(result.stdout.strip())

        print()
        print(
            "Run:"
        )
        print(
            "terraform -chdir=terraform "
            "fmt -recursive"
        )

        sys.exit(1)

    print("Terraform formatting passed.")


def terraform_validate():
    print()
    print("=== Terraform Validate ===")

    result = run(
        [
            "terraform",
            f"-chdir={TERRAFORM_DIR}",
            "validate",
            "-no-color",
        ]
    )

    output = result.stdout.strip()

    if output:
        print(output)


def terraform_state_check():
    print()
    print("=== Terraform State ===")

    result = run(
        [
            "terraform",
            f"-chdir={TERRAFORM_DIR}",
            "state",
            "list",
        ]
    )

    resources = [
        line
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    print(
        f"Resources currently in root state: "
        f"{len(resources)}"
    )

    if resources:
        print()
        print(
            "ERROR: Root Terraform state "
            "is not empty."
        )

        for resource in resources:
            print(f"- {resource}")

        sys.exit(1)

    print("Root Terraform state is clean.")


def terraform_plan():
    print()
    print("=== Terraform Creation Preview ===")

    result = run(
        [
            "terraform",
            f"-chdir={TERRAFORM_DIR}",
            "plan",
            "-detailed-exitcode",
            "-input=false",
            "-no-color",
        ],
        allow_failure=True,
    )

    if result.returncode not in (0, 2):
        print("ERROR: Terraform plan failed.")

        if result.stdout.strip():
            print(result.stdout.strip())

        if result.stderr.strip():
            print(result.stderr.strip())

        sys.exit(1)

    summary = None

    for line in result.stdout.splitlines():
        stripped = line.strip()

        if stripped.startswith("Plan:"):
            summary = stripped

    if summary:
        print(summary)
    elif result.returncode == 0:
        print("Terraform reports no changes.")
    else:
        print(
            "Terraform detected changes, "
            "but no plan summary was found."
        )

    print()
    print(
        "PREVIEW ONLY - terraform apply "
        "was NOT executed."
    )


def git_status():
    print()
    print("=== Git Working Tree ===")

    result = run(
        [
            "git",
            "-C",
            str(PROJECT_ROOT),
            "status",
            "--short",
        ]
    )

    if result.stdout.strip():
        print(
            "Local uncommitted changes detected:"
        )
        print(result.stdout.rstrip())
    else:
        print("Git working tree is clean.")


def main():
    print("=== Pac-Man Safe Launch Preview ===")
    print()
    print(
        "COST-SAFE MODE: this script cannot "
        "create AWS infrastructure."
    )
    print(
        "No terraform apply or Kubernetes "
        "deployment is implemented."
    )
    print()

    for tool in (
        "aws",
        "terraform",
        "git",
    ):
        path = check_tool(tool)
        print(f"{tool}: {path}")

    print()

    verify_aws_identity()
    verify_state_bucket()
    verify_runtime_is_off()

    terraform_init()
    terraform_fmt_check()
    terraform_validate()
    terraform_state_check()
    terraform_plan()

    git_status()

    print()
    print("=== Preview Complete ===")
    print(
        "No AWS runtime resources were created."
    )
    print(
        "The environment remains in "
        "COST-SAFE MODE."
    )


if __name__ == "__main__":
    main()
