output "vpc_id" {
  description = "Pac-Man VPC ID"
  value       = module.network.vpc_id
}

output "public_subnet_ids" {
  description = "Pac-Man public subnet IDs"
  value       = module.network.public_subnet_ids
}

output "ecr_repository_url" {
  description = "Pac-Man ECR repository URL"
  value       = module.ecr.repository_url
}

output "github_actions_role_arn" {
  description = "IAM role ARN used by GitHub Actions"
  value       = module.github_oidc.role_arn
}

output "eks_cluster_name" {
  description = "Pac-Man EKS cluster name"
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "Pac-Man EKS Kubernetes API endpoint"
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_role_arn" {
  description = "Pac-Man EKS cluster IAM role ARN"
  value       = module.eks.cluster_role_arn
}

output "eks_node_role_arn" {
  description = "Pac-Man EKS Auto Mode node IAM role ARN"
  value       = module.eks.node_role_arn
}
