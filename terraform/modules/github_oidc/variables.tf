variable "role_name" {
  description = "Name of the IAM role assumed by GitHub Actions"
  type        = string
}

variable "github_owner" {
  description = "GitHub repository owner"
  type        = string
}

variable "github_owner_id" {
  description = "Immutable GitHub repository owner ID"
  type        = string
}

variable "github_repository_name" {
  description = "GitHub repository name"
  type        = string
}

variable "github_repository_id" {
  description = "Immutable GitHub repository ID"
  type        = string
}

variable "github_branch" {
  description = "GitHub branch allowed to assume the IAM role"
  type        = string
}

variable "ecr_repository_arn" {
  description = "ARN of the ECR repository GitHub Actions can push to"
  type        = string
}

variable "eks_cluster_arn" {
  description = "ARN of the EKS cluster GitHub Actions can describe"
  type        = string
}
