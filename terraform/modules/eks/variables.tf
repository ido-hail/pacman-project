variable "cluster_name" {
  description = "Name of the EKS cluster"
  type        = string
}

variable "kubernetes_version" {
  description = "Kubernetes version for the EKS cluster"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs used by the EKS cluster"
  type        = list(string)
}

variable "public_access_cidr" {
  description = "CIDR allowed to access the public Kubernetes API endpoint"
  type        = string
}

variable "cluster_role_name" {
  description = "Name of the EKS cluster IAM role"
  type        = string
}

variable "node_role_name" {
  description = "Name of the EKS Auto Mode node IAM role"
  type        = string
}
