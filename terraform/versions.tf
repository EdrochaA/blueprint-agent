terraform {
  required_version = ">= 1.14.4"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    bucket = "s3-terraform-tfstate-ai-recruitment"
    key    = "blueprint-agent/terraform.tfstate"
    region = "eu-west-1"
  }
}

provider "aws" {
  region = local.config.runtime_deployment.region
}