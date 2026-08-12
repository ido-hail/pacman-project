variable "aws_region" {
  description = "AWS region for the project resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used for resource naming and tagging"
  type        = string
  default     = "pacman"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

variable "kubernetes_version" {
  description = "Kubernetes version used by the EKS cluster"
  type        = string
  default     = "1.34"
}

variable "eks_public_access_cidr" {
  description = "Public CIDR allowed to access the EKS Kubernetes API"
  type        = string
  default     = "0.0.0.0/0"
}
