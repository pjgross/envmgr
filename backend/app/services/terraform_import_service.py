import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models.system import SubSystem


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


async def import_terraform(
    system_id: int,
    tenant_id: int,
    content: bytes,
    db: AsyncSession,
) -> dict[str, int]:
    """
    Parse a .tfstate JSON file and upsert SubSystems from Terraform resources.
    Dependencies are NOT created (tfstate has no explicit dependency graph).
    Returns counts.
    """
    try:
        state = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    resources = state.get('resources', [])
    if not isinstance(resources, list):
        raise ValueError("Invalid tfstate format: 'resources' must be a list")

    # Filter to managed resources only (skip data sources, which have mode='data')
    managed = [r for r in resources if isinstance(r, dict) and r.get('mode') == 'managed']

    if not managed:
        raise ValueError("No managed resources found in tfstate file")

    # Load existing subsystems for upsert by name
    result = await db.execute(
        select(SubSystem).where(
            SubSystem.system_id == system_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
    )
    existing = {s.name: s for s in result.scalars().all()}

    subsystems_created = 0
    subsystems_updated = 0

    for resource in managed:
        resource_type = resource.get('type', '')
        resource_name = resource.get('name', '')
        if not isinstance(resource_type, str) or not isinstance(resource_name, str):
            continue
        if not resource_type or not resource_name:
            continue

        # Use "{type}.{name}" as the SubSystem name for uniqueness
        subsystem_name = f"{resource_type}.{resource_name}"[:200]
        component_type = infer_component_type(resource_type)
        technology = resource_type[:100]

        if subsystem_name in existing:
            sub = existing[subsystem_name]
            sub.component_type = component_type
            sub.technology = technology
            await db.flush()
            subsystems_updated += 1
        else:
            sub = SubSystem(
                name=subsystem_name,
                system_id=system_id,
                tenant_id=tenant_id,
                component_type=component_type,
                technology=technology,
            )
            db.add(sub)
            subsystems_created += 1

    await db.flush()
    return {
        'subsystems_created': subsystems_created,
        'subsystems_updated': subsystems_updated,
    }
