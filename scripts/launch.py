#!/usr/bin/env python3

import json
import shutil
import subprocess
import sys
from pathlib import Path


EXPECTED_ACCOUNT_ID = "506456084249"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "pacman-dev"
NAMESPACE = "pacman"

STATE_BUCKET = (
    "pacman-terraform-state-506456084249-us-east-1"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = PROJECT_ROOT / "terraform"
K8S_DIR = PROJECT_ROOT / "k8s"

REQUIRED_K8S_FILES = [
    "namespace.yaml",
    "storage-class.yaml",
    "mongo-service.yaml",
    "mongo-statefulset.yaml",
    "app-configmap.yaml",
    "app-deployment.yaml",
    "app-service.yaml",
]

RUNTIME_PHASES = [
    (
        "1. Terraform infrastructure",
        [
            "Create VPC and public subnets",
            "Create ECR repository",
            "Create GitHub OIDC IAM resources",
            "Create EKS Auto Mode cluster",
            "Create scoped GitHub Actions EKS access",
        ],
    ),
    (
        "2. Kubernetes access",
        [
            "Wait for EKS cluster to become ACTIVE",
            "Update local kubeconfig",
            "Verify Kubernetes API connectivity",
        ],
    ),
    (
        "3. Application image",
        [
            "Build linux/amd64 Pac-Man image",
            "Tag image with immutable Git commit SHA",
            "Authenticate to ECR",
            "Push image to ECR",
        ],
    ),
    (
        "4. Kubernetes base",
        [
            "Create pacman namespace",
            "Create gp3 Auto Mode StorageClass",
        ],
    ),
    (
        "5. MongoDB",
        [
            "Create MongoDB headless Service",
            "Create MongoDB StatefulSet",
            "Wait for MongoDB readiness",
            "Verify PVC and EBS volume",
        ],
    ),
    (
        "6. Pac-Man",
        [
            "Create Pac-Man ConfigMap",
            "Create Pac-Man Deployment",
            "Wait for rollout",
            "Verify Pac-Man connects to MongoDB",
            "Verify HTTP response internally",
        ],
    ),
    (
        "7. Public NLB",
        [
            "Create Pac-Man LoadBalancer Service",
            "Wait for NLB hostname",
            "Verify external HTTP response",
        ],
    ),
    (
        "8. Final runtime verification",
        [
            "Verify pods and services",
            "Verify persistent storage",
            "Verify NLB",
            "Collect evidence for documentation",
        ],
    ),
]


def fail(message):
    print(f"ERROR: {message}")
    sys.exit(1)


def check_tool(name):
    path = shutil.which(name)

    if path is None:
        fail(f"Required tool '{name}' was not found.")

    return path


def run(command, allow_failure=False):
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0 and not allow_failure:
        print(
            "ERROR: Command failed: "
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


def verify_project_files():
    print()
    print("=== Project File Check ===")

    required_paths = [
        PROJECT_ROOT / "Dockerfile",
        PROJECT_ROOT / "package.json",
        PROJECT_ROOT / "package-lock.json",
        TERRAFORM_DIR / "main.tf",
        TERRAFORM_DIR / "versions.tf",
        PROJECT_ROOT / "scripts" / "terminate.py",
    ]

    required_paths.extend(
        K8S_DIR / filename
        for filename in REQUIRED_K8S_FILES
    )

    missing = [
        path
        for path in required_paths
        if not path.exists()
    ]

    if missing:
        print("Missing required project files:")

        for path in missing:
            print(
                f"- {path.relative_to(PROJECT_ROOT)}"
            )

        sys.exit(1)

    print(
        f"Required project files: "
        f"{len(required_paths)}"
    )
    print("Project file check passed.")


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
        fail(
            "AWS account does not match "
            "the Pac-Man project account."
        )

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
        fail(
            "Terraform state bucket was not "
            f"found or is inaccessible: {STATE_BUCKET}"
        )

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

    for reservation in data.get(
        "Reservations",
        [],
    ):
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
            "COST-SAFE preview refuses to "
            "continue against an active runtime."
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
        if (
            "successfully initialized"
            in line.lower()
        ):
            print(line.strip())

    print(
        "Terraform initialization passed."
    )


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
        if result.stdout.strip():
            print(result.stdout.strip())

        print()
        print("Run:")
        print(
            "terraform -chdir=terraform "
            "fmt -recursive"
        )

        fail(
            "Terraform formatting check failed."
        )

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
        "Resources currently in root state: "
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


def show_runtime_plan():
    print()
    print("=== Future Runtime Launch Plan ===")
    print()
    print(
        "The following phases are documented "
        "only. None are executed in COST-SAFE MODE."
    )

    for title, steps in RUNTIME_PHASES:
        print()
        print(title)

        for step in steps:
            print(f"  - {step}")

    print()
    print(
        "Runtime execution remains disabled."
    )


def main():
    print("=== Pac-Man Safe Launch Preview ===")
    print()
    print(
        "COST-SAFE MODE: this script cannot "
        "create AWS infrastructure."
    )
    print(
        "No terraform apply, ECR push, "
        "kubectl apply, or NLB creation "
        "is implemented."
    )
    print()

    for tool in (
        "aws",
        "terraform",
        "git",
        "docker",
        "kubectl",
    ):
        path = check_tool(tool)
        print(f"{tool}: {path}")

    verify_project_files()

    print()
    verify_aws_identity()
    verify_state_bucket()

    verify_runtime_is_off()

    terraform_init()
    terraform_fmt_check()
    terraform_validate()
    terraform_state_check()
    terraform_plan()

    show_runtime_plan()
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
