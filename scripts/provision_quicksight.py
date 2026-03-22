from __future__ import annotations

import argparse
from dataclasses import dataclass

import boto3


@dataclass(slots=True)
class TableSpec:
    dataset_id: str
    name: str
    table_name: str
    quicksight_table_id: str


TABLE_SPECS = (
    TableSpec("commitscope-dev-commit-summary", "CommitScope Commit Summary", "commit_summary", "commitsummary"),
    TableSpec("commitscope-dev-class-metrics", "CommitScope Class Metrics", "class_metrics", "classmetrics"),
    TableSpec("commitscope-dev-file-metrics", "CommitScope File Metrics", "file_metrics", "filemetrics"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aws-account-id", default="463470943939")
    parser.add_argument("--quicksight-region", default="eu-west-2")
    parser.add_argument("--identity-region", default="eu-west-1")
    parser.add_argument("--data-region", default="eu-west-2")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--principal-arn", default=None)
    parser.add_argument("--database", default="commitscope_dev")
    parser.add_argument("--workgroup", default="commitscope-dev-wg")
    parser.add_argument("--data-source-id", default="commitscope-athena")
    parser.add_argument("--data-source-name", default="CommitScope Athena")
    parser.add_argument("--athena-role-arn", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    qs = boto3.client("quicksight", region_name=args.quicksight_region)
    qs_identity = boto3.client("quicksight", region_name=args.identity_region)
    glue = boto3.client("glue", region_name=args.data_region)

    principal_arn = args.principal_arn or get_principal_arn(qs_identity, args.aws_account_id, args.namespace)
    print(f"QuickSight principal: {principal_arn}")

    data_source_arn = ensure_athena_data_source(
        qs=qs,
        aws_account_id=args.aws_account_id,
        principal_arn=principal_arn,
        data_source_id=args.data_source_id,
        data_source_name=args.data_source_name,
        workgroup=args.workgroup,
        athena_role_arn=args.athena_role_arn or f"arn:aws:iam::{args.aws_account_id}:role/commitscope-dev-quicksight-athena-role",
    )
    print(f"Data source ARN: {data_source_arn}")

    for spec in TABLE_SPECS:
        table = glue.get_table(DatabaseName=args.database, Name=spec.table_name)["Table"]
        input_columns = build_input_columns(table)
        dataset_arn = ensure_data_set(
            qs=qs,
            aws_account_id=args.aws_account_id,
            principal_arn=principal_arn,
            data_source_arn=data_source_arn,
            database=args.database,
            spec=spec,
            input_columns=input_columns,
        )
        print(f"Dataset ready: {spec.dataset_id} -> {dataset_arn}")


def get_principal_arn(qs, aws_account_id: str, namespace: str) -> str:
    users = qs.list_users(AwsAccountId=aws_account_id, Namespace=namespace)["UserList"]
    if not users:
        raise RuntimeError("No QuickSight users found in the account")
    return users[0]["Arn"]


def ensure_athena_data_source(
    *,
    qs,
    aws_account_id: str,
    principal_arn: str,
    data_source_id: str,
    data_source_name: str,
    workgroup: str,
    athena_role_arn: str,
) -> str:
    permissions = [
        {
            "Principal": principal_arn,
            "Actions": [
                "quicksight:DescribeDataSource",
                "quicksight:DescribeDataSourcePermissions",
                "quicksight:PassDataSource",
                "quicksight:UpdateDataSource",
                "quicksight:DeleteDataSource",
                "quicksight:UpdateDataSourcePermissions",
            ],
        }
    ]
    try:
        existing = qs.describe_data_source(
            AwsAccountId=aws_account_id,
            DataSourceId=data_source_id,
        )["DataSource"]
        qs.update_data_source(
            AwsAccountId=aws_account_id,
            DataSourceId=data_source_id,
            Name=data_source_name,
            DataSourceParameters={"AthenaParameters": {"WorkGroup": workgroup, "RoleArn": athena_role_arn}},
        )
        return existing["Arn"]
    except qs.exceptions.ResourceNotFoundException:
        response = qs.create_data_source(
            AwsAccountId=aws_account_id,
            DataSourceId=data_source_id,
            Name=data_source_name,
            Type="ATHENA",
            DataSourceParameters={"AthenaParameters": {"WorkGroup": workgroup, "RoleArn": athena_role_arn}},
            Permissions=permissions,
        )
        return response["Arn"]


def build_input_columns(table: dict) -> list[dict]:
    columns = table["StorageDescriptor"]["Columns"] + table.get("PartitionKeys", [])
    return [{"Name": column["Name"], "Type": map_glue_type(column["Type"])} for column in columns]


def map_glue_type(glue_type: str) -> str:
    normalized = glue_type.lower()
    if normalized in {"bigint", "int", "integer", "smallint", "tinyint"}:
        return "INTEGER"
    if normalized in {"double", "float", "decimal"}:
        return "DECIMAL"
    if normalized in {"boolean", "bool"}:
        return "BOOLEAN"
    return "STRING"


def ensure_data_set(
    *,
    qs,
    aws_account_id: str,
    principal_arn: str,
    data_source_arn: str,
    database: str,
    spec: TableSpec,
    input_columns: list[dict],
) -> str:
    permissions = [
        {
            "Principal": principal_arn,
            "Actions": [
                "quicksight:DescribeDataSet",
                "quicksight:DescribeDataSetPermissions",
                "quicksight:PassDataSet",
                "quicksight:DescribeIngestion",
                "quicksight:ListIngestions",
                "quicksight:UpdateDataSet",
                "quicksight:DeleteDataSet",
                "quicksight:CreateIngestion",
                "quicksight:CancelIngestion",
                "quicksight:UpdateDataSetPermissions",
            ],
        }
    ]
    physical_table_map = {
        spec.quicksight_table_id: {
            "RelationalTable": {
                "DataSourceArn": data_source_arn,
                "Catalog": "AwsDataCatalog",
                "Schema": database,
                "Name": spec.table_name,
                "InputColumns": input_columns,
            }
        }
    }
    logical_table_map = {
        spec.quicksight_table_id: {
            "Alias": spec.name,
            "Source": {"PhysicalTableId": spec.quicksight_table_id},
        }
    }
    try:
        existing = qs.describe_data_set(
            AwsAccountId=aws_account_id,
            DataSetId=spec.dataset_id,
        )["DataSet"]
        qs.update_data_set(
            AwsAccountId=aws_account_id,
            DataSetId=spec.dataset_id,
            Name=spec.name,
            PhysicalTableMap=physical_table_map,
            LogicalTableMap=logical_table_map,
            ImportMode="DIRECT_QUERY",
        )
        return existing["Arn"]
    except qs.exceptions.ResourceNotFoundException:
        response = qs.create_data_set(
            AwsAccountId=aws_account_id,
            DataSetId=spec.dataset_id,
            Name=spec.name,
            PhysicalTableMap=physical_table_map,
            LogicalTableMap=logical_table_map,
            ImportMode="DIRECT_QUERY",
            Permissions=permissions,
        )
        return response["Arn"]


if __name__ == "__main__":
    main()
