# Pac-Man on AWS EKS Auto Mode

DevSecOps final project that deploys a containerized Pac-Man application and MongoDB on **Amazon EKS Auto Mode**.

The application is based on the supplied Pac-Man project. This repository focuses on the DevSecOps layer: Infrastructure as Code, Kubernetes, CI/CD, persistent storage, monitoring, security controls, automated deployment and complete teardown.

## Architecture

![Pac-Man DevSecOps Architecture](docs/architecture.png)

Editable source: [`docs/architecture.drawio`](docs/architecture.drawio)

Main components:

- Terraform-managed VPC with two public subnets across two Availability Zones
- Amazon EKS Auto Mode
- Amazon ECR with immutable image tags
- Pac-Man Deployment with two replicas
- MongoDB StatefulSet with encrypted `gp3` EBS storage
- Kubernetes NetworkPolicy restricting MongoDB access to Pac-Man Pods
- internet-facing AWS Network Load Balancer
- Prometheus and Grafana through `kube-prometheus-stack`
- GitHub Actions CI/CD using AWS OIDC
- encrypted and versioned S3 Terraform remote state

The project uses public subnets and no NAT Gateway to keep the lab architecture simple and cost-conscious.

## Repository Structure

```text
.github/workflows/ci-cd.yml   CI/CD pipeline
docs/                         architecture diagram
k8s/                          Kubernetes manifests
monitoring/                   Prometheus/Grafana values
scripts/launch.py             deployment workflow
scripts/terminate.py          teardown workflow
terraform/bootstrap/          Terraform state bootstrap
terraform/modules/            network, EKS, ECR and GitHub OIDC
Dockerfile                    application image
```

## Prerequisites

Required locally:

- Python 3
- AWS CLI v2
- Terraform
- Docker
- kubectl
- Helm
- Git

Authenticate the AWS CLI to the AWS account where the environment should be created. The active identity must have permissions to create and remove the required AWS resources.

```bash
aws sts get-caller-identity
```

The AWS account ID is detected automatically and is used to derive project-specific values such as the Terraform state bucket name.

No manual Terraform backend creation is required. On a fresh environment, `launch.py` automatically creates the encrypted and versioned S3 state bucket before initializing the main Terraform configuration.

## Deploy

Clone the repository:

```bash
git clone https://github.com/ido-hail/pacman-project.git
cd pacman-project
```

For a safe preview without creating the EKS runtime:

```bash
python3 scripts/launch.py
```

To create the complete environment:

```bash
python3 scripts/launch.py --apply
```

The script requires confirmation before creating billable resources. Non-interactive mode is also available:

```bash
python3 scripts/launch.py --apply --yes
```

Deployment flow:

```text
AWS authentication and preflight checks
              ↓
Terraform state bootstrap
              ↓
Terraform apply
              ↓
EKS Auto Mode + ECR
              ↓
Docker build + non-root verification + ECR push
              ↓
MongoDB StatefulSet + persistent EBS
              ↓
Pac-Man Deployment
              ↓
NLB + runtime validation
              ↓
Prometheus + Grafana
```

The application image is built for `linux/amd64`. The container runs as a non-root user and the deployed image is identified by the Git commit SHA.

## Kubernetes Runtime

Pac-Man uses:

- 2 replicas
- Node.js 22
- non-root UID/GID `1000`
- readiness and liveness probes
- CPU and memory requests/limits
- RollingUpdate with `maxUnavailable: 0`
- privilege escalation disabled
- Linux capabilities dropped

MongoDB uses:

- `mongo:3.4.24`
- StatefulSet + Service `mongo:27017`
- non-root UID/GID `999`
- encrypted `1Gi` `gp3` persistent volume
- EKS Auto Mode EBS CSI provisioning
- NetworkPolicy allowing TCP `27017` only from Pods labeled `app: pacman`

## Network Load Balancer

The Pac-Man Service uses Kubernetes `type: LoadBalancer` with the EKS Auto Mode NLB class and IP targets.

Expected traffic flow:

```text
Internet
   ↓
AWS NLB :80
   ↓
Pac-Man Service
   ↓
Pac-Man Pods :8080
```

EKS Auto Mode provisions and manages the NLB from the Kubernetes Service definition. `launch.py` waits for the public endpoint and performs HTTP validation during deployment.

For local access while the cluster is running:

```bash
kubectl port-forward -n pacman deployment/pacman 8000:8080
```

Then open `http://localhost:8000`.

## CI/CD

Workflow: `.github/workflows/ci-cd.yml`

Pull requests to `main` run validation without deploying. Pushes to `main` run the validation pipeline and deploy a new immutable image while the EKS runtime exists.

Pipeline:

```text
Terraform fmt / validate
        +
npm ci → npm audit → Docker build → non-root check → Trivy
        ↓
AWS authentication with GitHub OIDC
        ↓
immutable Git-SHA image push to ECR
        ↓
Kubernetes deployment
        ↓
rollout verification
```

GitHub Actions uses OIDC instead of long-lived AWS access keys. Kubernetes access for the CI/CD role is limited to the `pacman` namespace.

To enable AWS deployment from GitHub Actions, configure the repository variable:

```text
AWS_ACCOUNT_ID=<target AWS account ID>
```

The OIDC trust is intentionally scoped to a specific GitHub repository and the `main` branch. If this project is forked and the fork should use its own CI/CD deployment, update the GitHub owner/repository identity values passed to the `github_oidc` module in `terraform/main.tf` to match that fork.

## Security Controls

The project includes:

- GitHub OIDC authentication to AWS
- repository/branch-scoped OIDC trust
- namespace-scoped EKS access for CI/CD
- immutable ECR image tags
- digest-pinned Node base image
- non-root application and database containers
- disabled privilege escalation and dropped Linux capabilities
- Kubernetes NetworkPolicy for MongoDB
- encrypted EBS storage
- CPU and memory limits
- Trivy image scanning
- npm dependency audit
- pinned GitHub Actions
- Terraform formatting and validation in CI

The supplied Pac-Man application contains legacy dependencies. `npm audit` is informational, while the Docker image is protected by the blocking Trivy gate for fixable `HIGH` and `CRITICAL` findings.

## Monitoring

Monitoring uses `kube-prometheus-stack 87.21.0` with:

- Prometheus
- Grafana
- kube-state-metrics
- node-exporter

Monitoring is internal only; no public Grafana LoadBalancer or Ingress is created.

Access Grafana:

```bash
kubectl port-forward -n monitoring svc/pacman-monitoring-grafana 3000:80
```

Open `http://localhost:3000` with username `admin`.

Retrieve the generated password:

```bash
kubectl get secret pacman-monitoring-grafana \
  -n monitoring \
  -o jsonpath='{.data.admin-password}' \
  | base64 --decode; echo
```

## Teardown

Preview the resources that will be removed:

```bash
python3 scripts/terminate.py
```

Destroy the complete project:

```bash
python3 scripts/terminate.py --destroy
```

Non-interactive mode:

```bash
python3 scripts/terminate.py --destroy --yes
```

The teardown removes Kubernetes workloads and monitoring first, destroys the Terraform-managed AWS infrastructure, waits for EKS Auto Mode compute and storage cleanup, verifies that no active project runtime resources remain, and finally deletes all Terraform state versions and the S3 state bucket itself.

Final verification checks for zero remaining project resources across EKS, EC2, EBS, Load Balancers, Target Groups, VPCs and Terraform runtime state.

## Validation

The final project was validated for Terraform create/destroy, EKS Auto Mode, Docker/ECR deployment, Pac-Man to MongoDB connectivity, persistent EBS storage, non-root execution, NetworkPolicy enforcement, GitHub Actions OIDC CI/CD, Trivy scanning, Prometheus/Grafana monitoring and complete teardown.
