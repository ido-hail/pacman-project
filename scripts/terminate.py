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
AUTO_MODE_CSI_DRIVER = "ebs.csi.eks.amazonaws.com"

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


def run_aws_json(args, allow_failure=False):
    result = run_command(
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


def run_aws(args, allow_failure=False):
    return run_command(
        [
            "aws",
            *args,
            "--region",
            AWS_REGION,
            "--no-cli-pager",
        ],
        allow_failure=allow_failure,
    )


def run_kubectl(args, allow_failure=False):
    return run_command(
        [
            "kubectl",
            "--context",
            EXPECTED_KUBE_CONTEXT,
            *args,
        ],
        allow_failure=allow_failure,
    )


def kubectl_json(args, allow_failure=False):
    result = run_kubectl(
        [
            *args,
            "-o",
            "json",
        ],
        allow_failure=allow_failure,
    )

    if result.returncode != 0:
        return None

    output = result.stdout.strip()

    return json.loads(output) if output else {}


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


def get_tagged_project_resources():
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
        item["ResourceARN"]
        for item in data.get("ResourceTagMappingList", [])
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
        item["ResourceARN"]
        for item in data.get("ResourceTagMappingList", [])
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
            "size": volume["Size"],
            "type": volume["VolumeType"],
            "az": volume["AvailabilityZone"],
            "encrypted": volume["Encrypted"],
        }
        for volume in data.get("Volumes", [])
    ]


def get_volume(volume_id):
    result = run_command(
        [
            "aws",
            "ec2",
            "describe-volumes",
            "--include-managed-resources",
            "--volume-ids",
            volume_id,
            "--region",
            AWS_REGION,
            "--output",
            "json",
            "--no-cli-pager",
        ],
        allow_failure=True,
    )

    if result.returncode != 0:
        if "InvalidVolume.NotFound" in result.stderr:
            return None

        print(f"ERROR: Could not inspect EBS volume {volume_id}.")
        print(result.stderr.strip())
        sys.exit(1)

    data = json.loads(result.stdout)
    volumes = data.get("Volumes", [])

    return volumes[0] if volumes else None


def volume_exists(volume_id):
    return get_volume(volume_id) is not None


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
        print("ERROR: Expected kubeconfig context was not found.")
        print(f"Expected: {EXPECTED_KUBE_CONTEXT}")
        print()
        print(
            f"Run: aws eks update-kubeconfig "
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
    )

    return result.returncode == 0


def get_persistent_volume_ids():
    if not cluster_exists() or not namespace_exists():
        return []

    pvc_data = kubectl_json(
        [
            "get",
            "pvc",
            "-n",
            NAMESPACE,
        ],
        allow_failure=True,
    )

    if not pvc_data:
        return []

    volume_ids = []

    for pvc in pvc_data.get("items", []):
        pv_name = pvc.get("spec", {}).get("volumeName")

        if not pv_name:
            continue

        pv = kubectl_json(
            [
                "get",
                "pv",
                pv_name,
            ],
            allow_failure=True,
        )

        if not pv:
            continue

        csi = pv.get("spec", {}).get("csi", {})

        if csi.get("driver") != AUTO_MODE_CSI_DRIVER:
            continue

        volume_id = csi.get("volumeHandle")

        if volume_id:
            volume_ids.append(volume_id)

    return sorted(set(volume_ids))


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
    services = kubectl_json(
        [
            "get",
            "services",
            "--all-namespaces",
        ],
        allow_failure=True,
    )

    if not services:
        return

    for service in services.get("items", []):
        if service.get("spec", {}).get("type") != "LoadBalancer":
            continue

        namespace = service["metadata"]["namespace"]
        name = service["metadata"]["name"]

        print(
            f"Deleting LoadBalancer Service: "
            f"{namespace}/{name}"
        )

        run_kubectl(
            [
                "delete",
                "service",
                name,
                "-n",
                namespace,
                "--ignore-not-found=true",
            ],
            allow_failure=True,
        )


def delete_ingresses():
    ingresses = kubectl_json(
        [
            "get",
            "ingress",
            "--all-namespaces",
        ],
        allow_failure=True,
    )

    if not ingresses:
        return

    for ingress in ingresses.get("items", []):
        namespace = ingress["metadata"]["namespace"]
        name = ingress["metadata"]["name"]

        print(f"Deleting Ingress: {namespace}/{name}")

        run_kubectl(
            [
                "delete",
                "ingress",
                name,
                "-n",
                namespace,
                "--ignore-not-found=true",
            ],
            allow_failure=True,
        )


def delete_workloads():
    if not namespace_exists():
        return

    print("Deleting Pac-Man workloads...")

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


def delete_pvcs():
    if not namespace_exists():
        return

    print("Deleting Pac-Man PVCs...")

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


def wait_for_persistent_volumes_to_delete(volume_ids):
    if not volume_ids:
        print(
            "No Kubernetes persistent EBS volumes "
            "need cleanup."
        )

        return True

    print(
        "Persistent EBS volumes captured "
        "before PVC deletion:"
    )

    for volume_id in volume_ids:
        print(f"- {volume_id}")

    if wait_until(
        "persistent EBS volume deletion",
        lambda: all(
            not volume_exists(volume_id)
            for volume_id in volume_ids
        ),
        timeout=300,
        interval=10,
    ):
        return True

    print()
    print(
        "Persistent EBS volumes still present "
        "after PVC deletion."
    )

    for volume_id in volume_ids:
        volume = get_volume(volume_id)

        if volume is None:
            continue

        state = volume["State"]

        print(f"- {volume_id} ({state})")

        if state != "available":
            print(
                f"ERROR: {volume_id} is still {state}; "
                "refusing to force-delete it."
            )

            return False

        print(
            f"Deleting orphaned persistent "
            f"EBS volume: {volume_id}"
        )

        run_aws(
            [
                "ec2",
                "delete-volume",
                "--volume-id",
                volume_id,
            ]
        )

    return wait_until(
        "manual persistent EBS cleanup",
        lambda: all(
            not volume_exists(volume_id)
            for volume_id in volume_ids
        ),
        timeout=300,
        interval=10,
    )


def delete_remaining_load_balancers():
    load_balancers = get_cluster_load_balancers()

    if not load_balancers:
        return True

    print()
    print(
        "Cluster load balancers still exist "
        "after Kubernetes deletion:"
    )

    for arn in load_balancers:
        print(f"- {arn}")

    print(
        "Deleting remaining cluster-tagged "
        "load balancers..."
    )

    for arn in load_balancers:
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

    for arn in get_cluster_target_groups():
        print(
            f"Deleting remaining target group: {arn}"
        )

        run_aws(
            [
                "elbv2",
                "delete-target-group",
                "--target-group-arn",
                arn,
            ],
            allow_failure=True,
        )

    return True


def delete_namespace_and_storage_class():
    if namespace_exists():
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
        print(
            "EKS cluster does not exist. "
            "Skipping Kubernetes cleanup."
        )

        return True

    check_tool("kubectl")

    if not verify_kube_context():
        return False

    print()
    print("=== Kubernetes Cleanup ===")

    persistent_volume_ids = get_persistent_volume_ids()

    delete_load_balancer_services()
    delete_ingresses()

    wait_until(
        "Kubernetes load balancer cleanup",
        lambda: len(get_cluster_load_balancers()) == 0,
        timeout=300,
        interval=10,
    )

    if get_cluster_load_balancers():
        if not delete_remaining_load_balancers():
            return False

    delete_workloads()
    delete_pvcs()

    if not wait_for_persistent_volumes_to_delete(
        persistent_volume_ids
    ):
        return False

    delete_namespace_and_storage_class()

    return True


def show_inventory(verbose=False):
    print()
    print("=== Terraform Destroy Preview ===")

    exit_code = terraform_destroy_preview(
        verbose=verbose
    )

    if exit_code == 0:
        print(
            "No Terraform-managed resources "
            "need destruction."
        )

    elif exit_code == 2:
        print(
            "Terraform-managed resources "
            "would be destroyed."
        )
        print(
            "PREVIEW ONLY - nothing was deleted."
        )

    else:
        print(
            "ERROR: Terraform destroy preview failed."
        )

        sys.exit(1)

    print()
    print("=== AWS Runtime Inventory ===")

    tagged = get_tagged_project_resources()
    auto_mode = get_auto_mode_resources()
    all_ebs = get_cluster_ebs_volumes()
    persistent_ebs = get_persistent_volume_ids()
    load_balancers = get_cluster_load_balancers()
    clusters = get_eks_clusters()

    persistent_set = set(persistent_ebs)

    other_ebs = [
        volume
        for volume in all_ebs
        if volume["id"] not in persistent_set
    ]

    print(
        f"Tagged project resources : {len(tagged)}"
    )
    print(
        f"Auto Mode resources      : {len(auto_mode)}"
    )
    print(
        f"All cluster EBS volumes  : {len(all_ebs)}"
    )
    print(
        f"Persistent workload EBS  : {len(persistent_ebs)}"
    )
    print(
        f"Other cluster EBS        : {len(other_ebs)}"
    )
    print(
        f"Load balancers           : {len(load_balancers)}"
    )
    print(
        f"EKS clusters             : {len(clusters)}"
    )

    for volume_id in persistent_ebs:
        print(
            f"  Persistent EBS: {volume_id}"
        )

    for volume in other_ebs:
        print(
            f"  Other EBS: {volume['id']} "
            f"({volume['state']}, "
            f"{volume['size']} GiB)"
        )

    for cluster in clusters:
        print(f"  EKS: {cluster}")

    for arn in load_balancers:
        print(f"  LB : {arn}")


def wait_for_cluster_ebs_cleanup():
    return wait_until(
        "Auto Mode node EBS cleanup",
        lambda: len(get_cluster_ebs_volumes()) == 0,
        timeout=600,
        interval=15,
    )


def final_verification():
    print()
    print("=== Final Orphan Verification ===")

    clusters = get_eks_clusters()
    volumes = get_cluster_ebs_volumes()
    load_balancers = get_cluster_load_balancers()

    print(
        f"EKS clusters   : {len(clusters)}"
    )
    print(
        f"EBS volumes    : {len(volumes)}"
    )
    print(
        f"Load balancers : {len(load_balancers)}"
    )

    if clusters or volumes or load_balancers:
        print()
        print(
            "ERROR: Potential billable resources "
            "still remain."
        )

        for cluster in clusters:
            print(
                f"- EKS cluster: {cluster}"
            )

        for volume in volumes:
            print(
                f"- EBS volume: {volume['id']} "
                f"({volume['state']}, "
                f"{volume['size']} GiB)"
            )

        for arn in load_balancers:
            print(
                f"- Load balancer: {arn}"
            )

        return False

    print()
    print(
        "No EKS cluster, EBS volume, "
        "or load balancer remains."
    )

    return True


def confirm_destroy(skip_confirmation):
    if skip_confirmation:
        return True

    print()
    print(
        "WARNING: --destroy will remove "
        "the Pac-Man AWS environment."
    )
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
        description=(
            "Pac-Man AWS teardown "
            "and safety verification."
        )
    )

    parser.add_argument(
        "--destroy",
        action="store_true",
        help=(
            "Actually delete Kubernetes "
            "and Terraform resources."
        ),
    )

    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Skip interactive destroy confirmation."
        ),
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Show the full Terraform destroy plan."
        ),
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
        print(
            "ERROR: AWS account does not match "
            "the project account."
        )
        print("No actions were performed.")

        sys.exit(1)

    print()
    print("AWS account verification passed.")

    show_inventory(
        verbose=args.verbose
    )

    if not args.destroy:
        print()
        print("Safety check completed.")
        print("No AWS resources were deleted.")
        print()
        print("To perform teardown:")
        print(
            "python3 scripts/terminate.py --destroy"
        )

        return

    if not confirm_destroy(args.yes):
        print()
        print("Destroy cancelled.")
        print("No resources were deleted.")

        return

    if not kubernetes_cleanup():
        print()
        print(
            "ERROR: Kubernetes cleanup "
            "did not complete safely."
        )
        print(
            "Terraform destroy was NOT started."
        )

        sys.exit(1)

    if not terraform_destroy():
        print()
        print(
            "ERROR: Terraform destroy "
            "did not complete."
        )
        print(
            "Run the script without --destroy "
            "to inspect leftovers."
        )

        sys.exit(1)

    wait_for_cluster_ebs_cleanup()

    if not final_verification():
        sys.exit(1)

    print()
    print("Teardown completed successfully.")


if __name__ == "__main__":
    main()
