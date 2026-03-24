# Container Run Path

The heavy-analysis path is intended for ECS Fargate. Lambda stays limited to lightweight orchestration and helper work.

## Local Container Build

```bash
docker build -t commitscope:dev .
docker run --rm -e COMMITSCOPE_CONFIG=/app/examples/config.dev.json commitscope:dev
```

## ECS Expectations

- container image should package the `src/` application and pinned Python dependencies
- container image should include `git` and the parser dependencies used by the analyzers
- task command should run the same pipeline entrypoint used locally
- Step Functions should invoke the Fargate task synchronously for heavy analysis
- S3 and Glue/Athena remain the storage and query layers
- Python, Java, JavaScript, and TypeScript analysis should match the AST-backed local code path
