data "aws_iam_policy_document" "cluster_assume_role" {
  statement {
    effect = "Allow"

    actions = [
      "sts:AssumeRole",
      "sts:TagSession"
    ]

    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = var.cluster_role_name
  assume_role_policy = data.aws_iam_policy_document.cluster_assume_role.json
}

locals {
  cluster_policy_arns = {
    cluster      = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
    compute      = "arn:aws:iam::aws:policy/AmazonEKSComputePolicy"
    storage      = "arn:aws:iam::aws:policy/AmazonEKSBlockStoragePolicy"
    loadbalancer = "arn:aws:iam::aws:policy/AmazonEKSLoadBalancingPolicy"
    networking   = "arn:aws:iam::aws:policy/AmazonEKSNetworkingPolicy"
  }
}

resource "aws_iam_role_policy_attachment" "cluster" {
  for_each = local.cluster_policy_arns

  role       = aws_iam_role.cluster.name
  policy_arn = each.value
}

data "aws_iam_policy_document" "node_assume_role" {
  statement {
    effect = "Allow"

    actions = [
      "sts:AssumeRole"
    ]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = var.node_role_name
  assume_role_policy = data.aws_iam_policy_document.node_assume_role.json
}

locals {
  node_policy_arns = {
    worker = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodeMinimalPolicy"
    ecr    = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPullOnly"
  }
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = local.node_policy_arns

  role       = aws_iam_role.node.name
  policy_arn = each.value
}

resource "aws_eks_cluster" "this" {
  name     = var.cluster_name
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version

  deletion_protection           = false
  bootstrap_self_managed_addons = false

  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = true
  }

  compute_config {
    enabled       = true
    node_pools    = ["general-purpose"]
    node_role_arn = aws_iam_role.node.arn
  }

  kubernetes_network_config {
    elastic_load_balancing {
      enabled = true
    }
  }

  storage_config {
    block_storage {
      enabled = true
    }
  }

  control_plane_scaling_config {
    tier = "standard"
  }

  upgrade_policy {
    support_type = "STANDARD"
  }

  vpc_config {
    subnet_ids = var.subnet_ids

    endpoint_private_access = true
    endpoint_public_access  = true

    public_access_cidrs = [
      var.public_access_cidr
    ]
  }

  depends_on = [
    aws_iam_role_policy_attachment.cluster,
    aws_iam_role_policy_attachment.node
  ]
}
