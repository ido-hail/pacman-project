output "vpc_id" {
  description = "Pac-Man VPC ID"
  value       = module.network.vpc_id
}

output "public_subnet_ids" {
  description = "Pac-Man public subnet IDs"
  value       = module.network.public_subnet_ids
}
