# The network already exists. `scripts/adopt-existing.sh` imports it before the
# first plan so Terraform becomes its source of truth without recreating it.
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "sf-dev-vpc"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "sf-dev-igw"
  }
}

resource "aws_subnet" "public" {
  for_each = local.public_subnets

  vpc_id                  = aws_vpc.main.id
  cidr_block              = each.value.cidr
  availability_zone       = each.value.az
  map_public_ip_on_launch = true

  tags = {
    Name = "sf-dev-public-${each.key}"
    Tier = "public"
  }
}

resource "aws_subnet" "private_app" {
  for_each = local.private_app_subnets

  vpc_id                  = aws_vpc.main.id
  cidr_block              = each.value.cidr
  availability_zone       = each.value.az
  map_public_ip_on_launch = false

  tags = {
    Name = "sf-dev-private-app-${each.key}"
    Tier = "app"
  }
}

resource "aws_subnet" "private_data" {
  for_each = local.private_data_subnets

  vpc_id                  = aws_vpc.main.id
  cidr_block              = each.value.cidr
  availability_zone       = each.value.az
  map_public_ip_on_launch = false

  tags = {
    Name = "sf-dev-private-data-${each.key}"
    Tier = "data"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "sf-dev-rtb-public"
  }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  for_each = local.public_subnets

  subnet_id      = aws_subnet.public[each.key].id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  for_each = var.enable_nat_gateways ? local.nat_subnet_ids : {}

  domain = "vpc"

  tags = {
    Name = "${local.name_prefix}-nat-${each.key}"
  }
}

resource "aws_nat_gateway" "this" {
  for_each = var.enable_nat_gateways ? local.nat_subnet_ids : {}

  allocation_id = aws_eip.nat[each.key].id
  subnet_id     = aws_subnet.public[each.key].id

  tags = {
    Name = "${local.name_prefix}-nat-${each.key}"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "private_app" {
  for_each = local.private_app_subnets

  vpc_id = aws_vpc.main.id

  tags = {
    Name = "sf-dev-rtb-private${each.key == "a" ? "1" : "2"}-ap-southeast-1${each.key}"
  }
}

resource "aws_route" "private_app_nat" {
  for_each = var.enable_nat_gateways ? local.private_app_subnets : {}

  route_table_id         = aws_route_table.private_app[each.key].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[each.key].id
}

resource "aws_route_table_association" "private_app" {
  for_each = local.private_app_subnets

  subnet_id      = aws_subnet.private_app[each.key].id
  route_table_id = aws_route_table.private_app[each.key].id
}

resource "aws_route_table" "private_data" {
  for_each = local.private_data_subnets

  vpc_id = aws_vpc.main.id

  tags = {
    Name = "sf-dev-rtb-private${each.key == "a" ? "3" : "4"}-ap-southeast-1${each.key}"
  }
}

resource "aws_route_table_association" "private_data" {
  for_each = local.private_data_subnets

  subnet_id      = aws_subnet.private_data[each.key].id
  route_table_id = aws_route_table.private_data[each.key].id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids = concat(
    values(aws_route_table.private_app)[*].id,
    values(aws_route_table.private_data)[*].id,
  )

  tags = {
    Name = "sf-dev-vpce-s3"
  }
}
