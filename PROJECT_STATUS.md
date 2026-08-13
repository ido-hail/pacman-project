# Pac-Man Project Status

## Current mode

COST-SAFE MODE.

Do not create paid AWS runtime resources until explicitly approved.

Runtime execution is currently disabled.

Do not run:

- terraform apply
- Kubernetes workloads against AWS
- EKS worker nodes
- EBS workload volumes
- Network Load Balancers
- real GitHub Actions deployment to AWS
- Prometheus / Grafana deployment

## Current AWS checkpoint

The previous AWS environment was fully destroyed successfully.

Verified after teardown:

- Terraform destroy completed successfully
- EKS clusters: 0
- EC2 / EKS Auto Mode instances: 0
- EBS volumes: 0
- load balancers: 0
- Pac-Man VPC: 0
- root Terraform state: empty

The Terraform remote-state S3 bucket is intentionally retained.

Current Terraform creation preview:

Plan: 25 to add, 0 to change, 0 to destroy.

No Terraform apply has been executed after the previous teardown.

## Completed and verified

### Application / Docker

- Pac-Man container uses Node.js 22
- production dependencies installed with npm ci
- container runs as non-root user
- application listens on port 8080
- local Docker application and MongoDB connectivity verified
- linux/amd64 image strategy verified
- application image was previously pushed successfully to ECR

### Terraform / AWS

- remote Terraform state stored in S3
- VPC design with two public subnets across two AZs
- ECR repository module
- EKS Auto Mode module
- Kubernetes 1.34
- EKS Standard support policy
- GitHub Actions OIDC provider and IAM role
- immutable GitHub OIDC repository identity
- GitHub IAM permission scoped to the Pac-Man EKS cluster
- EKS Access Entry for GitHub Actions
- AmazonEKSAdminPolicy scoped only to namespace pacman
- Terraform fmt and validate pass
- current Terraform plan: 25 resources to create
- full Terraform teardown previously verified successfully

### Kubernetes

Runtime-proven baseline:

- Namespace: pacman
- Auto Mode gp3 StorageClass
- MongoDB StatefulSet
- MongoDB headless Service
- 1 GiB encrypted gp3 persistent storage
- Pac-Man ConfigMap
- Pac-Man Deployment
- explicit non-root UID/GID
- privilege escalation disabled
- Linux capabilities dropped
- resource requests and limits
- readiness probes
- Pac-Man successfully connected to MongoDB
- HTTP 200 verified previously through kubectl port-forward

Static validation performed while the EKS cluster is offline:

- all 7 YAML files parse successfully
- required apiVersion, kind, and metadata fields are present
- no privileged: true
- no allowPrivilegeEscalation: true
- no hostNetwork: true
- no hostPID: true
- no hostIPC: true
- no :latest image tags

Full Kubernetes API schema validation will be repeated when the EKS cluster
is recreated.

### GitHub Actions CI/CD

Manual workflow created at:

.github/workflows/ci-cd.yml

Current design:

- workflow_dispatch only
- no automatic push trigger
- build job has no AWS OIDC permission
- npm production dependency audit
- linux/amd64 Docker build
- non-root container verification
- Trivy HIGH / CRITICAL image scan
- GitHub Actions pinned to commit SHAs
- immutable application image tag based on Git commit SHA
- exact scanned image is saved and promoted to deployment
- deploy job receives id-token: write only when required
- AWS authentication uses OIDC instead of static AWS keys
- deployment requires explicit deploy=true
- deployment is restricted to main
- CI/CD updates the existing Pac-Man Deployment rather than creating base infrastructure

The workflow has not yet been executed against AWS.

Security scans currently report legacy vulnerabilities without blocking the
pipeline. A final accepted-risk / blocking policy will be defined during the
DevSecOps hardening phase.

### Launch workflow

scripts/launch.py currently operates only in COST-SAFE preview mode.

It verifies:

- required local tools
- required project files
- expected AWS account
- expected AWS region
- Terraform state bucket access
- absence of Pac-Man EKS runtime
- absence of Pac-Man Auto Mode EC2 instances
- absence of Pac-Man EBS volumes
- Terraform initialization
- Terraform formatting
- Terraform validation
- empty root Terraform state
- Terraform creation plan

It also documents the future runtime launch sequence:

1. Terraform infrastructure
2. Kubernetes access
3. application image
4. Kubernetes base
5. MongoDB
6. Pac-Man
7. public NLB
8. final runtime verification

Runtime execution is intentionally not implemented yet.

There is currently no terraform apply, docker push, kubectl apply, or NLB
creation logic inside scripts/launch.py.

### Teardown safety

scripts/terminate.py has already been tested against real AWS infrastructure.

It correctly distinguished:

- persistent workload EBS
- Auto Mode node lifecycle EBS

It successfully removed the previous runtime environment and verified that no
EKS cluster, EBS volume, load balancer, active Auto Mode EC2 instance, or
project VPC remained.

Important:

The teardown was proven before the final NLB and monitoring phases existed.

After NLB and Prometheus / Grafana are introduced, terminate.py must be
reviewed and tested again against the final architecture.

## Work allowed while in COST-SAFE MODE

Safe work that can continue now:

- improve scripts/launch.py without enabling runtime execution
- statically review scripts/terminate.py
- Terraform fmt / validate / plan
- CI/CD configuration review
- Kubernetes manifest static review
- prepare monitoring configuration without installing it
- prepare DevSecOps hardening
- documentation and architecture work

## Deferred until AWS runtime is approved

Runtime work intentionally postponed:

- terraform apply
- recreate VPC / ECR / IAM / EKS
- test new GitHub OIDC configuration against AWS
- build and push a new immutable image to ECR
- apply Namespace and StorageClass
- deploy MongoDB
- verify PVC and EBS
- deploy Pac-Man
- verify MongoDB connectivity
- verify internal HTTP response
- create public NLB
- verify NLB target health
- verify external HTTP response
- execute real GitHub Actions deployment
- install Prometheus and Grafana
- test monitoring
- apply runtime-tested Kubernetes hardening
- capture final screenshots and evidence
- re-test terminate.py against the final architecture

## Next runtime checkpoint

When AWS runtime is explicitly approved again:

Terraform apply
→ wait for EKS ACTIVE
→ update kubeconfig
→ create and push immutable application image
→ Kubernetes namespace and StorageClass
→ MongoDB
→ verify PVC / EBS / readiness
→ Pac-Man
→ verify MongoDB connection
→ internal HTTP validation
→ NLB
→ external HTTP validation
→ CI/CD deployment test
→ monitoring
→ final security validation
→ teardown validation

Do not skip intermediate validation steps.
