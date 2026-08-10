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
