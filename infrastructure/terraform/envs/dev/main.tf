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
  effective_container_image_uri = var.container_image_uri != null ? var.container_image_uri : (
    var.create_ecr_repository ? "${aws_ecr_repository.commitscope[0].repository_url}:latest" : null
  )
  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_ecr_repository" "commitscope" {
  count                = var.create_ecr_repository ? 1 : 0
  name                 = var.ecr_repository_name
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = local.common_tags
}

resource "aws_ecr_lifecycle_policy" "commitscope" {
  count      = var.create_ecr_repository ? 1 : 0
  repository = aws_ecr_repository.commitscope[0].name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the most recent 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
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

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${local.name_prefix}"
  retention_in_days = 14
  tags              = local.common_tags
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

resource "aws_iam_role_policy" "lambda_stepfunctions_helper" {
  name = "${local.name_prefix}-lambda-helper"
  role = aws_iam_role.lambda_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:DescribeTasks"]
        Resource = "*"
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
        Effect = "Allow"
        Action = ["ecs:RunTask", "ecs:StopTask", "ecs:DescribeTasks"]
        Resource = [
          aws_ecs_task_definition.analysis[0].arn
        ]
      },
      {
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          aws_iam_role.ecs_task_execution_role[0].arn,
          aws_iam_role.ecs_task_role[0].arn
        ]
      }
    ]
  })
}

resource "aws_iam_role" "ecs_task_execution_role" {
  count = local.effective_container_image_uri != null ? 1 : 0
  name  = "${local.name_prefix}-ecs-execution-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role" {
  count      = local.effective_container_image_uri != null ? 1 : 0
  role       = aws_iam_role.ecs_task_execution_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ecs_task_role" {
  count = local.effective_container_image_uri != null ? 1 : 0
  name  = "${local.name_prefix}-ecs-task-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "ecs_task_data_lake" {
  count = local.effective_container_image_uri != null ? 1 : 0
  name  = "${local.name_prefix}-ecs-task-data-lake"
  role  = aws_iam_role.ecs_task_role[0].id
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

resource "aws_ecs_cluster" "analysis" {
  count = local.effective_container_image_uri != null ? 1 : 0
  name  = "${local.name_prefix}-cluster"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = local.common_tags
}

resource "aws_ecs_task_definition" "analysis" {
  count                    = local.effective_container_image_uri != null ? 1 : 0
  family                   = "${local.name_prefix}-analysis"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.ecs_task_execution_role[0].arn
  task_role_arn            = aws_iam_role.ecs_task_role[0].arn
  container_definitions = jsonencode([
    {
      name      = "commitscope"
      image     = local.effective_container_image_uri
      essential = true
      command   = ["python", "-m", "commitscope.aws.container"]
      environment = [
        {
          name  = "COMMITSCOPE_CONFIG"
          value = "/app/examples/config.dev.json"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "commitscope"
        }
      }
    }
  ])
  tags = local.common_tags
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  output_path = "${path.module}/build/pipeline_lambda.zip"
  source {
    content  = <<-PY
import json

def handler(event, context):
    config_json = event.get("config_json")
    if isinstance(config_json, dict):
        config_json = json.dumps(config_json)
    return {
        "project": event.get("project", "commitscope"),
        "environment": event.get("environment", "dev"),
        "config_json": config_json,
        "container_overrides": [
            {
                "name": "commitscope",
                "environment": [
                    {"name": "COMMITSCOPE_CONFIG_JSON", "value": config_json}
                ],
            }
        ],
    }
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
        Parameters = {
          "config_json.$" = "$.config_json"
          "project.$"     = "$.project"
          "environment.$" = "$.environment"
        }
        ResultPath = "$.prepared"
        Next       = local.effective_container_image_uri != null ? "RunAnalysisContainer" : "Complete"
      }
      RunAnalysisContainer = {
        Type     = "Task"
        Resource = "arn:aws:states:::ecs:runTask.sync"
        Parameters = {
          LaunchType     = "FARGATE"
          Cluster        = aws_ecs_cluster.analysis[0].arn
          TaskDefinition = aws_ecs_task_definition.analysis[0].arn
          NetworkConfiguration = {
            AwsvpcConfiguration = {
              AssignPublicIp = "ENABLED"
              Subnets        = var.subnet_ids
              SecurityGroups = var.security_group_ids
            }
          }
          Overrides = {
            "ContainerOverrides.$" = "$.prepared.container_overrides"
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

resource "aws_athena_named_query" "core_ddl" {
  name        = "${local.name_prefix}-core-ddl"
  database    = aws_glue_catalog_database.commitscope.name
  workgroup   = aws_athena_workgroup.commitscope.name
  description = "Core Glue/Athena DDL for CommitScope tables"
  query       = <<-SQL
CREATE EXTERNAL TABLE IF NOT EXISTS ${var.athena_database}.commit_summary (
  total_classes int,
  total_methods int,
  avg_wmc double,
  avg_lcom double,
  max_cc int,
  total_loc int,
  total_files int,
  python_files int,
  non_python_files int
)
PARTITIONED BY (repo string, branch string, commit_hash string, commit_date string)
STORED AS PARQUET
LOCATION 's3://${var.bucket_name}/processed/commit_summary/';
  SQL
}

resource "aws_athena_named_query" "class_hotspots" {
  name        = "${local.name_prefix}-class-hotspots"
  database    = aws_glue_catalog_database.commitscope.name
  workgroup   = aws_athena_workgroup.commitscope.name
  description = "Hotspot classes for QuickSight"
  query       = <<-SQL
SELECT commit_date, class_name, wmc, fanin, cbo
FROM ${var.athena_database}.class_metrics
WHERE repo = 'YOUR_REPO'
ORDER BY commit_date, wmc DESC, fanin DESC;
  SQL
}

resource "aws_athena_named_query" "language_breakdown" {
  name        = "${local.name_prefix}-language-breakdown"
  database    = aws_glue_catalog_database.commitscope.name
  workgroup   = aws_athena_workgroup.commitscope.name
  description = "Language footprint for QuickSight"
  query       = <<-SQL
SELECT commit_date, language, sum(loc) AS total_loc
FROM ${var.athena_database}.file_metrics
WHERE repo = 'YOUR_REPO'
GROUP BY commit_date, language
ORDER BY commit_date, total_loc DESC;
  SQL
}
