output "data_lake_bucket" {
  value = aws_s3_bucket.data_lake.bucket
}

output "athena_database" {
  value = aws_glue_catalog_database.commitscope.name
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}

output "lambda_function_name" {
  value = aws_lambda_function.pipeline.function_name
}

output "ecs_cluster_arn" {
  value = try(aws_ecs_cluster.analysis[0].arn, null)
}

output "ecs_task_definition_arn" {
  value = try(aws_ecs_task_definition.analysis[0].arn, null)
}

output "ecr_repository_url" {
  value = try(aws_ecr_repository.commitscope[0].repository_url, null)
}

output "effective_container_image_uri" {
  value = local.effective_container_image_uri
}
