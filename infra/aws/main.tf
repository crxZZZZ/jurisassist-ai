terraform {
  required_version = ">= 1.7, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { Project = "JurisAssist", ManagedBy = "Terraform" } }
}

variable "region" {
  type    = string
  default = "us-east-1"
}
variable "ami_id" {
  type        = string
  description = "AMI Ubuntu 22.04/24.04 x86_64 com driver NVIDIA, Docker e plugin Compose previamente preparados."
  validation {
    condition     = can(regex("^ami-[a-f0-9]{8,17}$", var.ami_id))
    error_message = "Informe uma AMI válida e revisada para a região escolhida."
  }
}
variable "instance_type" {
  type    = string
  default = "g4dn.xlarge"
}
variable "backup_retention_days" {
  type    = number
  default = 30
}

data "aws_availability_zones" "available" { state = "available" }

resource "aws_vpc" "app" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
}
resource "aws_subnet" "app" {
  vpc_id                  = aws_vpc.app.id
  cidr_block              = "10.42.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = false
}
resource "aws_internet_gateway" "app" { vpc_id = aws_vpc.app.id }
resource "aws_route_table" "app" {
  vpc_id = aws_vpc.app.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.app.id
  }
}
resource "aws_route_table_association" "app" {
  subnet_id      = aws_subnet.app.id
  route_table_id = aws_route_table.app.id
}

resource "aws_security_group" "app" {
  name_prefix = "jurisassist-"
  description = "Sem entrada publica; administracao e acesso via SSM"
  vpc_id      = aws_vpc.app.id
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_s3_bucket" "backups" { bucket_prefix = "jurisassist-backups-" }
resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    id     = "retention"
    status = "Enabled"
    filter { prefix = "database/" }
    expiration { days = var.backup_retention_days }
    noncurrent_version_expiration { noncurrent_days = var.backup_retention_days }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}
data "aws_iam_policy_document" "tls_only" {
  statement {
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.backups.arn, "${aws_s3_bucket.backups.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}
resource "aws_s3_bucket_policy" "tls_only" {
  bucket = aws_s3_bucket.backups.id
  policy = data.aws_iam_policy_document.tls_only.json
}
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "app" {
  name_prefix        = "jurisassist-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
data "aws_iam_policy_document" "backups" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.backups.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["database/*"]
    }
  }
  statement {
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.backups.arn}/database/*"]
  }
}
resource "aws_iam_role_policy" "backups" {
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.backups.json
}
resource "aws_iam_instance_profile" "app" { role = aws_iam_role.app.name }

resource "aws_instance" "app" {
  ami                         = var.ami_id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.app.id
  vpc_security_group_ids      = [aws_security_group.app.id]
  iam_instance_profile        = aws_iam_instance_profile.app.name
  associate_public_ip_address = true # Outbound HTTPS for SSM; no ingress security-group rules.
  metadata_options { http_tokens = "required" }
  root_block_device {
    volume_size           = 60
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = false
  }
  tags = { Name = "jurisassist-reference-single-node" }
}

output "instance_id" { value = aws_instance.app.id }
output "backup_bucket" { value = aws_s3_bucket.backups.id }
output "access" { value = "Use SSM Session Manager para encaminhar a porta local 8080; nenhuma porta de entrada publica e aberta." }
