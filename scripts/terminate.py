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
MONITORING_NAMESPACE = "monitoring"
MONITORING_RELEASE = "pacman-monitoring"
STORAGE_CLASS = "gp3-auto"
AUTO_MODE_CSI_DRIVER = "ebs.csi.eks.amazonaws.com"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = PROJECT_ROOT / "terraform"

EXPECTED_KUBE_CONTEXT = (
    f"arn:aws:eks:{AWS_REGION}:{EXPECTED_ACCOUNT_ID}:cluster/{CLUSTER_NAME}"
)


def fail(message):
    print()
    print(f"ERROR: {message}")
    sys.exit(1)


def check_tool(name):
    if shutil.which(name) is None:
        fail(f"Required tool '{name}' was not found.")


def run_command(command, allow_failure=False, live=False):
    if live:
        result = subprocess.run(command, text=True)
    else:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
        )

    if result.returncode != 0 and not allow_failure:
        print(f"ERROR: Command failed: {' '.join(command)}")
        if not live:
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


def run_aws(args, allow_failure=False, live=False):
    return run_command(
        [
            "aws",
            *args,
            "--region",
            AWS_REGION,
            "--no-cli-pager",
        ],
        allow_failure=allow_failure,
        live=live,
    )


def run_kubectl(args, allow_failure=False, live=False):
    return run_command(
        [
            "kubectl",
            "--context",
            EXPECTED_KUBE_CONTEXT,
            *args,
        ],
        allow_failure=allow_failure,
        live=live,
    )


def run_helm(args, allow_failure=False, live=False):
    return run_command(
        [
            "helm",
            "--kube-context",
            EXPECTED_KUBE_CONTEXT,
            *args,
        ],
        allow_failure=allow_failure,
        live=live,
    )


def kubectl_json(args, allow_failure=False):
    result = run_kubectl(
        [*args, "-o", "json"],
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
    data = run_aws_json(["eks", "list-clusters"])
    return [
        name
        for name in data.get("clusters", [])
        if name == CLUSTER_NAME
    ]


def cluster_exists():
    return bool(get_eks_clusters())


def get_project_instances():
    data = run_aws_json(
        [
            "ec2",
            "describe-instances",
            "--include-managed-resources",
            "--filters",
            f"Name=tag:eks:eks-cluster-name,Values={CLUSTER_NAME}",
            (
                "Name=instance-state-name,"
                "Values=pending,running,stopping,stopped"
            ),
        ]
    )

    instances = []
    for reservation in data.get("Reservations", []):
        instances.extend(reservation.get("Instances", []))
    return instances


def get_project_vpcs():
    data = run_aws_json(
        [
            "ec2",
            "describe-vpcs",
            "--filters",
            f"Name=tag:Project,Values={PROJECT_NAME}",
            f"Name=tag:Environment,Values={ENVIRONMENT}",
        ]
    )
    return data.get("Vpcs", [])


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
        fail(f"Could not inspect EBS volume {volume_id}.")

    data = json.loads(result.stdout)
    volumes = data.get("Volumes", [])
    return volumes[0] if volumes else None


def volume_exists(volume_id):
    return get_volume(volume_id) is not None


def terraform_state_resources():
    result = run_command(
        [
            "terraform",
            f"-chdir={TERRAFORM_DIR}",
            "state",
            "list",
        ],
        allow_failure=True,
    )

    if result.returncode != 0:
        return None

    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
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
            if stripped.startswith("Plan:") or "No changes." in stripped:
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
        live=True,
    )

    if result.returncode != 0:
        print("ERROR: Terraform destroy failed.")
        return False

    return True


def ensure_kube_context():
    result = run_command(
        [
            "kubectl",
            "config",
            "get-contexts",
            "-o",
            "name",
        ]
    )

    if EXPECTED_KUBE_CONTEXT in result.stdout.splitlines():
        return True

    print("Expected kubeconfig context is missing; recreating it...")

    update = run_command(
        [
            "aws",
            "eks",
            "update-kubeconfig",
            "--region",
            AWS_REGION,
            "--name",
            CLUSTER_NAME,
        ],
        allow_failure=True,
        live=True,
    )

    return update.returncode == 0


def namespace_exists(namespace):
    result = run_kubectl(
        ["get", "namespace", namespace],
        allow_failure=True,
    )
    return result.returncode == 0


def get_persistent_volume_ids():
    if not cluster_exists() or not namespace_exists(NAMESPACE):
        return []

    pvc_data = kubectl_json(
        ["get", "pvc", "-n", NAMESPACE],
        allow_failure=True,
    )

    if not pvc_data:
        return []

    volume_ids = []

    for pvc in pvc_data.get("items", []):
        pv_name = pvc.get("spec", {}).get("volumeName")
        if not pv_name:
            continue

        pv = kubectl_json(["get", "pv", pv_name], allow_failure=True)
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


def uninstall_monitoring():
    if not namespace_exists(MONITORING_NAMESPACE):
        print("Monitoring namespace does not exist; skipping monitoring cleanup.")
        return

    print()
    print("=== Monitoring Cleanup ===")

    check_tool("helm")

    status = run_helm(
        [
            "status",
            MONITORING_RELEASE,
            "-n",
            MONITORING_NAMESPACE,
        ],
        allow_failure=True,
    )

    if status.returncode == 0:
        print(f"Uninstalling Helm release: {MONITORING_RELEASE}")
        run_helm(
            [
                "uninstall",
                MONITORING_RELEASE,
                "-n",
                MONITORING_NAMESPACE,
            ],
            allow_failure=True,
            live=True,
        )
    else:
        print("Monitoring Helm release not found; continuing.")

    print(f"Deleting namespace: {MONITORING_NAMESPACE}")
    run_kubectl(
        [
            "delete",
            "namespace",
            MONITORING_NAMESPACE,
            "--ignore-not-found=true",
            "--wait=true",
            "--timeout=180s",
        ],
        allow_failure=True,
        live=True,
    )


def delete_load_balancer_services():
    services = kubectl_json(
        ["get", "services", "--all-namespaces"],
        allow_failure=True,
    )

    if not services:
        return

    for service in services.get("items", []):
        if service.get("spec", {}).get("type") != "LoadBalancer":
            continue

        namespace = service["metadata"]["namespace"]
        name = service["metadata"]["name"]

        print(f"Deleting LoadBalancer Service: {namespace}/{name}")
        run_kubectl(
            [
                "delete",
                "service",
                name,
                "-n",
                namespace,
                "--ignore-not-found=true",
                "--wait=false",
            ],
            allow_failure=True,
            live=True,
        )


def delete_ingresses():
    ingresses = kubectl_json(
        ["get", "ingress", "--all-namespaces"],
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
                "--wait=false",
            ],
            allow_failure=True,
            live=True,
        )


def delete_remaining_elb_resources():
    load_balancers = get_cluster_load_balancers()

    for arn in load_balancers:
        print(f"Deleting remaining load balancer: {arn}")
        run_aws(
            [
                "elbv2",
                "delete-load-balancer",
                "--load-balancer-arn",
                arn,
            ],
            allow_failure=True,
        )

    if load_balancers:
        if not wait_until(
            "load balancer deletion",
            lambda: len(get_cluster_load_balancers()) == 0,
            timeout=300,
            interval=10,
        ):
            return False

    target_groups = get_cluster_target_groups()

    for arn in target_groups:
        print(f"Deleting remaining target group: {arn}")
        run_aws(
            [
                "elbv2",
                "delete-target-group",
                "--target-group-arn",
                arn,
            ],
            allow_failure=True,
        )

    if target_groups:
        return wait_until(
            "target group deletion",
            lambda: len(get_cluster_target_groups()) == 0,
            timeout=300,
            interval=10,
        )

    return True


def delete_workloads():
    if not namespace_exists(NAMESPACE):
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
        live=True,
    )


def delete_pvcs():
    if not namespace_exists(NAMESPACE):
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
        live=True,
    )


def wait_for_persistent_volumes_to_delete(volume_ids):
    if not volume_ids:
        print("No Kubernetes persistent EBS volumes need cleanup.")
        return True

    print("Persistent EBS volumes captured before PVC deletion:")
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

    print("Persistent EBS volumes still present after PVC deletion.")

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

        print(f"Deleting orphaned persistent EBS volume: {volume_id}")
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


def delete_namespace_and_storage_class():
    if namespace_exists(NAMESPACE):
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
            live=True,
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
        live=True,
    )


def kubernetes_cleanup():
    if not cluster_exists():
        print("EKS cluster does not exist. Skipping Kubernetes cleanup.")
        return True

    check_tool("kubectl")

    if not ensure_kube_context():
        print("ERROR: Could not configure the expected kubeconfig context.")
        return False

    print()
    print("=== Kubernetes Cleanup ===")

    persistent_volume_ids = get_persistent_volume_ids()

    uninstall_monitoring()

    delete_load_balancer_services()
    delete_ingresses()

    wait_until(
        "Kubernetes load balancer cleanup",
        lambda: len(get_cluster_load_balancers()) == 0,
        timeout=300,
        interval=10,
    )

    if not delete_remaining_elb_resources():
        return False

    delete_workloads()
    delete_pvcs()

    if not wait_for_persistent_volumes_to_delete(persistent_volume_ids):
        return False

    delete_namespace_and_storage_class()
    return True


def wait_for_cluster_runtime_cleanup():
    instances_ok = wait_until(
        "Auto Mode EC2 cleanup",
        lambda: len(get_project_instances()) == 0,
        timeout=600,
        interval=15,
    )

    ebs_ok = wait_until(
        "Auto Mode EBS cleanup",
        lambda: len(get_cluster_ebs_volumes()) == 0,
        timeout=600,
        interval=15,
    )

    return instances_ok and ebs_ok


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
        fail("Terraform destroy preview failed.")

    print()
    print("=== AWS Runtime Inventory ===")

    tagged = get_tagged_project_resources()
    auto_mode = get_auto_mode_resources()
    ebs = get_cluster_ebs_volumes()
    instances = get_project_instances()
    load_balancers = get_cluster_load_balancers()
    target_groups = get_cluster_target_groups()
    clusters = get_eks_clusters()
    vpcs = get_project_vpcs()

    persistent_ebs = []
    if clusters and ensure_kube_context():
        persistent_ebs = get_persistent_volume_ids()

    print(f"Tagged project resources : {len(tagged)}")
    print(f"Auto Mode resources      : {len(auto_mode)}")
    print(f"Active Auto Mode EC2     : {len(instances)}")
    print(f"All cluster EBS volumes  : {len(ebs)}")
    print(f"Persistent workload EBS  : {len(persistent_ebs)}")
    print(f"Load balancers           : {len(load_balancers)}")
    print(f"Target groups            : {len(target_groups)}")
    print(f"Project VPCs             : {len(vpcs)}")
    print(f"EKS clusters             : {len(clusters)}")

    for instance in instances:
        print(
            f"  EC2: {instance['InstanceId']} "
            f"({instance['State']['Name']}, {instance['InstanceType']})"
        )

    for volume in ebs:
        print(
            f"  EBS: {volume['id']} "
            f"({volume['state']}, {volume['size']} GiB)"
        )

    for arn in load_balancers:
        print(f"  LB : {arn}")

    for arn in target_groups:
        print(f"  TG : {arn}")

    for vpc in vpcs:
        print(f"  VPC: {vpc['VpcId']}")

    for cluster in clusters:
        print(f"  EKS: {cluster}")


def final_verification():
    print()
    print("=== Final Orphan Verification ===")

    clusters = get_eks_clusters()
    instances = get_project_instances()
    volumes = get_cluster_ebs_volumes()
    load_balancers = get_cluster_load_balancers()
    target_groups = get_cluster_target_groups()
    vpcs = get_project_vpcs()
    state_resources = terraform_state_resources()

    print(f"EKS clusters       : {len(clusters)}")
    print(f"Active AutoMode EC2: {len(instances)}")
    print(f"EBS volumes        : {len(volumes)}")
    print(f"Load balancers     : {len(load_balancers)}")
    print(f"Target groups      : {len(target_groups)}")
    print(f"Project VPCs       : {len(vpcs)}")

    if state_resources is None:
        print("Terraform state    : ERROR")
    else:
        print(f"Terraform resources: {len(state_resources)}")

    leftovers = bool(
        clusters
        or instances
        or volumes
        or load_balancers
        or target_groups
        or vpcs
        or state_resources
        or state_resources is None
    )

    if leftovers:
        print()
        print("ERROR: Potential project resources still remain.")

        for cluster in clusters:
            print(f"- EKS cluster: {cluster}")

        for instance in instances:
            print(
                f"- EC2 instance: {instance['InstanceId']} "
                f"({instance['State']['Name']})"
            )

        for volume in volumes:
            print(
                f"- EBS volume: {volume['id']} "
                f"({volume['state']}, {volume['size']} GiB)"
            )

        for arn in load_balancers:
            print(f"- Load balancer: {arn}")

        for arn in target_groups:
            print(f"- Target group: {arn}")

        for vpc in vpcs:
            print(f"- VPC: {vpc['VpcId']}")

        if state_resources:
            for resource in state_resources:
                print(f"- Terraform state: {resource}")

        return False

    print()
    print(
        "No EKS cluster, active Auto Mode EC2, EBS volume, "
        "load balancer, target group, project VPC or Terraform "
        "runtime state remains."
    )
    print("The remote Terraform state S3 bucket is retained intentionally.")
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
        description=(
            "Pac-Man AWS teardown preview, cleanup and orphan verification."
        )
    )

    parser.add_argument(
        "--destroy",
        action="store_true",
        help=(
            "Actually delete Kubernetes, monitoring and Terraform resources."
        ),
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

    if args.yes and not args.destroy:
        fail("--yes is only valid together with --destroy.")

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
        fail(
            "AWS account does not match the project account. "
            "No actions were performed."
        )

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
        fail(
            "Kubernetes cleanup did not complete safely. "
            "Terraform destroy was NOT started."
        )

    if not terraform_destroy():
        fail(
            "Terraform destroy did not complete. "
            "Run the script without --destroy to inspect leftovers."
        )

    wait_for_cluster_runtime_cleanup()

    if not final_verification():
        sys.exit(1)

    print()
    print("Teardown completed successfully.")


if __name__ == "__main__":
    main()
