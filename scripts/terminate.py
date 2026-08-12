#!/usr/bin/env python3

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


EXPECTED_ACCOUNT_ID = "506456084249"
AWS_REGION = "us-east-1"
PROJECT_NAME = "pacman"
ENVIRONMENT = "dev"

CLUSTER_NAME = f"{PROJECT_NAME}-{ENVIRONMENT}"
NAMESPACE = "pacman"
STORAGE_CLASS = "gp3-auto"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = PROJECT_ROOT / "terraform"

EXPECTED_KUBE_CONTEXT = (
    f"arn:aws:eks:{AWS_REGION}:{EXPECTED_ACCOUNT_ID}:cluster/{CLUSTER_NAME}"
)


def check_tool(name):
    if shutil.which(name) is None:
        print(f"ERROR: Required tool '{name}' was not found.")
        sys.exit(1)


def run_command(command, allow_failure=False):
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0 and not allow_failure:
        print(f"ERROR: Command failed: {' '.join(command)}")

        if result.stdout.strip():
            print(result.stdout.strip())

        if result.stderr.strip():
            print(result.stderr.strip())

        sys.exit(1)

    return result


def run_aws_json(args):
    result = run_command(
        [
            "aws",
            *args,
            "--region",
            AWS_REGION,
            "--output",
            "json",
            "--no-cli-pager",
        ]
    )

    output = result.stdout.strip()

    if not output:
        return {}

    return json.loads(output)


def run_aws(args):
    return run_command(
        [
            "aws",
            *args,
            "--region",
            AWS_REGION,
            "--no-cli-pager",
        ]
    )


def run_kubectl(args, allow_failure=False, print_output=True):
    result = run_command(
        [
            "kubectl",
            "--context",
            EXPECTED_KUBE_CONTEXT,
            *args,
        ],
        allow_failure=allow_failure,
    )

    if print_output and result.stdout.strip():
        print(result.stdout.strip())

    if print_output and result.stderr.strip():
        print(result.stderr.strip())

    return result


def kubectl_json(args):
    result = run_kubectl(
        [
            *args,
            "-o",
            "json",
        ],
        print_output=False,
    )

    return json.loads(result.stdout)


def get_aws_identity():
    result = run_command(
        [
            "aws",
            "sts",
            "get-caller-identity",
            "--output",
            "json",
            "--no-cli-pager",
        ]
    )

    return json.loads(result.stdout)


def get_eks_clusters():
    data = run_aws_json(
        [
            "eks",
            "list-clusters",
        ]
    )

    return [
        name
        for name in data.get("clusters", [])
        if name == CLUSTER_NAME
    ]


def cluster_exists():
    return bool(get_eks_clusters())


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


def get_auto_mode_resources():
    data = run_aws_json(
        [
            "resourcegroupstaggingapi",
            "get-resources",
            "--tag-filters",
            f"Key=eks:eks-cluster-name,Values={CLUSTER_NAME}",
        ]
    )

    return [
        resource["ResourceARN"]
        for resource in data.get("ResourceTagMappingList", [])
    ]


def get_cluster_load_balancers():
    return [
        arn
        for arn in get_auto_mode_resources()
        if ":elasticloadbalancing:" in arn
        and ":loadbalancer/" in arn
    ]


def get_cluster_target_groups():
    return [
        arn
        for arn in get_auto_mode_resources()
        if ":elasticloadbalancing:" in arn
        and ":targetgroup/" in arn
    ]


def get_cluster_ebs_volumes():
    data = run_aws_json(
        [
            "ec2",
            "describe-volumes",
            "--include-managed-resources",
            "--filters",
            f"Name=tag:eks:eks-cluster-name,Values={CLUSTER_NAME}",
        ]
    )

    return [
        {
            "id": volume["VolumeId"],
            "state": volume["State"],
        }
        for volume in data.get("Volumes", [])
    ]


def terraform_destroy_preview(verbose=False):
    result = run_command(
        [
            "terraform",
            f"-chdir={TERRAFORM_DIR}",
            "plan",
            "-destroy",
            "-detailed-exitcode",
            "-input=false",
            "-no-color",
        ],
        allow_failure=True,
    )

    if verbose:
        if result.stdout:
            print(result.stdout)

        if result.stderr:
            print(result.stderr, file=sys.stderr)

    else:
        summary_found = False

        for line in result.stdout.splitlines():
            stripped = line.strip()

            if stripped.startswith("Plan:"):
                print(stripped)
                summary_found = True

            elif "No changes." in stripped:
                print(stripped)
                summary_found = True

        if not summary_found and result.stdout.strip():
            print("Terraform plan completed without a summary line.")

    return result.returncode


def terraform_destroy():
    print()
    print("=== Terraform Destroy ===")

    result = run_command(
        [
            "terraform",
            f"-chdir={TERRAFORM_DIR}",
            "destroy",
            "-auto-approve",
            "-input=false",
            "-no-color",
        ],
        allow_failure=True,
    )

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        print("ERROR: Terraform destroy failed.")
        return False

    return True


def verify_kube_context():
    result = run_command(
        [
            "kubectl",
            "config",
            "get-contexts",
            "-o",
            "name",
        ]
    )

    contexts = result.stdout.splitlines()

    if EXPECTED_KUBE_CONTEXT not in contexts:
        print("ERROR: Expected EKS kubeconfig context was not found.")
        print(f"Expected: {EXPECTED_KUBE_CONTEXT}")
        print()
        print("Run:")
        print(
            f"aws eks update-kubeconfig "
            f"--region {AWS_REGION} "
            f"--name {CLUSTER_NAME}"
        )
        return False

    return True


def namespace_exists():
    result = run_kubectl(
        [
            "get",
            "namespace",
            NAMESPACE,
        ],
        allow_failure=True,
        print_output=False,
    )

    return result.returncode == 0


def wait_until(description, condition, timeout=300, interval=10):
    print(f"Waiting for {description}...")

    deadline = time.time() + timeout

    while time.time() < deadline:
        if condition():
            print(f"{description}: complete")
            return True

        time.sleep(interval)

    print(f"WARNING: Timed out waiting for {description}.")
    return False


def delete_load_balancer_services():
    if not namespace_exists():
        return

    services = kubectl_json(
        [
            "get",
            "services",
            "-n",
            NAMESPACE,
        ]
    )

    for service in services.get("items", []):
        if service.get("spec", {}).get("type") == "LoadBalancer":
            name = service["metadata"]["name"]

            print(f"Deleting LoadBalancer Service: {name}")

            run_kubectl(
                [
                    "delete",
                    "service",
                    name,
                    "-n",
                    NAMESPACE,
                    "--ignore-not-found=true",
                ]
            )


def delete_ingresses():
    if not namespace_exists():
        return

    ingresses = kubectl_json(
        [
            "get",
            "ingress",
            "-n",
            NAMESPACE,
        ]
    )

    for ingress in ingresses.get("items", []):
        name = ingress["metadata"]["name"]

        print(f"Deleting Ingress: {name}")

        run_kubectl(
            [
                "delete",
                "ingress",
                name,
                "-n",
                NAMESPACE,
                "--ignore-not-found=true",
            ]
        )


def delete_workloads():
    if not namespace_exists():
        return

    print("Deleting application workloads...")

    run_kubectl(
        [
            "delete",
            "deployment,statefulset,daemonset,job,cronjob",
            "--all",
            "-n",
            NAMESPACE,
            "--ignore-not-found=true",
            "--wait=true",
            "--timeout=180s",
        ],
        allow_failure=True,
    )


def pvc_count():
    if not namespace_exists():
        return 0

    data = kubectl_json(
        [
            "get",
            "pvc",
            "-n",
            NAMESPACE,
        ]
    )

    return len(data.get("items", []))


def delete_pvcs():
    if not namespace_exists():
        return

    print("Deleting PersistentVolumeClaims...")

    run_kubectl(
        [
            "delete",
            "pvc",
            "--all",
            "-n",
            NAMESPACE,
            "--ignore-not-found=true",
            "--wait=false",
        ],
        allow_failure=True,
    )

    wait_until(
        "PVC deletion",
        lambda: pvc_count() == 0,
        timeout=300,
        interval=10,
    )


def delete_remaining_ebs_volumes():
    volumes = get_cluster_ebs_volumes()

    if not volumes:
        return True

    print()
    print("EBS volumes still associated with the cluster:")

    success = True

    for volume in volumes:
        volume_id = volume["id"]
        state = volume["state"]

        print(f"- {volume_id} ({state})")

        if state != "available":
            print(
                f"ERROR: {volume_id} is not available and "
                "will not be force-deleted."
            )
            success = False
            continue

        print(f"Deleting orphaned EBS volume: {volume_id}")

        run_aws(
            [
                "ec2",
                "delete-volume",
                "--volume-id",
                volume_id,
            ]
        )

    if not success:
        return False

    return wait_until(
        "EBS volume deletion",
        lambda: len(get_cluster_ebs_volumes()) == 0,
        timeout=300,
        interval=10,
    )


def delete_remaining_load_balancers():
    load_balancers = get_cluster_load_balancers()

    if load_balancers:
        print()
        print("Deleting remaining Auto Mode load balancers...")

        for arn in load_balancers:
            print(f"- {arn}")

            run_aws(
                [
                    "elbv2",
                    "delete-load-balancer",
                    "--load-balancer-arn",
                    arn,
                ]
            )

        if not wait_until(
            "load balancer deletion",
            lambda: len(get_cluster_load_balancers()) == 0,
            timeout=300,
            interval=10,
        ):
            return False

    target_groups = get_cluster_target_groups()

    if target_groups:
        print("Deleting remaining target groups...")

        for arn in target_groups:
            print(f"- {arn}")

            run_aws(
                [
                    "elbv2",
                    "delete-target-group",
                    "--target-group-arn",
                    arn,
                ]
            )

    return True


def delete_namespace_and_storage_class():
    if namespace_exists():
        print()
        print(f"Deleting namespace: {NAMESPACE}")

        run_kubectl(
            [
                "delete",
                "namespace",
                NAMESPACE,
                "--ignore-not-found=true",
                "--wait=true",
                "--timeout=180s",
            ],
            allow_failure=True,
        )

    print(f"Deleting StorageClass: {STORAGE_CLASS}")

    run_kubectl(
        [
            "delete",
            "storageclass",
            STORAGE_CLASS,
            "--ignore-not-found=true",
        ],
        allow_failure=True,
    )


def kubernetes_cleanup():
    if not cluster_exists():
        print("EKS cluster does not exist. Skipping Kubernetes cleanup.")
        return True

    check_tool("kubectl")

    if not verify_kube_context():
        return False

    print()
    print("=== Kubernetes Cleanup ===")

    delete_load_balancer_services()
    delete_ingresses()

    wait_until(
        "Kubernetes-managed load balancer cleanup",
        lambda: len(get_cluster_load_balancers()) == 0,
        timeout=300,
        interval=10,
    )

    if get_cluster_load_balancers():
        if not delete_remaining_load_balancers():
            return False

    delete_workloads()
    delete_pvcs()

    wait_until(
        "Kubernetes-managed EBS cleanup",
        lambda: len(get_cluster_ebs_volumes()) == 0,
        timeout=300,
        interval=10,
    )

    if get_cluster_ebs_volumes():
        if not delete_remaining_ebs_volumes():
            return False

    delete_namespace_and_storage_class()

    return True


def show_inventory(verbose=False):
    print()
    print("=== Terraform Destroy Preview ===")

    exit_code = terraform_destroy_preview(verbose=verbose)

    if exit_code == 0:
        print("No Terraform-managed resources need destruction.")

    elif exit_code == 2:
        print("Terraform-managed resources would be destroyed.")
        print("PREVIEW ONLY - nothing was deleted.")

    else:
        print("ERROR: Terraform destroy preview failed.")
        sys.exit(1)

    print()
    print("=== AWS Runtime Inventory ===")

    tagged = get_tagged_runtime_resources()
    auto_mode = get_auto_mode_resources()
    volumes = get_cluster_ebs_volumes()
    load_balancers = get_cluster_load_balancers()
    clusters = get_eks_clusters()

    print(f"Tagged project resources : {len(tagged)}")
    print(f"Auto Mode resources      : {len(auto_mode)}")
    print(f"EBS volumes              : {len(volumes)}")
    print(f"Load balancers           : {len(load_balancers)}")
    print(f"EKS clusters             : {len(clusters)}")

    if clusters:
        for cluster in clusters:
            print(f"  EKS: {cluster}")

    if volumes:
        for volume in volumes:
            print(f"  EBS: {volume['id']} ({volume['state']})")

    if load_balancers:
        for arn in load_balancers:
            print(f"  LB : {arn}")


def final_verification():
    print()
    print("=== Final Orphan Verification ===")

    clusters = get_eks_clusters()
    volumes = get_cluster_ebs_volumes()
    load_balancers = get_cluster_load_balancers()
    auto_mode = get_auto_mode_resources()
    tagged = get_tagged_runtime_resources()

    print(f"EKS clusters        : {len(clusters)}")
    print(f"EBS volumes         : {len(volumes)}")
    print(f"Load balancers      : {len(load_balancers)}")
    print(f"Auto Mode resources : {len(auto_mode)}")
    print(f"Tagged resources    : {len(tagged)}")

    billable_leftovers = bool(
        clusters
        or volumes
        or load_balancers
    )

    if billable_leftovers:
        print()
        print("ERROR: Potential billable resources still remain.")

        for cluster in clusters:
            print(f"- EKS cluster: {cluster}")

        for volume in volumes:
            print(f"- EBS volume: {volume['id']} ({volume['state']})")

        for arn in load_balancers:
            print(f"- Load balancer: {arn}")

        return False

    print()
    print("No EKS cluster, EBS volume, or load balancer remains.")
    return True


def confirm_destroy(skip_confirmation):
    if skip_confirmation:
        return True

    print()
    print("WARNING: --destroy will remove the Pac-Man AWS environment.")
    print(f"Cluster : {CLUSTER_NAME}")
    print(f"Account : {EXPECTED_ACCOUNT_ID}")
    print(f"Region  : {AWS_REGION}")
    print()

    answer = input(
        f"Type '{CLUSTER_NAME}' to continue: "
    ).strip()

    return answer == CLUSTER_NAME


def parse_args():
    parser = argparse.ArgumentParser(
        description="Pac-Man AWS teardown and safety verification."
    )

    parser.add_argument(
        "--destroy",
        action="store_true",
        help="Actually delete Kubernetes and Terraform resources.",
    )

    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive destroy confirmation.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show the full Terraform destroy plan.",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    print("=== Pac-Man AWS Teardown ===")

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

    show_inventory(verbose=args.verbose)

    if not args.destroy:
        print()
        print("Safety check completed.")
        print("No AWS resources were deleted.")
        print()
        print("To perform teardown:")
        print("python3 scripts/terminate.py --destroy")
        return

    if not confirm_destroy(args.yes):
        print()
        print("Destroy cancelled.")
        print("No resources were deleted.")
        return

    if not kubernetes_cleanup():
        print()
        print("ERROR: Kubernetes cleanup did not complete safely.")
        print("Terraform destroy was NOT started.")
        sys.exit(1)

    # One final fallback before deleting the cluster.
    if not delete_remaining_load_balancers():
        print("ERROR: Load balancer cleanup failed.")
        sys.exit(1)

    if not delete_remaining_ebs_volumes():
        print("ERROR: EBS cleanup failed.")
        sys.exit(1)

    if not terraform_destroy():
        print()
        print("Remaining Auto Mode resources:")

        for arn in get_auto_mode_resources():
            print(f"- {arn}")

        sys.exit(1)

    # A persistent EBS volume is the important Auto Mode exception.
    # Re-check once more after cluster deletion.
    if get_cluster_ebs_volumes():
        if not delete_remaining_ebs_volumes():
            sys.exit(1)

    if not final_verification():
        sys.exit(1)

    print()
    print("Teardown completed successfully.")


if __name__ == "__main__":
    main()
