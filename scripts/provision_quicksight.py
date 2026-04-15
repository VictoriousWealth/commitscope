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
    TableSpec("commitscope-dev-method-metrics", "CommitScope Method Metrics", "method_metrics", "methodmetrics"),
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
            "CustomSql": {
                "DataSourceArn": data_source_arn,
                "Name": spec.name,
                "SqlQuery": build_latest_scope_sql(database, spec.table_name),
                "Columns": input_columns,
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


def build_latest_scope_sql(database: str, table_name: str) -> str:
    latest_scope = f"""
WITH latest_scope AS (
    SELECT execution_id
    FROM {database}.commit_summary
    WHERE execution_id IS NOT NULL
    GROUP BY execution_id
    ORDER BY max(execution_started_at) DESC, execution_id DESC
    LIMIT 1
)
""".strip()
    return (
        latest_scope
        + f"""
SELECT t.*
FROM {database}.{table_name} AS t
JOIN latest_scope AS latest
  ON t.execution_id = latest.execution_id
""".rstrip()
    )


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
        latest_version = max(
            version["VersionNumber"]
            for version in qs.list_dashboard_versions(
                AwsAccountId=aws_account_id,
                DashboardId=dashboard_id,
            )["DashboardVersionSummaryList"]
        )
        qs.update_dashboard_published_version(
            AwsAccountId=aws_account_id,
            DashboardId=dashboard_id,
            VersionNumber=latest_version,
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
            {"Identifier": "method_metrics", "DataSetArn": dataset_arns["commitscope-dev-method-metrics"]},
            {"Identifier": "file_metrics", "DataSetArn": dataset_arns["commitscope-dev-file-metrics"]},
        ],
        "Sheets": [
            {
                "SheetId": "repo-trends",
                "Name": "Repo Trends",
                "Title": "Repository Trends",
                "Visuals": [
                    line_chart_visual(
                        visual_id="avg-wmc-trend",
                        title="Average WMC by Commit Date",
                        dataset_identifier="commit_summary",
                        category_column="commit_date",
                        value_column="avg_wmc",
                        aggregation="AVERAGE",
                    ),
                    line_chart_visual(
                        visual_id="peak-cc-trend",
                        title="Peak CC by Commit Date",
                        dataset_identifier="commit_summary",
                        category_column="commit_date",
                        value_column="max_cc",
                        aggregation="MAX",
                    ),
                    line_chart_visual(
                        visual_id="total-loc-trend",
                        title="Total LOC by Commit Date",
                        dataset_identifier="commit_summary",
                        category_column="commit_date",
                        value_column="total_loc",
                        aggregation="SUM",
                    ),
                    pie_chart_visual(
                        visual_id="language-footprint",
                        title="Language Footprint by LOC",
                        dataset_identifier="file_metrics",
                        group_column="language",
                        size_column="loc",
                        aggregation="SUM",
                    ),
                    table_visual(
                        visual_id="commit-summary-table",
                        title="Commit Summary Snapshot",
                        dataset_identifier="commit_summary",
                        group_by_columns=["commit_date"],
                        value_columns=[
                            ("total_classes", "MAX"),
                            ("total_methods", "MAX"),
                            ("total_files", "MAX"),
                            ("total_loc", "MAX"),
                            ("max_cc", "MAX"),
                        ],
                    ),
                ],
                "Layouts": [
                    {
                        "Configuration": {
                            "GridLayout": {
                                "Elements": [
                                    grid_element("avg-wmc-trend", 0, 18, 0, 8),
                                    grid_element("total-loc-trend", 18, 18, 0, 8),
                                    grid_element("peak-cc-trend", 0, 18, 8, 8),
                                    grid_element("language-footprint", 18, 18, 8, 8),
                                    grid_element("commit-summary-table", 0, 36, 16, 12),
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
            ,
            {
                "SheetId": "class-hotspots",
                "Name": "Class Hotspots",
                "Title": "Class Hotspots",
                "Visuals": [
                    scatter_plot_visual(
                        visual_id="lcom-vs-cbo",
                        title="LCOM vs CBO",
                        dataset_identifier="class_metrics",
                        x_column="lcom",
                        y_column="cbo",
                    ),
                    scatter_plot_visual(
                        visual_id="wmc-vs-fanin",
                        title="WMC vs FANIN",
                        dataset_identifier="class_metrics",
                        x_column="wmc",
                        y_column="fanin",
                    ),
                    bar_chart_visual(
                        visual_id="wmc-by-class",
                        title="Peak WMC by Class",
                        dataset_identifier="class_metrics",
                        category_column="class_name",
                        value_column="wmc",
                        aggregation="MAX",
                    ),
                    bar_chart_visual(
                        visual_id="fanin-by-class",
                        title="Peak FANIN by Class",
                        dataset_identifier="class_metrics",
                        category_column="class_name",
                        value_column="fanin",
                        aggregation="MAX",
                    ),
                    bar_chart_visual(
                        visual_id="rfc-by-class",
                        title="Peak RFC by Class",
                        dataset_identifier="class_metrics",
                        category_column="class_name",
                        value_column="rfc",
                        aggregation="MAX",
                    ),
                    pie_chart_visual(
                        visual_id="class-share",
                        title="Language Share by WMC",
                        dataset_identifier="class_metrics",
                        group_column="language",
                        size_column="wmc",
                        aggregation="SUM",
                    ),
                    pie_chart_visual(
                        visual_id="wmc-share-by-class",
                        title="WMC Share by Class",
                        dataset_identifier="class_metrics",
                        group_column="class_name",
                        size_column="wmc",
                        aggregation="MAX",
                    ),
                    pie_chart_visual(
                        visual_id="loc-share-by-class",
                        title="LOC Share by Class",
                        dataset_identifier="class_metrics",
                        group_column="class_name",
                        size_column="loc",
                        aggregation="MAX",
                    ),
                    table_visual(
                        visual_id="class-hotspot-table",
                        title="Class Hotspot Detail",
                        dataset_identifier="class_metrics",
                        group_by_columns=["language", "class_name"],
                        value_columns=[
                            ("wmc", "MAX"),
                            ("fanin", "MAX"),
                            ("cbo", "MAX"),
                            ("rfc", "MAX"),
                            ("lcom", "MAX"),
                        ],
                    ),
                ],
                "Layouts": [
                    {
                        "Configuration": {
                            "GridLayout": {
                                "Elements": [
                                    grid_element("lcom-vs-cbo", 0, 18, 0, 10),
                                    grid_element("class-share", 18, 18, 0, 10),
                                    grid_element("wmc-vs-fanin", 0, 18, 10, 10),
                                    grid_element("rfc-by-class", 18, 18, 10, 10),
                                    grid_element("wmc-share-by-class", 0, 12, 20, 10),
                                    grid_element("wmc-by-class", 12, 12, 20, 10),
                                    grid_element("fanin-by-class", 24, 12, 20, 10),
                                    grid_element("loc-share-by-class", 0, 12, 30, 10),
                                    grid_element("class-hotspot-table", 12, 24, 30, 12),
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
            },
            {
                "SheetId": "method-hotspots",
                "Name": "Method Hotspots",
                "Title": "Method Hotspots",
                "Visuals": [
                    scatter_plot_visual(
                        visual_id="cc-vs-loc",
                        title="CC vs LOC",
                        dataset_identifier="method_metrics",
                        x_column="cc",
                        y_column="loc",
                    ),
                    scatter_plot_visual(
                        visual_id="fanin-vs-fanout-methods",
                        title="Method FANIN vs FANOUT",
                        dataset_identifier="method_metrics",
                        x_column="fanout",
                        y_column="fanin",
                    ),
                    bar_chart_visual(
                        visual_id="parameters-by-method",
                        title="Peak Parameters by Method",
                        dataset_identifier="method_metrics",
                        category_column="method_name",
                        value_column="parameters",
                        aggregation="MAX",
                    ),
                    bar_chart_visual(
                        visual_id="fanin-by-method",
                        title="Peak FANIN by Method",
                        dataset_identifier="method_metrics",
                        category_column="method_name",
                        value_column="fanin",
                        aggregation="MAX",
                    ),
                    bar_chart_visual(
                        visual_id="cc-by-method",
                        title="Peak CC by Method",
                        dataset_identifier="method_metrics",
                        category_column="method_name",
                        value_column="cc",
                        aggregation="MAX",
                    ),
                    pie_chart_visual(
                        visual_id="method-share",
                        title="Language Share by Method LOC",
                        dataset_identifier="method_metrics",
                        group_column="language",
                        size_column="loc",
                        aggregation="SUM",
                    ),
                    pie_chart_visual(
                        visual_id="loc-share-by-method",
                        title="LOC Share by Method",
                        dataset_identifier="method_metrics",
                        group_column="method_name",
                        size_column="loc",
                        aggregation="MAX",
                    ),
                    pie_chart_visual(
                        visual_id="cc-share-by-method",
                        title="CC Share by Method",
                        dataset_identifier="method_metrics",
                        group_column="method_name",
                        size_column="cc",
                        aggregation="MAX",
                    ),
                    table_visual(
                        visual_id="method-hotspot-table",
                        title="Method Hotspot Detail",
                        dataset_identifier="method_metrics",
                        group_by_columns=["language", "class_name", "method_name"],
                        value_columns=[
                            ("cc", "MAX"),
                            ("loc", "MAX"),
                            ("fanin", "MAX"),
                            ("fanout", "MAX"),
                            ("parameters", "MAX"),
                        ],
                    ),
                ],
                "Layouts": [
                    {
                        "Configuration": {
                            "GridLayout": {
                                "Elements": [
                                    grid_element("cc-vs-loc", 0, 18, 0, 10),
                                    grid_element("method-share", 18, 18, 0, 10),
                                    grid_element("fanin-vs-fanout-methods", 0, 18, 10, 10),
                                    grid_element("cc-by-method", 18, 18, 10, 10),
                                    grid_element("loc-share-by-method", 0, 12, 20, 10),
                                    grid_element("parameters-by-method", 12, 12, 20, 10),
                                    grid_element("fanin-by-method", 24, 12, 20, 10),
                                    grid_element("cc-share-by-method", 0, 12, 30, 10),
                                    grid_element("method-hotspot-table", 12, 24, 30, 12),
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
    aggregation: str,
) -> dict[str, Any]:
    return {
        "LineChartVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "LineChartAggregatedFieldWells": {
                        "Category": [categorical_dimension(dataset_identifier, category_column)],
                        "Values": [numerical_measure(dataset_identifier, value_column, aggregation)],
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
    aggregation: str,
) -> dict[str, Any]:
    return {
        "BarChartVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "BarChartAggregatedFieldWells": {
                        "Category": [categorical_dimension(dataset_identifier, category_column)],
                        "Values": [numerical_measure(dataset_identifier, value_column, aggregation)],
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
    group_column: str,
    size_column: str,
    aggregation: str,
) -> dict[str, Any]:
    return {
        "PieChartVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "PieChartAggregatedFieldWells": {
                        "Category": [categorical_dimension(dataset_identifier, group_column)],
                        "Values": [numerical_measure(dataset_identifier, size_column, aggregation)],
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
    value_columns: list[tuple[str, str]],
) -> dict[str, Any]:
    return {
        "TableVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "TableAggregatedFieldWells": {
                        "GroupBy": [categorical_dimension(dataset_identifier, column) for column in group_by_columns],
                        "Values": [numerical_measure(dataset_identifier, column, aggregation) for column, aggregation in value_columns],
                    }
                }
            },
        }
    }


def scatter_plot_visual(
    *,
    visual_id: str,
    title: str,
    dataset_identifier: str,
    x_column: str,
    y_column: str,
) -> dict[str, Any]:
    return {
        "ScatterPlotVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "ScatterPlotUnaggregatedFieldWells": {
                        "XAxis": [numerical_dimension(dataset_identifier, x_column)],
                        "YAxis": [numerical_dimension(dataset_identifier, y_column)],
                    }
                }
            },
        }
    }


def tree_map_visual(
    *,
    visual_id: str,
    title: str,
    dataset_identifier: str,
    group_column: str,
    size_column: str,
    aggregation: str,
) -> dict[str, Any]:
    return {
        "TreeMapVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "TreeMapAggregatedFieldWells": {
                        "Groups": [categorical_dimension(dataset_identifier, group_column)],
                        "Sizes": [numerical_measure(dataset_identifier, size_column, aggregation)],
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


def numerical_dimension(dataset_identifier: str, column_name: str) -> dict[str, Any]:
    return {
        "NumericalDimensionField": {
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
