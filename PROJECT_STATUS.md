# Pac-Man Project Status

## Current mode

COST-SAFE MODE.

Do not create paid AWS runtime resources until explicitly approved.

Do not run:

- terraform apply
- scripts/launch.py in apply mode
- Kubernetes workloads against AWS
- EKS worker nodes
- EBS workload volumes
- Network Load Balancers

## Current checkpoint

The previous AWS environment was fully destroyed successfully.

Verified after teardown:

- Terraform destroy: 23 resources destroyed
- EKS cluster: 0
- EC2 / EKS Auto Mode instances: 0
- EBS volumes: 0
- Load balancers: 0
- Pac-Man VPC: 0
- Root Terraform state: empty

The Terraform remote-state S3 bucket is intentionally retained.

## Completed and verified

### Application / Docker

- Pac-Man container uses Node.js 22
- Container runs as non-root user
- Application listens on port 8080
- Local Docker application and MongoDB connectivity verified
- Application image previously pushed successfully to ECR

### Terraform / AWS

- Remote Terraform state in S3
- VPC with two public subnets across two AZs
- ECR repository
- GitHub Actions OIDC provider and IAM role
- EKS Auto Mode cluster
- Kubernetes 1.34
- Standard EKS support policy
- Terraform teardown verified successfully

### Kubernetes

- Namespace: pacman
- Auto Mode gp3 StorageClass
- MongoDB StatefulSet
- MongoDB headless Service
- 1 GiB encrypted gp3 persistent volume
- Pac-Man ConfigMap
- Pac-Man Deployment
- Non-root Kubernetes securityContext
- Pac-Man successfully connected to MongoDB
- HTTP 200 verified through kubectl port-forward

### Teardown safety

scripts/terminate.py has been tested against real infrastructure.

It correctly distinguishes:

- persistent workload EBS
- Auto Mode node EBS

It successfully removed the complete AWS runtime environment and verified
that no EKS cluster, EBS volumes, load balancers, EC2 Auto Mode instances,
or project VPC remained.

## Work allowed while in COST-SAFE MODE

1. Build and validate scripts/launch.py
2. Terraform fmt / validate / plan only
3. Static review of Kubernetes manifests
4. Prepare GitHub Actions CI/CD configuration without executing deployment
5. Prepare documentation and final project structure
6. Security / DevSecOps static configuration work

## Deferred until AWS runtime is approved

1. Terraform apply
2. Recreate EKS infrastructure
3. Build and push a new immutable Pac-Man image to ECR
4. Apply Namespace and StorageClass
5. Deploy MongoDB and verify PVC/EBS
6. Deploy Pac-Man and verify database connectivity
7. Create the public NLB
8. Test the application externally
9. Execute GitHub Actions deployment
10. Install Prometheus and Grafana
11. Capture final AWS / Kubernetes evidence

## Next runtime checkpoint

When AWS runtime is approved again:

Terraform infrastructure
→ kubeconfig
→ ECR image
→ Kubernetes base resources
→ MongoDB
→ Pac-Man
→ internal validation
→ NLB
→ external validation

Do not skip intermediate validation steps.
