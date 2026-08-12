variable "name_prefix" {
  description = "Prefix used for network resource names"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
}

variable "public_subnets" {
  description = "Public subnet CIDRs mapped by availability zone"
  type        = map(string)
}
