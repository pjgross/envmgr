import json
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.scanning.declared import DeclaredState, DeclaredSubsystem


TF_TYPE_MAP = {
    'aws_db_instance': 'database',
    'aws_rds_cluster': 'database',
    'aws_rds_cluster_instance': 'database',
    'google_sql_database_instance': 'database',
    'azurerm_sql_database': 'database',
    'azurerm_postgresql_flexible_server': 'database',
    'aws_elasticache_cluster': 'cache',
    'aws_elasticache_replication_group': 'cache',
    'google_redis_instance': 'cache',
    'azurerm_redis_cache': 'cache',
    'aws_mq_broker': 'message_queue',
    'aws_sqs_queue': 'message_queue',
    'aws_sns_topic': 'message_queue',
    'google_pubsub_topic': 'message_queue',
    'azurerm_servicebus_queue': 'message_queue',
    'aws_lambda_function': 'worker',
    'google_cloudfunctions_function': 'worker',
    'google_cloudfunctions2_function': 'worker',
    'azurerm_function_app': 'worker',
    'aws_alb': 'api_gateway',
    'aws_lb': 'api_gateway',
    'aws_api_gateway_rest_api': 'api_gateway',
    'aws_apigatewayv2_api': 'api_gateway',
    'google_compute_backend_service': 'api_gateway',
    'azurerm_api_management': 'api_gateway',
    'aws_ecs_service': 'web_service',
    'aws_elastic_beanstalk_environment': 'web_service',
    'google_cloud_run_service': 'web_service',
    'google_cloud_run_v2_service': 'web_service',
    'azurerm_app_service': 'web_service',
    'azurerm_linux_web_app': 'web_service',
    'azurerm_container_app': 'web_service',
    'kubernetes_deployment': 'web_service',
    'kubernetes_stateful_set': 'web_service',
}


def infer_component_type(resource_type: str) -> str:
    return TF_TYPE_MAP.get(resource_type, 'other')


def parse_tfstate(content: bytes, path: str) -> DeclaredState:
    """Read a .tfstate JSON file into the resources it records. Pure.

    Dependencies are not produced: tfstate carries no explicit dependency graph.
    """
    try:
        state = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    resources = state.get('resources', [])
    if not isinstance(resources, list):
        raise ValueError("Invalid tfstate format: 'resources' must be a list")

    declared = DeclaredState()
    for resource in resources:
        if not isinstance(resource, dict) or resource.get('mode') != 'managed':
            # mode='data' is something Terraform reads, not something it manages.
            continue
        resource_type = resource.get('type', '')
        resource_name = resource.get('name', '')
        if not isinstance(resource_type, str) or not isinstance(resource_name, str):
            continue
        if not resource_type or not resource_name:
            continue
        declared.subsystems.append(DeclaredSubsystem(
            name=f"{resource_type}.{resource_name}"[:200],
            component_type=infer_component_type(resource_type),
            technology=resource_type[:100],
            source_path=path[:500],
        ))
    return declared


async def import_terraform(
    system_id: int,
    tenant_id: int,
    content: bytes,
    db: AsyncSession,
    path: str = "terraform.tfstate",
) -> dict[str, int]:
    """Parse a .tfstate file and write what it records."""
    from app.db.models.system import SubSystemSource
    from app.services.scanning import reconcile

    declared = parse_tfstate(content, path)
    result = await reconcile.apply(
        db, system_id=system_id, tenant_id=tenant_id,
        source=SubSystemSource.TERRAFORM,
        edge_source=None,
        declared=declared,
    )
    return {
        'subsystems_created': result.subsystems_created,
        'subsystems_updated': result.subsystems_updated,
    }
