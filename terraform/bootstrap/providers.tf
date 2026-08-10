provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "pacman"
      ManagedBy = "Terraform"
      Purpose   = "TerraformState"
    }
  }
}
