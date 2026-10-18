terraform {
  required_version = ">= 1.7.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Create this bucket first with ./bootstrap. The backend is intentionally
  # explicit so state never falls back to a developer laptop.
  backend "s3" {
    bucket       = "supplyforce-410244642625-tfstate"
    key          = "supplyforge/staging/terraform.tfstate"
    region       = "ap-southeast-1"
    profile      = "supplyforge-dev"
    encrypt      = true
    use_lockfile = true
  }
}
