#!/usr/bin/env python3

import argparse
import http.client
import json
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


EXPECTED_ACCOUNT_ID = "506456084249"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "pacman-dev"
NAMESPACE = "pacman"
MONITORING_NAMESPACE = "monitoring"
MONITORING_RELEASE = "pacman-monitoring"
MONITORING_CHART = "prometheus-community/kube-prometheus-stack"
MONITORING_CHART_VERSION = "87.21.0"

STATE_BUCKET = "pacman-terraform-state-506456084249-us-east-1"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = PROJECT_ROOT / "terraform"
K8S_DIR = PROJECT_ROOT / "k8s"
MONITORING_VALUES = (
    PROJECT_ROOT / "monitoring" / "kube-prometheus-values.yaml"
)
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci-cd.yml"

REQUIRED_K8S_FILES = [
    "enable-network-policy.yaml",
    "namespace.yaml",
    "storage-class.yaml",
    "mongo-service.yaml",
    "mongo-networkpolicy.yaml",
    "mongo-statefulset.yaml",
    "app-configmap.yaml",
    "app-deployment.yaml",
    "app-service.yaml",
]

RUNTIME_PHASES = [
    "Terraform infrastructure",
    "EKS kubeconfig",
    "Docker build and immutable ECR push",
    "MongoDB StatefulSet and persistent EBS",
    "Pac-Man Deployment and internal HTTP validation",
    "Public NLB attempt and external HTTP validation",
    "Prometheus and Grafana monitoring",
    "Final runtime health summary",
]


def fail(message):
    print()
    print(f"ERROR: {message}")
    sys.exit(1)


def check_tool(name):
    path = shutil.which(name)
    if path is None:
        fail(f"Required tool '{name}' was not found.")
    return path


def run(command, allow_failure=False, input_text=None, live=False, cwd=None):
    if live:
        result = subprocess.run(
            command,
            text=True,
            input=input_text,
            cwd=cwd,
        )
    else:
        result = subprocess.run(
            command,
            text=True,
            input=input_text,
            capture_output=True,
            cwd=cwd,
        )

    if result.returncode != 0 and not allow_failure:
        print()
        print(f"ERROR: Command failed: {' '.join(command)}")
        if not live:
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


def kubectl(args, allow_failure=False, input_text=None):
    return run(
        ["kubectl", *args],
        allow_failure=allow_failure,
        input_text=input_text,
    )


def kubectl_json(args, allow_failure=False):
    result = kubectl(
        [*args, "-o", "json"],
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
        CI_WORKFLOW,
        MONITORING_VALUES,
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
            print(f"- {path.relative_to(PROJECT_ROOT)}")
        fail("Project file check failed.")

    print(f"Required project files: {len(required_paths)}")
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
            "Terraform state bucket was not found or is inaccessible: "
            f"{STATE_BUCKET}"
        )

    print(f"Terraform state bucket: {STATE_BUCKET}")
    print("State bucket verification passed.")


def get_project_cluster():
    data = aws_json(["eks", "list-clusters"])
    return [
        cluster
        for cluster in data.get("clusters", [])
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
        instances.extend(reservation.get("Instances", []))
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


def get_project_vpcs():
    data = aws_json(
        [
            "ec2",
            "describe-vpcs",
            "--filters",
            "Name=tag:Project,Values=pacman",
            "Name=tag:Environment,Values=dev",
        ]
    )
    return data.get("Vpcs", [])


def get_auto_mode_resources():
    data = aws_json(
        [
            "resourcegroupstaggingapi",
            "get-resources",
            "--tag-filters",
            (
                "Key=eks:eks-cluster-name,"
                f"Values={CLUSTER_NAME}"
            ),
        ]
    )

    return [
        item["ResourceARN"]
        for item in data.get("ResourceTagMappingList", [])
    ]


def get_project_load_balancers():
    return [
        arn
        for arn in get_auto_mode_resources()
        if ":elasticloadbalancing:" in arn
        and ":loadbalancer/" in arn
    ]


def get_project_target_groups():
    return [
        arn
        for arn in get_auto_mode_resources()
        if ":elasticloadbalancing:" in arn
        and ":targetgroup/" in arn
    ]


def verify_runtime_is_off():
    print()
    print("=== AWS Runtime Safety Check ===")

    clusters = get_project_cluster()
    instances = get_project_instances()
    volumes = get_project_ebs()
    load_balancers = get_project_load_balancers()
    target_groups = get_project_target_groups()
    vpcs = get_project_vpcs()

    print(f"EKS clusters  : {len(clusters)}")
    print(f"EC2 instances : {len(instances)}")
    print(f"EBS volumes   : {len(volumes)}")
    print(f"Load balancers: {len(load_balancers)}")
    print(f"Target groups : {len(target_groups)}")
    print(f"Project VPCs  : {len(vpcs)}")

    if (
        clusters
        or instances
        or volumes
        or load_balancers
        or target_groups
        or vpcs
    ):
        fail(
            "Pac-Man runtime resources already exist. "
            "Run scripts/terminate.py before a clean launch."
        )

    print("No active Pac-Man runtime resources detected.")


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
        if result.stdout.strip():
            print(result.stdout.strip())
        fail(
            "Terraform formatting check failed. Run: "
            "terraform -chdir=terraform fmt -recursive"
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

    if result.stdout.strip():
        print(result.stdout.strip())


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
        for resource in resources:
            print(f"- {resource}")
        fail(
            "Root Terraform state is not empty. "
            "Refusing a clean launch."
        )

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
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip())
        fail("Terraform plan failed.")

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


def get_git_sha():
    result = run(
        [
            "git",
            "-C",
            str(PROJECT_ROOT),
            "rev-parse",
            "HEAD",
        ]
    )
    return result.stdout.strip()


def verify_git_tree(require_clean):
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

    status = result.stdout.strip()
    if status:
        print(status)
        if require_clean:
            fail(
                "Working tree must be clean before --apply so the "
                "immutable Git SHA matches the image."
            )
        print("Preview warning: local changes are present.")
        return

    print("Git working tree is clean.")


def show_runtime_plan():
    print()
    print("=== Runtime Launch Plan ===")
    for index, phase in enumerate(RUNTIME_PHASES, start=1):
        print(f"{index}. {phase}")


def confirm_apply(skip_confirmation):
    if skip_confirmation:
        return True

    print()
    print("WARNING: --apply creates billable AWS resources.")
    print(f"Cluster : {CLUSTER_NAME}")
    print(f"Account : {EXPECTED_ACCOUNT_ID}")
    print(f"Region  : {AWS_REGION}")
    print()

    answer = input(
        f"Type '{CLUSTER_NAME}' to create the environment: "
    ).strip()
    return answer == CLUSTER_NAME


def terraform_apply():
    print()
    print("=== Terraform Apply ===")

    result = run(
        [
            "terraform",
            f"-chdir={TERRAFORM_DIR}",
            "apply",
            "-auto-approve",
            "-input=false",
            "-no-color",
        ],
        live=True,
        allow_failure=True,
    )

    if result.returncode != 0:
        fail(
            "Terraform apply failed. Review the output and use "
            "scripts/terminate.py for cleanup if needed."
        )


def terraform_output(name):
    result = run(
        [
            "terraform",
            f"-chdir={TERRAFORM_DIR}",
            "output",
            "-raw",
            name,
        ]
    )

    value = result.stdout.strip()
    if not value:
        fail(f"Terraform output '{name}' is empty.")
    return value


def configure_kubeconfig():
    print()
    print("=== EKS Kubernetes Access ===")

    run(
        [
            "aws",
            "eks",
            "wait",
            "cluster-active",
            "--name",
            CLUSTER_NAME,
            "--region",
            AWS_REGION,
        ],
        live=True,
    )

    run(
        [
            "aws",
            "eks",
            "update-kubeconfig",
            "--region",
            AWS_REGION,
            "--name",
            CLUSTER_NAME,
        ],
        live=True,
    )

    result = kubectl(["cluster-info"])
    if result.stdout.strip():
        print(result.stdout.strip())


def docker_login(ecr_repository_url):
    registry = ecr_repository_url.split("/", 1)[0]

    password_result = run(
        [
            "aws",
            "ecr",
            "get-login-password",
            "--region",
            AWS_REGION,
        ]
    )

    login = run(
        [
            "docker",
            "login",
            "--username",
            "AWS",
            "--password-stdin",
            registry,
        ],
        input_text=password_result.stdout,
        allow_failure=True,
    )

    if login.returncode != 0:
        if login.stderr.strip():
            print(login.stderr.strip())
        fail("Docker login to Amazon ECR failed.")


def build_and_push_image(ecr_repository_url, git_sha):
    print()
    print("=== Docker Build and ECR Push ===")

    bootstrap_tag = f"bootstrap-{git_sha}"
    local_image = f"pacman-launch:{bootstrap_tag}"
    image_uri = f"{ecr_repository_url}:{bootstrap_tag}"

    run(
        [
            "docker",
            "build",
            "--platform",
            "linux/amd64",
            "-t",
            local_image,
            ".",
        ],
        live=True,
        cwd=PROJECT_ROOT,
    )

    uid = run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "id",
            local_image,
            "-u",
        ]
    ).stdout.strip()

    print(f"Container UID: {uid}")
    if uid == "0":
        fail("Container image runs as root.")

    docker_login(ecr_repository_url)

    run(["docker", "tag", local_image, image_uri])
    run(["docker", "push", image_uri], live=True)

    print(f"Immutable image pushed: {image_uri}")
    return image_uri


def apply_manifest(filename):
    path = K8S_DIR / filename
    result = kubectl(["apply", "-f", str(path)])
    if result.stdout.strip():
        print(result.stdout.strip())


def wait_rollout(resource, namespace, timeout):
    run(
        [
            "kubectl",
            "rollout",
            "status",
            resource,
            "-n",
            namespace,
            f"--timeout={timeout}",
        ],
        live=True,
    )


def deploy_mongodb():
    print()
    print("=== Kubernetes Base and MongoDB ===")

    apply_manifest("enable-network-policy.yaml")

    for filename in (
        "namespace.yaml",
        "storage-class.yaml",
        "mongo-service.yaml",
        "mongo-networkpolicy.yaml",
        "mongo-statefulset.yaml",
    ):
        apply_manifest(filename)

    wait_rollout("statefulset/mongo", NAMESPACE, "10m")

    run(
        [
            "kubectl",
            "wait",
            "--for=condition=Ready",
            "pod/mongo-0",
            "-n",
            NAMESPACE,
            "--timeout=5m",
        ],
        live=True,
    )


def verify_persistent_storage():
    print()
    print("=== Persistent Storage Verification ===")

    pvc_data = kubectl_json(["get", "pvc", "-n", NAMESPACE])

    bound_pvcs = [
        pvc
        for pvc in pvc_data.get("items", [])
        if pvc.get("status", {}).get("phase") == "Bound"
    ]

    if not bound_pvcs:
        fail("No Bound PVC was found for MongoDB.")

    pvc = bound_pvcs[0]
    pvc_name = pvc["metadata"]["name"]
    pv_name = pvc["spec"].get("volumeName")

    if not pv_name:
        fail(f"PVC {pvc_name} has no PersistentVolume.")

    pv = kubectl_json(["get", "pv", pv_name])
    csi = pv.get("spec", {}).get("csi", {})
    volume_id = csi.get("volumeHandle")

    if not volume_id:
        fail(f"PV {pv_name} has no EBS volume handle.")

    data = aws_json(
        [
            "ec2",
            "describe-volumes",
            "--include-managed-resources",
            "--volume-ids",
            volume_id,
        ]
    )

    volumes = data.get("Volumes", [])
    if not volumes:
        fail(f"EBS volume {volume_id} was not found.")

    volume = volumes[0]

    print(f"PVC       : {pvc_name}")
    print(f"PV        : {pv_name}")
    print(f"EBS       : {volume_id}")
    print(f"Type      : {volume['VolumeType']}")
    print(f"Size      : {volume['Size']} GiB")
    print(f"Encrypted : {volume['Encrypted']}")
    print(f"State     : {volume['State']}")

    if volume["VolumeType"] != "gp3":
        fail("MongoDB EBS volume is not gp3.")
    if not volume["Encrypted"]:
        fail("MongoDB EBS volume is not encrypted.")


def render_app_deployment(image_uri):
    deployment_path = K8S_DIR / "app-deployment.yaml"
    content = deployment_path.read_text()

    rendered, count = re.subn(
        r"^(\s*image:\s*).+$",
        rf"\g<1>{image_uri}",
        content,
        count=1,
        flags=re.MULTILINE,
    )

    if count != 1:
        fail(
            "Could not replace the Pac-Man image in "
            "app-deployment.yaml."
        )

    return rendered


def wait_for_database_connection(timeout=90):
    deadline = time.time() + timeout
    last_logs = ""

    while time.time() < deadline:
        result = kubectl(
            [
                "logs",
                "deployment/pacman",
                "-n",
                NAMESPACE,
                "--tail=100",
            ],
            allow_failure=True,
        )

        if result.returncode == 0:
            last_logs = result.stdout
            if "Connected to database server successfully" in last_logs:
                print("Pac-Man connected to MongoDB successfully.")
                return

        time.sleep(5)

    if last_logs.strip():
        print(last_logs.strip())

    fail(
        "Pac-Man did not confirm MongoDB connectivity "
        "within the expected time."
    )


def find_free_local_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def http_status(host, port, path="/", timeout=3):
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def verify_internal_http():
    print()
    print("=== Pac-Man Internal HTTP Verification ===")

    port = find_free_local_port()

    process = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            "-n",
            NAMESPACE,
            "deployment/pacman",
            f"{port}:8080",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    deadline = time.time() + 45

    try:
        while time.time() < deadline:
            if process.poll() is not None:
                stderr = process.stderr.read().strip()
                if stderr:
                    print(stderr)
                fail("kubectl port-forward exited unexpectedly.")

            try:
                status = http_status("127.0.0.1", port, timeout=2)
                if status == 200:
                    print("Pac-Man internal HTTP 200: OK")
                    return
            except OSError:
                pass

            time.sleep(2)

        fail("Pac-Man internal HTTP validation timed out.")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def deploy_pacman(image_uri):
    print()
    print("=== Pac-Man Deployment ===")

    apply_manifest("app-configmap.yaml")

    rendered = render_app_deployment(image_uri)
    result = kubectl(["apply", "-f", "-"], input_text=rendered)
    if result.stdout.strip():
        print(result.stdout.strip())

    wait_rollout("deployment/pacman", NAMESPACE, "10m")
    wait_for_database_connection()
    verify_internal_http()


def get_nlb_endpoint():
    service = kubectl_json(
        [
            "get",
            "service",
            "pacman",
            "-n",
            NAMESPACE,
        ],
        allow_failure=True,
    )

    if not service:
        return None

    ingress = (
        service.get("status", {})
        .get("loadBalancer", {})
        .get("ingress", [])
    )

    if not ingress:
        return None

    return ingress[0].get("hostname") or ingress[0].get("ip")


def nlb_account_is_blocked():
    result = kubectl(
        [
            "describe",
            "service",
            "pacman",
            "-n",
            NAMESPACE,
        ],
        allow_failure=True,
    )

    output = f"{result.stdout}\n{result.stderr}"
    return (
        "OperationNotPermitted" in output
        and "does not support creating load balancers" in output
    )


def verify_external_http(endpoint, timeout=180):
    print(f"NLB endpoint: {endpoint}")
    print("Waiting for external HTTP 200...")

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status = http_status(endpoint, 80, timeout=5)
            if status == 200:
                print("Pac-Man external HTTP 200: OK")
                return
        except OSError:
            pass

        time.sleep(10)

    fail(
        "NLB endpoint was created, but external HTTP 200 "
        "was not observed before timeout."
    )


def create_and_verify_nlb():
    print()
    print("=== Public Network Load Balancer ===")

    apply_manifest("app-service.yaml")

    deadline = time.time() + 180
    while time.time() < deadline:
        endpoint = get_nlb_endpoint()
        if endpoint:
            verify_external_http(endpoint)
            return "OK"

        if nlb_account_is_blocked():
            print()
            print(
                "WARNING: AWS rejected CreateLoadBalancer with "
                "OperationNotPermitted."
            )
            print(
                "The Kubernetes Service is configured, but this "
                "AWS account is currently restricted from creating "
                "load balancers."
            )
            print(
                "Continuing with monitoring. Public NLB acceptance "
                "remains BLOCKED externally."
            )
            return "BLOCKED_BY_AWS"

        time.sleep(10)

    fail(
        "NLB did not receive an endpoint and no known AWS account "
        "restriction was detected."
    )


def install_monitoring():
    print()
    print("=== Prometheus and Grafana ===")

    add_repo = run(
        [
            "helm",
            "repo",
            "add",
            "prometheus-community",
            "https://prometheus-community.github.io/helm-charts",
        ],
        allow_failure=True,
    )

    if add_repo.returncode != 0:
        output = f"{add_repo.stdout}\n{add_repo.stderr}"
        if "already exists" not in output:
            if output.strip():
                print(output.strip())
            fail("Could not configure the Prometheus Helm repo.")

    run(["helm", "repo", "update"], live=True)

    run(
        [
            "helm",
            "upgrade",
            "--install",
            MONITORING_RELEASE,
            MONITORING_CHART,
            "--version",
            MONITORING_CHART_VERSION,
            "--namespace",
            MONITORING_NAMESPACE,
            "--create-namespace",
            "-f",
            str(MONITORING_VALUES),
            "--wait",
            "--timeout",
            "10m",
        ],
        live=True,
    )

    pods = kubectl_json(
        [
            "get",
            "pods",
            "-n",
            MONITORING_NAMESPACE,
        ]
    )

    if not pods.get("items"):
        fail("No monitoring pods were created.")

    not_ready = []
    for pod in pods["items"]:
        name = pod["metadata"]["name"]
        phase = pod.get("status", {}).get("phase")
        statuses = pod.get("status", {}).get(
            "containerStatuses",
            [],
        )
        containers_ready = (
            bool(statuses)
            and all(status.get("ready") for status in statuses)
        )

        if phase != "Running" or not containers_ready:
            not_ready.append(name)

    if not_ready:
        print("Monitoring pods not ready:")
        for name in not_ready:
            print(f"- {name}")
        fail("Monitoring installation is not healthy.")

    result = kubectl(
        [
            "get",
            "pods",
            "-n",
            MONITORING_NAMESPACE,
        ]
    )
    print(result.stdout.strip())
    print("Monitoring workloads are Ready.")


def final_summary(image_uri, nlb_status):
    print()
    print("=== Final Runtime Summary ===")

    print(f"Cluster       : {CLUSTER_NAME}")
    print(f"Namespace     : {NAMESPACE}")
    print(f"Image         : {image_uri}")
    print("MongoDB       : OK")
    print("Persistent EBS: OK")
    print("Internal HTTP : OK")
    print(f"Public NLB    : {nlb_status}")
    print("Monitoring    : OK")

    print()
    print("Pac-Man resources:")
    result = kubectl(
        [
            "get",
            "pods,svc,pvc",
            "-n",
            NAMESPACE,
        ]
    )
    print(result.stdout.strip())

    print()
    print("Grafana access:")
    print(
        "kubectl port-forward -n monitoring "
        "svc/pacman-monitoring-grafana 3000:80"
    )
    print("Open: http://localhost:3000")
    print("User: admin")
    print("Password:")
    print(
        "kubectl get secret pacman-monitoring-grafana "
        "-n monitoring "
        "-o jsonpath='{.data.admin-password}' "
        "| base64 --decode; echo"
    )

    print()
    print(
        "CI/CD: pushes to main will use GitHub OIDC to build, "
        "scan, push and deploy a new immutable image while this "
        "EKS runtime exists."
    )

    if nlb_status == "BLOCKED_BY_AWS":
        print()
        print(
            "Launch completed with one external blocker: "
            "AWS account-level load balancer creation restriction."
        )
    else:
        print()
        print("Launch completed successfully.")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Pac-Man AWS launch preview and runtime deployment."
        )
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Create the AWS/Kubernetes runtime after preflight "
            "checks and confirmation."
        ),
    )

    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Skip the interactive --apply confirmation. "
            "Only valid with --apply."
        ),
    )

    return parser.parse_args()


def main():
    args = parse_args()

    if args.yes and not args.apply:
        fail("--yes is only valid together with --apply.")

    print("=== Pac-Man AWS Launch ===")
    print()
    print(
        "Mode: "
        + (
            "APPLY - creates billable resources"
            if args.apply
            else "PREVIEW ONLY"
        )
    )

    print()
    print("=== Required Tools ===")

    for tool in (
        "aws",
        "terraform",
        "git",
        "docker",
        "kubectl",
        "helm",
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

    verify_git_tree(require_clean=args.apply)
    show_runtime_plan()

    if not args.apply:
        print()
        print("=== Preview Complete ===")
        print("No AWS runtime resources were created.")
        print()
        print("To create the environment:")
        print("python3 scripts/launch.py --apply")
        return

    if not confirm_apply(args.yes):
        print()
        print("Launch cancelled.")
        print("No terraform apply was started.")
        return

    git_sha = get_git_sha()

    terraform_apply()

    ecr_repository_url = terraform_output("ecr_repository_url")

    configure_kubeconfig()

    image_uri = build_and_push_image(
        ecr_repository_url,
        git_sha,
    )

    deploy_mongodb()
    verify_persistent_storage()

    deploy_pacman(image_uri)

    nlb_status = create_and_verify_nlb()

    install_monitoring()

    final_summary(image_uri, nlb_status)


if __name__ == "__main__":
    main()
