from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

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

ANALYSIS_ID = "commitscope-dev-overview"
ANALYSIS_NAME = "CommitScope Dev Overview"
DASHBOARD_ID = "commitscope-dev-overview"
DASHBOARD_NAME = "CommitScope Dev Overview"


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
    parser.add_argument("--skip-assets", action="store_true")
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

    dataset_arns = {}
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
        dataset_arns[spec.dataset_id] = dataset_arn
        print(f"Dataset ready: {spec.dataset_id} -> {dataset_arn}")

    if args.skip_assets:
        return

    definition = build_asset_definition(dataset_arns)
    analysis_arn = ensure_analysis(
        qs=qs,
        aws_account_id=args.aws_account_id,
        principal_arn=principal_arn,
        analysis_id=ANALYSIS_ID,
        analysis_name=ANALYSIS_NAME,
        definition=definition,
    )
    print(f"Analysis ready: {analysis_arn}")
    dashboard_arn = ensure_dashboard(
        qs=qs,
        aws_account_id=args.aws_account_id,
        principal_arn=principal_arn,
        dashboard_id=DASHBOARD_ID,
        dashboard_name=DASHBOARD_NAME,
        definition=definition,
    )
    print(f"Dashboard ready: {dashboard_arn}")


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


def ensure_analysis(
    *,
    qs,
    aws_account_id: str,
    principal_arn: str,
    analysis_id: str,
    analysis_name: str,
    definition: dict[str, Any],
) -> str:
    permissions = [
        {
            "Principal": principal_arn,
            "Actions": [
                "quicksight:RestoreAnalysis",
                "quicksight:UpdateAnalysisPermissions",
                "quicksight:DeleteAnalysis",
                "quicksight:DescribeAnalysisPermissions",
                "quicksight:QueryAnalysis",
                "quicksight:DescribeAnalysis",
                "quicksight:UpdateAnalysis",
            ],
        }
    ]
    try:
        existing = qs.describe_analysis(AwsAccountId=aws_account_id, AnalysisId=analysis_id)["Analysis"]
        qs.update_analysis(
            AwsAccountId=aws_account_id,
            AnalysisId=analysis_id,
            Name=analysis_name,
            Definition=definition,
            ValidationStrategy={"Mode": "LENIENT"},
        )
        return existing["Arn"]
    except qs.exceptions.ResourceNotFoundException:
        response = qs.create_analysis(
            AwsAccountId=aws_account_id,
            AnalysisId=analysis_id,
            Name=analysis_name,
            Definition=definition,
            Permissions=permissions,
            ValidationStrategy={"Mode": "LENIENT"},
        )
        return response["Arn"]


def ensure_dashboard(
    *,
    qs,
    aws_account_id: str,
    principal_arn: str,
    dashboard_id: str,
    dashboard_name: str,
    definition: dict[str, Any],
) -> str:
    permissions = [
        {
            "Principal": principal_arn,
            "Actions": [
                "quicksight:DescribeDashboard",
                "quicksight:ListDashboardVersions",
                "quicksight:UpdateDashboardPermissions",
                "quicksight:QueryDashboard",
                "quicksight:UpdateDashboard",
                "quicksight:DeleteDashboard",
                "quicksight:DescribeDashboardPermissions",
                "quicksight:UpdateDashboardPublishedVersion",
            ],
        }
    ]
    try:
        existing = qs.describe_dashboard(AwsAccountId=aws_account_id, DashboardId=dashboard_id)["Dashboard"]
        qs.update_dashboard(
            AwsAccountId=aws_account_id,
            DashboardId=dashboard_id,
            Name=dashboard_name,
            Definition=definition,
            ValidationStrategy={"Mode": "LENIENT"},
        )
        qs.update_dashboard_published_version(
            AwsAccountId=aws_account_id,
            DashboardId=dashboard_id,
            VersionNumber=existing["Version"]["VersionNumber"],
        )
        return existing["Arn"]
    except qs.exceptions.ResourceNotFoundException:
        response = qs.create_dashboard(
            AwsAccountId=aws_account_id,
            DashboardId=dashboard_id,
            Name=dashboard_name,
            Definition=definition,
            Permissions=permissions,
            ValidationStrategy={"Mode": "LENIENT"},
        )
        return response["Arn"]


def build_asset_definition(dataset_arns: dict[str, str]) -> dict[str, Any]:
    return {
        "DataSetIdentifierDeclarations": [
            {"Identifier": "commit_summary", "DataSetArn": dataset_arns["commitscope-dev-commit-summary"]},
            {"Identifier": "class_metrics", "DataSetArn": dataset_arns["commitscope-dev-class-metrics"]},
            {"Identifier": "file_metrics", "DataSetArn": dataset_arns["commitscope-dev-file-metrics"]},
        ],
        "Sheets": [
            {
                "SheetId": "overview",
                "Name": "Overview",
                "Title": "CommitScope Overview",
                "Visuals": [
                    line_chart_visual(
                        visual_id="avg-wmc-trend",
                        title="Average WMC by Commit Date",
                        dataset_identifier="commit_summary",
                        category_column="commit_date",
                        value_column="avg_wmc",
                    ),
                    bar_chart_visual(
                        visual_id="total-loc-trend",
                        title="Total LOC by Commit Date",
                        dataset_identifier="commit_summary",
                        category_column="commit_date",
                        value_column="total_loc",
                    ),
                    pie_chart_visual(
                        visual_id="language-footprint",
                        title="Language Footprint",
                        dataset_identifier="file_metrics",
                        category_column="language",
                        value_column="loc",
                    ),
                    table_visual(
                        visual_id="hotspot-classes",
                        title="Hotspot Classes",
                        dataset_identifier="class_metrics",
                        group_by_columns=["commit_date", "class_name"],
                        value_columns=["wmc", "fanin", "cbo", "rfc"],
                    ),
                ],
                "Layouts": [
                    {
                        "Configuration": {
                            "GridLayout": {
                                "Elements": [
                                    grid_element("avg-wmc-trend", 0, 18, 0, 8),
                                    grid_element("total-loc-trend", 18, 18, 0, 8),
                                    grid_element("language-footprint", 0, 12, 8, 8),
                                    grid_element("hotspot-classes", 12, 24, 8, 12),
                                ],
                                "CanvasSizeOptions": {
                                    "ScreenCanvasSizeOptions": {
                                        "ResizeOption": "FIXED",
                                        "OptimizedViewPortWidth": "1600px",
                                    }
                                },
                            }
                        }
                    }
                ],
            }
        ],
    }


def line_chart_visual(
    *,
    visual_id: str,
    title: str,
    dataset_identifier: str,
    category_column: str,
    value_column: str,
) -> dict[str, Any]:
    return {
        "LineChartVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "LineChartAggregatedFieldWells": {
                        "Category": [categorical_dimension(dataset_identifier, category_column)],
                        "Values": [numerical_measure(dataset_identifier, value_column, "AVERAGE")],
                    }
                }
            },
        }
    }


def bar_chart_visual(
    *,
    visual_id: str,
    title: str,
    dataset_identifier: str,
    category_column: str,
    value_column: str,
) -> dict[str, Any]:
    return {
        "BarChartVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "BarChartAggregatedFieldWells": {
                        "Category": [categorical_dimension(dataset_identifier, category_column)],
                        "Values": [numerical_measure(dataset_identifier, value_column, "SUM")],
                    }
                }
            },
        }
    }


def pie_chart_visual(
    *,
    visual_id: str,
    title: str,
    dataset_identifier: str,
    category_column: str,
    value_column: str,
) -> dict[str, Any]:
    return {
        "PieChartVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "PieChartAggregatedFieldWells": {
                        "Category": [categorical_dimension(dataset_identifier, category_column)],
                        "Values": [numerical_measure(dataset_identifier, value_column, "SUM")],
                    }
                }
            },
        }
    }


def table_visual(
    *,
    visual_id: str,
    title: str,
    dataset_identifier: str,
    group_by_columns: list[str],
    value_columns: list[str],
) -> dict[str, Any]:
    return {
        "TableVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "TableAggregatedFieldWells": {
                        "GroupBy": [categorical_dimension(dataset_identifier, column) for column in group_by_columns],
                        "Values": [numerical_measure(dataset_identifier, column, "SUM") for column in value_columns],
                    }
                }
            },
        }
    }


def categorical_dimension(dataset_identifier: str, column_name: str) -> dict[str, Any]:
    return {
        "CategoricalDimensionField": {
            "FieldId": f"{dataset_identifier}-{column_name}-dimension",
            "Column": {
                "DataSetIdentifier": dataset_identifier,
                "ColumnName": column_name,
            },
        }
    }


def numerical_measure(dataset_identifier: str, column_name: str, aggregation: str) -> dict[str, Any]:
    return {
        "NumericalMeasureField": {
            "FieldId": f"{dataset_identifier}-{column_name}-measure",
            "Column": {
                "DataSetIdentifier": dataset_identifier,
                "ColumnName": column_name,
            },
            "AggregationFunction": {
                "SimpleNumericalAggregation": aggregation,
            },
        }
    }


def grid_element(element_id: str, column_index: int, column_span: int, row_index: int, row_span: int) -> dict[str, Any]:
    return {
        "ElementId": element_id,
        "ElementType": "VISUAL",
        "ColumnIndex": column_index,
        "ColumnSpan": column_span,
        "RowIndex": row_index,
        "RowSpan": row_span,
    }


if __name__ == "__main__":
    main()
