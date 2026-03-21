output "data_lake_bucket" {
  value = aws_s3_bucket.data_lake.bucket
}

output "athena_database" {
  value = aws_glue_catalog_database.commitscope.name
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}
