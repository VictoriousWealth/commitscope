terraform {
  required_version = ">= 1.6.0"

  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.5"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.92"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name_prefix = "${var.project}-${var.environment}"
  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_bucket" "data_lake" {
  bucket = var.bucket_name
  tags   = local.common_tags
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_object" "raw_prefix" {
  bucket  = aws_s3_bucket.data_lake.id
  key     = "raw/"
  content = ""
}

resource "aws_s3_object" "processed_prefix" {
  bucket  = aws_s3_bucket.data_lake.id
  key     = "processed/"
  content = ""
}

resource "aws_s3_object" "curated_prefix" {
  bucket  = aws_s3_bucket.data_lake.id
  key     = "curated/"
  content = ""
}

resource "aws_glue_catalog_database" "commitscope" {
  name = var.athena_database
}

resource "aws_athena_workgroup" "commitscope" {
  name = "${local.name_prefix}-wg"
  configuration {
    enforce_workgroup_configuration = true
    result_configuration {
      output_location = "s3://${aws_s3_bucket.data_lake.bucket}/curated/athena-results/"
    }
  }
  tags = local.common_tags
}

resource "aws_iam_role" "lambda_role" {
  name = "${local.name_prefix}-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_data_lake" {
  name = "${local.name_prefix}-lambda-data-lake"
  role = aws_iam_role.lambda_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.data_lake.arn,
          "${aws_s3_bucket.data_lake.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role" "glue_role" {
  name = "${local.name_prefix}-glue-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "glue.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_data_lake" {
  name = "${local.name_prefix}-glue-data-lake"
  role = aws_iam_role.glue_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.data_lake.arn,
          "${aws_s3_bucket.data_lake.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_glue_crawler" "processed" {
  name          = "${local.name_prefix}-crawler"
  database_name = aws_glue_catalog_database.commitscope.name
  role          = aws_iam_role.glue_role.arn
  s3_target {
    path = "s3://${aws_s3_bucket.data_lake.bucket}/processed/"
  }
  schema_change_policy {
    delete_behavior = "LOG"
    update_behavior = "UPDATE_IN_DATABASE"
  }
}

resource "aws_iam_role" "step_functions_role" {
  name = "${local.name_prefix}-sfn-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "states.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "step_functions_policy" {
  name = "${local.name_prefix}-sfn-policy"
  role = aws_iam_role.step_functions_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [aws_lambda_function.pipeline.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask", "ecs:StopTask", "ecs:DescribeTasks", "iam:PassRole"]
        Resource = "*"
      }
    ]
  })
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  output_path = "${path.module}/build/pipeline_lambda.zip"
  source {
    content  = <<-PY
def handler(event, context):
    return {"status": "placeholder", "event": event}
PY
    filename = "handler.py"
  }
}

resource "aws_lambda_function" "pipeline" {
  function_name    = "${local.name_prefix}-pipeline"
  role             = aws_iam_role.lambda_role.arn
  runtime          = "python3.11"
  handler          = "handler.handler"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 60
  tags             = local.common_tags
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${local.name_prefix}-pipeline"
  role_arn = aws_iam_role.step_functions_role.arn
  definition = jsonencode({
    StartAt = "Prepare"
    States = {
      Prepare = {
        Type     = "Task"
        Resource = aws_lambda_function.pipeline.arn
        Next     = var.container_cluster_arn != null && var.container_task_definition_arn != null ? "RunAnalysisContainer" : "Complete"
      }
      RunAnalysisContainer = {
        Type     = "Task"
        Resource = "arn:aws:states:::ecs:runTask.sync"
        Parameters = {
          LaunchType     = "FARGATE"
          Cluster        = var.container_cluster_arn
          TaskDefinition = var.container_task_definition_arn
          NetworkConfiguration = {
            AwsvpcConfiguration = {
              AssignPublicIp = "ENABLED"
              Subnets        = var.subnet_ids
              SecurityGroups = var.security_group_ids
            }
          }
        }
        Next = "Complete"
      }
      Complete = {
        Type = "Succeed"
      }
    }
  })
  tags = local.common_tags
}
