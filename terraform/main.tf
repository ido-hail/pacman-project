module "network" {
  source = "./modules/network"

  name_prefix = "${var.project_name}-${var.environment}"
  vpc_cidr    = "10.0.0.0/16"

  public_subnets = {
    "us-east-1a" = "10.0.1.0/24"
    "us-east-1b" = "10.0.2.0/24"
  }
}

module "ecr" {
  source = "./modules/ecr"

  repository_name = "${var.project_name}-${var.environment}-app"
}

module "github_oidc" {
  source = "./modules/github_oidc"

  role_name          = "${var.project_name}-${var.environment}-github-actions"
  github_repository  = "ido-hail/pacman-project"
  github_branch      = "main"
  ecr_repository_arn = module.ecr.repository_arn
}

module "eks" {
  source = "./modules/eks"

  cluster_name       = "${var.project_name}-${var.environment}"
  kubernetes_version = var.kubernetes_version

  subnet_ids = values(module.network.public_subnet_ids)

  public_access_cidr = var.eks_public_access_cidr

  cluster_role_name = "${var.project_name}-${var.environment}-eks-cluster-role"
  node_role_name    = "${var.project_name}-${var.environment}-eks-node-role"
}
