module "network" {
  source = "./modules/network"

  name_prefix = "${var.project_name}-${var.environment}"
  vpc_cidr    = "10.0.0.0/16"

  public_subnets = {
    "us-east-1a" = "10.0.1.0/24"
    "us-east-1b" = "10.0.2.0/24"
  }
}
