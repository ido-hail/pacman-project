#!/usr/bin/env python3

import json
import shutil
import subprocess
import sys
from pathlib import Path


EXPECTED_ACCOUNT_ID = "506456084249"
AWS_REGION = "us-east-1"
PROJECT_NAME = "pacman"
ENVIRONMENT = "dev"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = PROJECT_ROOT / "terraform"


def check_tool(name):
    if shutil.which(name) is None:
        print(f"ERROR: Required tool '{name}' was not found.")
        sys.exit(1)


def run_aws_json(args):
    command = [
        "aws",
        *args,
        "--region",
        AWS_REGION,
        "--output",
        "json",
        "--no-cli-pager",
    ]

    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        print("ERROR: AWS CLI command failed.")
        print(result.stderr.strip())
        sys.exit(1)

    return json.loads(result.stdout)


def get_aws_identity():
    result = subprocess.run(
        [
            "aws",
            "sts",
            "get-caller-identity",
            "--output",
            "json",
        ],
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        print("ERROR: Could not verify AWS identity.")
        print(result.stderr.strip())
        sys.exit(1)

    return json.loads(result.stdout)


def terraform_destroy_preview():
    command = [
        "terraform",
        f"-chdir={TERRAFORM_DIR}",
        "plan",
        "-destroy",
        "-detailed-exitcode",
        "-input=false",
        "-no-color",
    ]

    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
    )

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print(result.stderr, file=sys.stderr)

    return result.returncode


def get_tagged_runtime_resources():
    data = run_aws_json(
        [
            "resourcegroupstaggingapi",
            "get-resources",
            "--tag-filters",
            f"Key=Project,Values={PROJECT_NAME}",
            f"Key=Environment,Values={ENVIRONMENT}",
        ]
    )

    return [
        resource["ResourceARN"]
        for resource in data.get("ResourceTagMappingList", [])
    ]


def main():
    print("=== Pac-Man AWS Teardown Safety Check ===")

    check_tool("aws")
    check_tool("terraform")

    identity = get_aws_identity()

    account_id = identity["Account"]
    arn = identity["Arn"]

    print(f"AWS account : {account_id}")
    print(f"AWS identity: {arn}")
    print(f"AWS region  : {AWS_REGION}")

    if account_id != EXPECTED_ACCOUNT_ID:
        print()
        print("ERROR: AWS account does not match the project account.")
        print("No actions were performed.")
        sys.exit(1)

    print()
    print("AWS account verification passed.")

    print()
    print("=== Terraform Destroy Preview ===")

    exit_code = terraform_destroy_preview()

    if exit_code == 0:
        print("No Terraform-managed runtime resources need to be destroyed.")

    elif exit_code == 2:
        print("Terraform found resources that would be destroyed.")
        print("PREVIEW ONLY - nothing was deleted.")

    else:
        print("ERROR: Terraform destroy preview failed.")
        sys.exit(1)

    print()
    print("=== AWS Tagged Runtime Inventory ===")

    resources = get_tagged_runtime_resources()

    if resources:
        print(f"Found {len(resources)} tagged runtime resource(s):")

        for resource_arn in resources:
            print(f"- {resource_arn}")

    else:
        print("No tagged runtime resources found.")

    print()
    print("Safety check completed.")
    print("No AWS resources were deleted.")


if __name__ == "__main__":
    main()
