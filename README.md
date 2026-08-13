# Pac-Man on AWS EKS Auto Mode

DevSecOps final project deploying a containerized Pac-Man application with MongoDB on Amazon EKS Auto Mode.

The project demonstrates Infrastructure as Code, Kubernetes, CI/CD, persistent storage, monitoring, security scanning, and safe environment teardown.

## Project Goals

The final environment demonstrates:

- Terraform-based AWS provisioning
- Amazon EKS Auto Mode
- Docker containerization
- Amazon ECR
- MongoDB StatefulSet with persistent storage
- AWS Network Load Balancer
- GitHub Actions CI/CD
- GitHub OIDC authentication to AWS
- Trivy and npm security scanning
- Prometheus and Grafana monitoring
- automated and verified teardown

## Architecture

The environment is deployed in `us-east-1` and includes:

- one VPC
- two public subnets across two Availability Zones
- Amazon EKS Auto Mode
- Amazon ECR
- AWS Network Load Balancer
- Pac-Man Deployment
- MongoDB StatefulSet
- encrypted gp3 persistent storage
- GitHub Actions using AWS OIDC
- Prometheus and Grafana using `kube-prometheus-stack`

Architecture source:

`docs/architecture.drawio`

The project intentionally uses public subnets without a NAT Gateway.

This is a cost-conscious lab design. A production environment would normally use stronger network isolation, such as private worker capacity and more restrictive control-plane access.

## Repository Structure

```text
.
├── .github/
│   └── workflows/
│       └── ci-cd.yml
├── docs/
│   └── COMPLETION_PLAN.md
├── k8s/
│   ├── namespace.yaml
│   ├── storage-class.yaml
│   ├── mongo-service.yaml
│   ├── mongo-statefulset.yaml
│   ├── app-configmap.yaml
│   ├── app-deployment.yaml
│   └── app-service.yaml
├── monitoring/
│   └── kube-prometheus-values.yaml
├── scripts/
│   ├── launch.py
│   └── terminate.py
├── terraform/
│   ├── bootstrap/
│   ├── modules/
│   │   ├── network/
│   │   ├── ecr/
│   │   ├── eks/
│   │   └── github_oidc/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── versions.tf
├── Dockerfile
├── package.json
├── package-lock.json
└── README.md
```

## Application Container

The application image is based on:

`node:22-bookworm-slim`

The Docker image:

- installs production dependencies using `npm ci --omit=dev`
- uses the repository package lock file
- runs as the built-in non-root `node` user
- exposes port `8080`
- copies the local source code into the image
- does not clone source code during the image build
- is built for `linux/amd64`

Build locally:

```bash
docker build   --platform linux/amd64   -t pacman:local   .
```

The project uses `linux/amd64` consistently because the required legacy MongoDB image and the tested EKS Auto Mode environment use amd64.

## Terraform

Terraform configuration is stored under:

`terraform/`

Terraform manages:

- VPC networking
- two public subnets
- Internet Gateway and routing
- Amazon ECR repository
- Amazon EKS Auto Mode cluster
- EKS IAM roles
- GitHub Actions OIDC provider and IAM role
- EKS access entry for GitHub Actions
- namespace-scoped Kubernetes access for CI/CD

Network configuration:

```text
VPC: 10.0.0.0/16

us-east-1a:
10.0.1.0/24

us-east-1b:
10.0.2.0/24
```

The Terraform state is stored remotely in an encrypted and versioned Amazon S3 bucket.

The bootstrap state and main environment state are kept separately.

Safe Terraform validation:

```bash
terraform -chdir=terraform init
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
terraform -chdir=terraform plan
```

The current cost-safe preview is expected to show:

```text
Plan: 25 to add, 0 to change, 0 to destroy.
```

## Amazon EKS Auto Mode

The cluster is named:

`pacman-dev`

Configuration:

- Kubernetes `1.34`
- EKS Auto Mode
- Standard EKS support policy
- Auto Mode compute
- Auto Mode block storage
- Auto Mode load balancing
- public and private Kubernetes API endpoints enabled
- public API access protected by IAM/EKS authentication

The public API endpoint is a deliberate lab CI/CD trade-off because GitHub-hosted runners do not use a fixed outbound IP address.

## Kubernetes

Kubernetes manifests are stored under:

`k8s/`

The application uses the namespace:

`pacman`

### MongoDB

MongoDB runs as a single-replica StatefulSet using:

`mongo:3.4.24`

It uses:

- a headless Kubernetes Service named `mongo`
- port `27017`
- a `1Gi` PersistentVolumeClaim
- EKS Auto Mode EBS CSI provisioning
- encrypted gp3 storage
- `WaitForFirstConsumer`
- `ReadWriteOnce`

The storage layer is used to demonstrate that application data survives MongoDB pod recreation.

### Pac-Man

Pac-Man runs as a Kubernetes Deployment.

The container:

- listens on port `8080`
- runs as UID/GID `1000`
- cannot escalate privileges
- drops Linux capabilities
- has CPU and memory requests and limits
- uses an HTTP readiness probe

MongoDB configuration is provided using a ConfigMap.

Important environment variables include:

```text
MONGO_SERVICE_HOST=mongo
MONGO_DATABASE=pacman
MY_MONGO_PORT=27017
MONGO_USE_SSL=false
MONGO_VALIDATE_SSL=false
MONGO_URL=mongodb://mongo:27017/pacman
```

The application has already been runtime-tested successfully against MongoDB and returned HTTP 200 through `kubectl port-forward`.

## Network Load Balancer

The Pac-Man Service uses:

```text
type: LoadBalancer
loadBalancerClass: eks.amazonaws.com/nlb
```

EKS Auto Mode provisions an internet-facing AWS Network Load Balancer.

Traffic flow:

```text
Internet
   |
AWS Network Load Balancer :80
   |
Pac-Man Service
   |
Pac-Man Pod :8080
```

The final runtime acceptance test will verify:

- NLB creation
- NLB DNS name
- healthy target registration
- external HTTP 200 response

## CI/CD

GitHub Actions workflow:

`.github/workflows/ci-cd.yml`

The pipeline performs:

```text
Checkout
  ↓
npm ci
  ↓
npm audit
  ↓
Docker build
  ↓
non-root verification
  ↓
Trivy image scan
  ↓
save exact scanned image
  ↓
AWS authentication with OIDC
  ↓
ECR push
  ↓
EKS image update
  ↓
rollout verification
```

Application images use the Git commit SHA as an immutable image tag.

The exact Docker image that is scanned is saved and promoted to the deployment stage. The deployment job does not rebuild a different image.

AWS authentication uses GitHub OIDC.

No long-lived AWS access keys are stored in GitHub.

GitHub Actions EKS access is scoped to the `pacman` namespace.

During cost-safe development, the workflow is manually triggered.

The final acceptance test will enable automatic deployment on push to `main`.

## Security

Implemented DevSecOps controls include:

- MFA on the AWS administrative identities used for the lab
- GitHub OIDC instead of static AWS credentials
- repository/branch-scoped OIDC trust
- namespace-scoped CI/CD Kubernetes access
- immutable ECR image tags
- non-root Docker container
- explicit non-root Kubernetes UID/GID
- privilege escalation disabled
- Linux capabilities dropped
- CPU and memory limits
- encrypted EBS storage
- Trivy container image scanning
- npm dependency auditing
- GitHub Actions pinned to specific commit SHAs

### Legacy Dependency Risk

The supplied Pac-Man application and the required MongoDB `3.4.24` image contain legacy dependencies.

Security scans are expected to report vulnerabilities.

For this course project, findings are documented rather than automatically force-fixed because aggressive dependency upgrades could break the supplied legacy application.

The CI pipeline therefore reports the known vulnerability baseline instead of permanently failing every build on existing HIGH or CRITICAL findings.

## Monitoring

Monitoring configuration:

`monitoring/kube-prometheus-values.yaml`

Pinned chart:

`kube-prometheus-stack 87.21.0`

Enabled components:

- Prometheus
- Grafana
- kube-state-metrics
- node-exporter

The monitoring configuration intentionally uses:

- no persistent Prometheus storage
- no Grafana PVC
- no monitoring LoadBalancer
- no monitoring Ingress
- no Alertmanager
- short Prometheus retention
- lightweight resource requests and limits

Grafana is accessed using `kubectl port-forward`.

The Helm configuration has already been rendered successfully locally for Kubernetes `1.34.1`.

The final runtime acceptance test will verify that the monitoring workloads are running and that Kubernetes metrics are visible in Grafana.

## Safe Launch Workflow

Script:

`scripts/launch.py`

While the project is in COST-SAFE mode, the script performs validation and preview only.

It checks:

- required local tools
- required project files
- AWS account and region
- Terraform state bucket
- absence of EKS runtime
- absence of Auto Mode EC2 instances
- absence of project EBS volumes
- Terraform initialization
- Terraform formatting
- Terraform validation
- empty root Terraform state
- Terraform creation plan

The script documents the final runtime sequence but does not currently execute:

- `terraform apply`
- ECR pushes
- `kubectl apply`
- Helm installation
- NLB creation

The frozen final sequence is documented in:

`docs/COMPLETION_PLAN.md`

## Teardown

Script:

`scripts/terminate.py`

The teardown workflow removes Kubernetes resources before destroying the EKS infrastructure.

This is important for resources such as:

- Network Load Balancers
- Target Groups
- persistent EBS volumes

The script has already completed one successful real teardown of the previously tested EKS, Pac-Man, MongoDB and EBS environment.

A historical EKS Auto Mode EC2 Fleet object may remain visible after teardown. The original EC2 instance behind that instant Fleet no longer exists and the Fleet is not treated as an active billable runtime resource.

The teardown script will receive one final validation after NLB and monitoring are included in the final environment.

Preview teardown:

```bash
python3 scripts/terminate.py
```

Actual teardown:

```bash
python3 scripts/terminate.py --destroy
```

## Cost Control

The project is designed as a temporary lab environment.

Cost-control decisions include:

- two Availability Zones only
- no NAT Gateway
- minimal application replicas
- small persistent volume allocation
- lightweight monitoring
- no public Grafana endpoint
- monitoring installed only for the final validation phase
- complete runtime teardown after testing

The Terraform state S3 bucket is intentionally retained after runtime teardown because its storage cost is negligible and it preserves infrastructure state history.

## Completion Status

The frozen completion plan is stored in:

`docs/COMPLETION_PLAN.md`

Remaining runtime acceptance gates:

1. recreate the AWS environment
2. verify EKS and kubeconfig
3. build and push a new immutable application image
4. deploy MongoDB and verify PVC/EBS
5. deploy Pac-Man and verify database connectivity
6. verify internal HTTP 200
7. create and verify the public NLB
8. verify MongoDB persistence after pod recreation
9. enable and verify automatic GitHub Actions deployment from `main`
10. install and verify Prometheus and Grafana
11. capture security and infrastructure evidence
12. finalize screenshots and documentation
13. run the final teardown and orphan verification

## Final Acceptance Criteria

The project is finished when:

- Terraform recreates the AWS environment successfully
- Pac-Man is reachable through the AWS Network Load Balancer
- MongoDB persistence survives pod recreation
- GitHub Actions automatically deploys from `main` using OIDC
- Prometheus and Grafana monitoring are demonstrated
- security scan findings are documented
- README and architecture diagram are complete
- required screenshots are captured
- final teardown leaves no active billable runtime resources
