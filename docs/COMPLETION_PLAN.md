# Pac-Man Project - Completion Freeze

## Purpose

This document defines the remaining work required to finish the project.

The project is now in completion mode.

Do not add optional infrastructure, refactors, security features, or
architecture changes unless:

1. they are explicitly required by the project,
2. a real acceptance test fails without them, or
3. they are required for safe teardown or final evidence.

## Current mode

COST-SAFE MODE.

No paid AWS runtime resources should be created until explicitly approved.

The retained Terraform state S3 bucket is intentional.

## Completed

### Application and Docker

- Node.js 22 container
- production npm installation
- non-root container
- linux/amd64 image
- local Pac-Man + MongoDB connectivity
- HTTP 200 validation
- Docker image previously pushed successfully to ECR

### Terraform and AWS

- remote Terraform state in S3
- VPC module
- two public subnets across two Availability Zones
- no NAT Gateway
- ECR module
- EKS Auto Mode module
- Kubernetes 1.34
- Standard EKS support policy
- GitHub OIDC IAM role
- immutable GitHub repository OIDC subject
- namespace-scoped EKS access for GitHub Actions
- Terraform fmt and validate
- previous real Terraform apply
- previous successful full Terraform destroy

Current creation preview:

Plan: 25 to add, 0 to change, 0 to destroy.

### Kubernetes

Previously runtime verified:

- namespace pacman
- gp3 Auto Mode StorageClass
- MongoDB StatefulSet
- MongoDB headless Service
- persistent EBS storage
- Pac-Man ConfigMap
- Pac-Man Deployment
- non-root security context
- resource requests and limits
- readiness probes
- successful MongoDB connection
- internal HTTP 200 response

Current manifests also passed local YAML syntax validation.

### CI/CD

GitHub Actions workflow exists with:

- immutable Git SHA image tags
- Docker build
- npm audit
- Trivy scan
- non-root verification
- OIDC authentication
- ECR push
- EKS deployment
- rollout verification
- pinned GitHub Actions versions

The current workflow is intentionally manual until the final runtime test.

### Monitoring

Pinned:

kube-prometheus-stack 87.21.0

Configuration:

- Prometheus enabled
- Grafana enabled
- kube-state-metrics enabled
- node-exporter enabled
- Alertmanager disabled
- no monitoring PVC
- no monitoring LoadBalancer
- no monitoring Ingress
- Grafana accessed through port-forward
- lightweight resource requests and limits

Helm template rendering succeeded locally for Kubernetes 1.34.1.

### Launch safety

scripts/launch.py currently performs only safe preview checks.

It validates:

- local tools
- required project files
- AWS identity and account
- state bucket
- absence of EKS / EC2 / EBS runtime
- Terraform init
- Terraform fmt
- Terraform validate
- empty root Terraform state
- Terraform creation plan

It documents the complete final runtime sequence.

Runtime creation remains disabled.

### Teardown

scripts/terminate.py already completed one successful real AWS teardown.

It removed the previously tested:

- Kubernetes workloads
- persistent EBS
- Auto Mode compute
- EKS cluster
- Terraform-managed infrastructure

A historical EKS Auto Mode EC2 Fleet object may remain visible as metadata.

The original EC2 instance behind that instant Fleet no longer exists.
The Fleet object is not treated as an active billable runtime resource.

## Scope freeze

The following are NOT blockers for project completion:

- private worker subnets
- NAT Gateway
- NetworkPolicy
- PodDisruptionBudget
- HPA
- TLS termination
- public Grafana
- persistent Prometheus storage
- Vault
- Secrets Manager
- custom node pools
- liveness probe
- readOnlyRootFilesystem
- dependency modernization
- MongoDB upgrade
- npm audit fix --force
- multi-replica production HA

Do not add them unless a required acceptance test proves they are necessary.

## Remaining acceptance gates

### Gate 1 - Recreate runtime

Terraform apply.

Verify:

- EKS becomes ACTIVE
- kubeconfig works
- new immutable application image is pushed to ECR
- MongoDB becomes Ready
- PVC and EBS are created
- Pac-Man becomes Ready
- Pac-Man connects to MongoDB
- internal HTTP 200

### Gate 2 - Core application acceptance

Create the public Network Load Balancer.

Verify:

- NLB hostname exists
- target is healthy
- Pac-Man returns HTTP 200 externally

Persistence test:

- create application data
- delete the MongoDB pod
- StatefulSet recreates the pod
- stored data remains

### Gate 3 - CI/CD acceptance

Enable automatic deployment on push to main.

Verify one real workflow:

- GitHub Actions succeeds
- OIDC role assumption succeeds
- immutable SHA image reaches ECR
- Pac-Man Deployment receives the new image
- rollout succeeds

No static AWS access keys may be stored in GitHub.

### Gate 4 - Monitoring acceptance

Install kube-prometheus-stack 87.21.0.

Verify:

- Prometheus is running
- Grafana is running
- kube-state-metrics is running
- node-exporter is running
- Grafana is reachable through port-forward
- Kubernetes metrics are visible

Capture evidence.

### Gate 5 - Security evidence

Capture:

- npm audit result
- Trivy result
- container non-root evidence

Document that the application and MongoDB are legacy components and that
known dependency findings are accepted for the course environment rather
than force-fixed in a way that could break the provided application.

### Gate 6 - Final documentation and teardown

Complete:

- README
- architecture.drawio
- architecture image/export
- required screenshots

Update terminate.py once for the final architecture.

Run final teardown.

Success requires:

- EKS clusters: 0
- active Auto Mode EC2 instances: 0
- project EBS volumes: 0
- project load balancers: 0
- project target groups: 0
- project VPC: 0
- root Terraform state: empty

The remote-state S3 bucket may remain intentionally.

## Final runtime order

Terraform
→ EKS
→ kubeconfig
→ ECR image
→ namespace / StorageClass
→ MongoDB
→ PVC / EBS validation
→ Pac-Man
→ internal HTTP validation
→ NLB
→ external HTTP validation
→ Mongo persistence test
→ CI/CD test
→ monitoring
→ security evidence
→ screenshots
→ final documentation
→ teardown
→ orphan verification

## Definition of Done

The project is finished when:

- Terraform recreates the AWS environment successfully
- Pac-Man is reachable through the NLB
- MongoDB persistence survives pod recreation
- GitHub Actions automatically deploys from main using OIDC
- Prometheus and Grafana monitoring is demonstrated
- security scan findings are documented
- README and architecture diagram are complete
- required screenshots are captured
- final teardown leaves no active billable runtime resources

There is no additional development phase after these gates.
