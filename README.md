# Pac-Man on AWS EKS Auto Mode

DevSecOps final project that deploys a containerized Pac-Man application and MongoDB to Amazon EKS Auto Mode.

The project focuses on a reproducible AWS/Kubernetes architecture, automated launch and teardown, CI/CD, persistent storage, monitoring and practical security controls.

## Architecture

The environment runs in `us-east-1` and contains:

- Terraform-managed VPC and two public subnets across two Availability Zones
- Amazon EKS Auto Mode
- Amazon ECR
- Pac-Man Kubernetes Deployment
- MongoDB StatefulSet
- encrypted `gp3` EBS persistent storage
- internet-facing AWS Network Load Balancer through EKS Auto Mode
- GitHub Actions CI/CD using AWS OIDC
- Prometheus and Grafana using `kube-prometheus-stack`

Traffic and deployment flow:

```text
GitHub
   |
   v
GitHub Actions --OIDC--> AWS IAM
   |                        |
   |                        v
   +---- build/scan -----> ECR
                            |
                            v
Internet --> NLB --> Pac-Man Service --> Pac-Man Pod
                                      |
                                      v
                                 MongoDB StatefulSet
                                      |
                                      v
                                  encrypted EBS

Prometheus <---- Kubernetes / node metrics
    |
    v
 Grafana
```

Architecture files:

- `docs/architecture.drawio`
- `docs/architecture.png`

The project intentionally uses public subnets and no NAT Gateway to keep the lab architecture simple and cost-conscious. A production design would normally use stronger network isolation.

## Repository Structure

```text
.
├── .github/workflows/ci-cd.yml
├── docs/
│   ├── architecture.drawio
│   └── architecture.png
├── k8s/
│   ├── namespace.yaml
│   ├── storage-class.yaml
│   ├── mongo-service.yaml
│   ├── mongo-statefulset.yaml
│   ├── app-configmap.yaml
│   ├── app-deployment.yaml
│   └── app-service.yaml
├── monitoring/kube-prometheus-values.yaml
├── scripts/
│   ├── launch.py
│   └── terminate.py
├── terraform/
│   ├── bootstrap/
│   ├── modules/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── versions.tf
├── Dockerfile
├── package.json
├── package-lock.json
└── README.md
```

## Prerequisites

Required locally:

- AWS CLI v2
- Terraform
- Docker
- kubectl
- Helm
- Git
- Python 3

AWS CLI must already be authenticated to the project AWS account and have sufficient permissions to create and destroy the environment.

Verify the active AWS identity before running the project:

```bash
aws sts get-caller-identity
```

The scripts also verify the expected account automatically before making changes.

## Application Container

The Pac-Man image uses:

```text
node:22-bookworm-slim
```

The image:

- installs production dependencies with `npm ci --omit=dev`
- runs as the non-root `node` user
- exposes port `8080`
- is built for `linux/amd64`
- is tagged with the exact Git commit SHA for runtime deployment

The launch script verifies that the built container does not run as UID `0` before pushing it to ECR.

## Terraform

Terraform manages the AWS foundation:

- VPC `10.0.0.0/16`
- public subnet `10.0.1.0/24` in `us-east-1a`
- public subnet `10.0.2.0/24` in `us-east-1b`
- Internet Gateway and public routing
- ECR repository
- EKS Auto Mode cluster
- EKS IAM roles
- GitHub Actions OIDC provider and IAM role
- namespace-scoped EKS access for GitHub Actions

Terraform state is stored remotely in an encrypted, versioned S3 bucket.

The remote-state bucket is intentionally retained after runtime teardown.

## Kubernetes

The application namespace is:

```text
pacman
```

### MongoDB

MongoDB runs as a single-replica StatefulSet using:

```text
mongo:3.4.24
```

It uses:

- headless Service `mongo`
- port `27017`
- `1Gi` PVC
- EKS Auto Mode EBS CSI provisioning
- encrypted `gp3` storage
- `WaitForFirstConsumer`
- `ReadWriteOnce`

Persistence was runtime-tested by inserting data, deleting the MongoDB Pod and verifying that the recreated StatefulSet Pod used the same persistent storage and retained the data.

### Pac-Man

Pac-Man runs as a single-replica Deployment.

Runtime controls include:

- UID/GID `1000`
- `runAsNonRoot: true`
- privilege escalation disabled
- all Linux capabilities dropped
- CPU and memory requests/limits
- HTTP readiness probe

MongoDB configuration is provided through the Pac-Man ConfigMap:

```text
MONGO_SERVICE_HOST=mongo
MONGO_DATABASE=pacman
MY_MONGO_PORT=27017
MONGO_USE_SSL=false
MONGO_VALIDATE_SSL=false
MONGO_URL=mongodb://mongo:27017/pacman
```

The deployment manifest contains a repository image placeholder, but the launch workflow injects the exact immutable ECR image URI for the current Git SHA before applying the Deployment. GitHub Actions also updates the running Deployment with the exact SHA image it built and scanned.

## Launch Workflow

The main operational entry point is:

```text
scripts/launch.py
```

### Preview only

Run:

```bash
python3 scripts/launch.py
```

This performs safe checks without creating AWS runtime resources:

- required tools and files
- AWS account and region
- Terraform state bucket
- absence of an existing Pac-Man runtime
- Terraform init
- Terraform formatting
- Terraform validation
- empty runtime Terraform state
- Terraform creation plan
- Git working tree status

A clean destroyed environment should produce a Terraform plan similar to:

```text
Plan: 25 to add, 0 to change, 0 to destroy.
```

### Create the environment

Run from a clean Git working tree:

```bash
python3 scripts/launch.py --apply
```

The script requires explicit confirmation before starting the real deployment.

For non-interactive execution:

```bash
python3 scripts/launch.py --apply --yes
```

`--yes` should only be used when the target account and intended cost are already understood.

The runtime workflow is:

```text
Preflight checks
    |
Terraform apply
    |
EKS ACTIVE + kubeconfig
    |
Docker linux/amd64 build
    |
non-root image verification
    |
ECR login + immutable Git SHA push
    |
namespace + StorageClass
    |
MongoDB StatefulSet + PVC/EBS verification
    |
Pac-Man Deployment
    |
MongoDB connectivity check
    |
internal HTTP 200 check
    |
NLB Service / external HTTP check
    |
Prometheus + Grafana install
    |
final runtime summary
```

If any normal required deployment step fails, the launch exits with an error so the failure is visible rather than silently ignored.

## Network Load Balancer

The Pac-Man Service is configured as:

```text
type: LoadBalancer
loadBalancerClass: eks.amazonaws.com/nlb
```

with:

```text
internet-facing
NLB target type: ip
```

Expected traffic flow:

```text
Internet
   |
AWS NLB :80
   |
Pac-Man Service
   |
Pac-Man Pod :8080
```

### Current AWS account restriction

The architecture and Kubernetes Service are configured for EKS Auto Mode NLB provisioning, but the project AWS account currently returns an account-level AWS error when `CreateLoadBalancer` is attempted:

```text
OperationNotPermitted
This AWS account currently does not support creating load balancers.
```

This is an external account restriction rather than a Kubernetes manifest failure.

`launch.py` detects this specific condition, reports:

```text
Public NLB: BLOCKED_BY_AWS
```

and continues to monitoring so the rest of the environment can still be validated.

Once AWS removes the account restriction, the same Service and launch workflow are intended to continue through NLB hostname and external HTTP validation without changing the architecture.

While the NLB is unavailable, Pac-Man can still be reached locally for validation:

```bash
kubectl port-forward -n pacman deployment/pacman 8000:8080
```

Then open:

```text
http://localhost:8000
```

## CI/CD

Workflow:

```text
.github/workflows/ci-cd.yml
```

A push to `main` runs the CI/CD pipeline.

Pipeline flow:

```text
Checkout
   |
npm ci --omit=dev
   |
npm audit
   |
Docker build
   |
non-root verification
   |
Trivy image scan
   |
save exact scanned image
   |
AWS authentication with OIDC
   |
ECR push with Git SHA tag
   |
EKS Deployment image update
   |
rollout verification
```

GitHub Actions uses AWS OIDC rather than long-lived AWS access keys.

The CI/CD IAM/EKS access is limited to the required AWS actions and the `pacman` Kubernetes namespace.

The automatic `main` deployment path has been runtime-tested successfully.

Note: a push to `main` while the EKS runtime is intentionally destroyed will still run the workflow, but the deploy stage cannot update a cluster that does not exist. For normal deployment use, create the runtime first with `launch.py --apply`.

## Security

Implemented controls include:

- MFA on the AWS identities used for the lab
- GitHub OIDC instead of static AWS credentials
- repository/branch-scoped OIDC trust
- namespace-scoped Kubernetes access for CI/CD
- immutable ECR image tags
- non-root Docker container
- explicit non-root Kubernetes UID/GID
- privilege escalation disabled
- Linux capabilities dropped
- CPU and memory limits
- encrypted EBS storage
- Trivy image scanning
- npm dependency auditing
- GitHub Actions pinned to specific commit SHAs

### Legacy dependency findings

The supplied Pac-Man application and required MongoDB version are legacy components.

Current production dependency audit baseline:

```text
8 vulnerabilities
1 low
1 high
6 critical
```

The findings are reported but not force-fixed because `npm audit fix --force` proposes breaking dependency upgrades that can break the supplied application.

The CI workflow therefore records the security findings while allowing the known legacy baseline to continue through the lab pipeline.

## Monitoring

Monitoring uses:

```text
kube-prometheus-stack 87.21.0
```

Enabled components:

- Prometheus
- Grafana
- kube-state-metrics
- node-exporter

Monitoring is intentionally temporary and internal:

- no Prometheus PVC
- no Grafana PVC
- no monitoring LoadBalancer
- no monitoring Ingress
- Alertmanager disabled
- Prometheus retention `2h`

Grafana memory is limited to `512Mi`. The lower `256Mi` limit was runtime-tested and caused an OOM restart during Grafana plugin initialization, so the final configuration uses the verified `512Mi` limit.

To access Grafana:

```bash
kubectl port-forward \
  -n monitoring \
  svc/pacman-monitoring-grafana \
  3000:80
```

Open:

```text
http://localhost:3000
```

Username:

```text
admin
```

Retrieve the generated admin password locally:

```bash
kubectl get secret pacman-monitoring-grafana \
  -n monitoring \
  -o jsonpath='{.data.admin-password}' \
  | base64 --decode; echo
```

Kubernetes Pod metrics were runtime-tested successfully in Grafana using the `pacman` namespace.

## Teardown

The teardown entry point is:

```text
scripts/terminate.py
```

### Preview cleanup

```bash
python3 scripts/terminate.py
```

This displays the Terraform destroy preview and current project runtime inventory without deleting resources.

### Destroy the runtime

```bash
python3 scripts/terminate.py --destroy
```

The script requires confirmation before deletion.

For non-interactive execution:

```bash
python3 scripts/terminate.py --destroy --yes
```

The cleanup sequence removes Kubernetes-managed resources before Terraform destroys the EKS foundation:

```text
Monitoring Helm release / namespace
    |
LoadBalancer Services / Ingresses
    |
remaining NLB / Target Groups
    |
Pac-Man and MongoDB workloads
    |
PVC / persistent EBS
    |
pacman namespace / StorageClass
    |
Terraform destroy
    |
Auto Mode EC2/EBS wait
    |
final orphan verification
```

Final verification requires zero active project runtime resources for:

```text
EKS clusters
Auto Mode EC2 instances
EBS volumes
Load Balancers
Target Groups
Project VPCs
Terraform runtime state
```

The teardown workflow has already been runtime-tested successfully. After the latest full destroy, independent AWS CLI checks also confirmed zero EKS clusters, active Auto Mode EC2 instances, EBS volumes, load balancers, target groups and Pac-Man VPCs.

The remote Terraform state S3 bucket is retained intentionally.

Some historical EKS Auto Mode metadata may remain visible in AWS resource discovery even after the active compute/storage/network resources are gone. The teardown safety decision is based on active EC2, EBS, EKS, ELB, Target Group, VPC and Terraform runtime state rather than metadata-only records.

## Cost Control

The environment is designed to be temporary.

Cost-conscious decisions include:

- two Availability Zones only
- no NAT Gateway
- one Pac-Man replica
- one MongoDB replica
- `1Gi` application PVC
- temporary monitoring storage
- no public Grafana endpoint
- full runtime teardown after testing

Always run the teardown when the environment is no longer required:

```bash
python3 scripts/terminate.py --destroy
```

## Current Validation Status

Validated successfully:

```text
Terraform create/destroy                  OK
EKS Auto Mode                             OK
Docker/ECR immutable image workflow       OK
Pac-Man -> MongoDB connectivity            OK
Internal HTTP 200                         OK
MongoDB persistent EBS                    OK
Persistence after Mongo Pod recreation    OK
GitHub Actions OIDC CI/CD                 OK
Automatic deployment from main            OK
Prometheus/Grafana                         OK
Grafana Kubernetes metrics                OK
Runtime non-root UID 1000                 OK
Final teardown/orphan verification        OK
Public NLB                                BLOCKED BY AWS ACCOUNT
```

The remaining external acceptance item is public NLB creation and external HTTP access after AWS removes the account-level load balancer restriction.
