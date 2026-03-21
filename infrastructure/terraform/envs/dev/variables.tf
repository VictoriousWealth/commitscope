variable "project" {
  type    = string
  default = "commitscope"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "aws_region" {
  type    = string
  default = "eu-west-2"
}

variable "bucket_name" {
  type    = string
  default = "commitscope-nick-dev"
}

variable "athena_database" {
  type    = string
  default = "commitscope_dev"
}

variable "container_cluster_arn" {
  type    = string
  default = null
}

variable "container_task_definition_arn" {
  type    = string
  default = null
}

variable "subnet_ids" {
  type    = list(string)
  default = []
}

variable "security_group_ids" {
  type    = list(string)
  default = []
}
