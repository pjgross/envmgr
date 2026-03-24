import { useCallback, useEffect, useMemo, useState } from 'react'
import ReactFlow, {
  Background, Controls, MiniMap, Handle, Position,
  type Node, type Edge, MarkerType,
} from 'reactflow'
import 'reactflow/dist/style.css'
import dagre from '@dagrejs/dagre'
import { Box, Chip, Typography, CircularProgress, Alert } from '@mui/material'
import SystemGroupNode from '../../components/topology/SystemGroupNode'
import DependencyDetailPane from '../../components/topology/DependencyDetailPane'
import { environmentService } from '../../services/environmentService'
import type { EnvSubsystemNode } from '../../types/environment'
import type { ComponentDependencyResponse } from '../../types/dependency'

const COMPONENT_COLORS: Record<string, string> = {
  database: '#1976d2', cache: '#f57c00', message_queue: '#7b1fa2',
  web_service: '#388e3c', api_gateway: '#00796b', worker: '#e64a19',
  frontend: '#303f9f', other: '#616161',
}
const MOCK_COLOR = '#9e9e9e'

const NODE_WIDTH = 180
const NODE_HEIGHT = 70
const GROUP_PADDING = 40
const GROUP_LABEL_HEIGHT = 20
const GROUP_GAP = 80

function SubsystemNode({ data }: { data: { node: EnvSubsystemNode } }) {
  const s = data.node
  const isMocked = s.is_mocked
  const color = isMocked ? MOCK_COLOR : (COMPONENT_COLORS[s.component_type] ?? COMPONENT_COLORS.other)
  return (
    <Box
      sx={{
        width: NODE_WIDTH, height: NODE_HEIGHT,
        border: `2px ${isMocked ? 'dashed' : 'solid'} ${color}`,
        borderRadius: 1,
        bgcolor: isMocked ? 'rgba(158,158,158,0.06)' : 'background.paper',
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', px: 1, cursor: 'default',
        opacity: isMocked ? 0.75 : 1,
      }}
    >
      <Typography variant="body2" fontWeight="bold" noWrap sx={{ width: '100%', textAlign: 'center' }}>
        {s.name}
      </Typography>
      <Chip
        label={s.component_type.replace(/_/g, ' ')}
        size="small"
        sx={{ bgcolor: color, color: '#fff', fontSize: '0.65rem', height: 18, mt: 0.5 }}
      />
      {isMocked && (
        <Typography variant="caption" sx={{ color: MOCK_COLOR, fontSize: '0.6rem' }}>mocked</Typography>
      )}
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </Box>
  )
}

const nodeTypes = { subsystemNode: SubsystemNode, systemGroupNode: SystemGroupNode }

function getLayoutedElements(
  subsystems: EnvSubsystemNode[],
  dependencies: ComponentDependencyResponse[],
  outsideSubsystems: EnvSubsystemNode[],
  outsideDependencies: ComponentDependencyResponse[],
  systemNames: Record<string, string>,
  envSystemIds: Set<number>,
  selectedDepId: number | null,
) {
  const allSubsystems = [...subsystems, ...outsideSubsystems]
  const allDependencies = [...dependencies, ...outsideDependencies]
  if (allSubsystems.length === 0) return { nodes: [], edges: [] }

  const groups = new Map<number, EnvSubsystemNode[]>()
  for (const s of allSubsystems) {
    if (!groups.has(s.system_id)) groups.set(s.system_id, [])
    groups.get(s.system_id)!.push(s)
  }

  interface GroupLayout {
    nodePositions: Map<number, { x: number; y: number }>
    contentWidth: number
    contentHeight: number
  }

  const groupLayouts = new Map<number, GroupLayout>()
  for (const [sysId, subs] of groups) {
    const subIds = new Set(subs.map((s) => s.id))
    const g = new dagre.graphlib.Graph()
    g.setGraph({ rankdir: 'LR', ranksep: 80, nodesep: 40 })
    g.setDefaultEdgeLabel(() => ({}))
    subs.forEach((s) => g.setNode(String(s.id), { width: NODE_WIDTH, height: NODE_HEIGHT }))
    allDependencies.forEach((d) => {
      if (subIds.has(d.from_subsystem_id) && subIds.has(d.to_subsystem_id)) {
        g.setEdge(String(d.from_subsystem_id), String(d.to_subsystem_id))
      }
    })
    dagre.layout(g)

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    subs.forEach((s) => {
      const pos = g.node(String(s.id))
      minX = Math.min(minX, pos.x - NODE_WIDTH / 2); minY = Math.min(minY, pos.y - NODE_HEIGHT / 2)
      maxX = Math.max(maxX, pos.x + NODE_WIDTH / 2); maxY = Math.max(maxY, pos.y + NODE_HEIGHT / 2)
    })

    const positions = new Map<number, { x: number; y: number }>()
    subs.forEach((s) => {
      const pos = g.node(String(s.id))
      positions.set(s.id, { x: pos.x - minX, y: pos.y - minY })
    })
    groupLayouts.set(sysId, {
      nodePositions: positions,
      contentWidth: maxX - minX,
      contentHeight: maxY - minY,
    })
  }

  const allSysIds = [...groups.keys()]
  const sortedSysIds = allSysIds.sort((a, b) => {
    const aInEnv = envSystemIds.has(a) ? 0 : 1
    const bInEnv = envSystemIds.has(b) ? 0 : 1
    return aInEnv - bInEnv || a - b
  })

  const groupOrigins = new Map<number, { x: number; y: number }>()
  let cursorX = 0
  for (const sysId of sortedSysIds) {
    const layout = groupLayouts.get(sysId)!
    groupOrigins.set(sysId, { x: cursorX, y: 0 })
    cursorX += layout.contentWidth + GROUP_PADDING * 2 + GROUP_GAP
  }

  const groupNodes: Node[] = sortedSysIds.map((sysId) => {
    const layout = groupLayouts.get(sysId)!
    const origin = groupOrigins.get(sysId)!
    const inEnv = envSystemIds.has(sysId)
    const label = inEnv
      ? (systemNames[String(sysId)] ?? `System ${sysId}`)
      : `${systemNames[String(sysId)] ?? `System ${sysId}`} — not in environment`
    return {
      id: `group-${sysId}`,
      type: 'systemGroupNode',
      position: { x: origin.x, y: origin.y },
      data: { label, isCurrent: inEnv },
      style: {
        width: layout.contentWidth + GROUP_PADDING * 2,
        height: layout.contentHeight + GROUP_PADDING * 2 + GROUP_LABEL_HEIGHT,
      },
      selectable: false,
      draggable: false,
    }
  })

  const subsystemNodes: Node[] = allSubsystems.map((s) => {
    const layout = groupLayouts.get(s.system_id)!
    const nodeCenter = layout.nodePositions.get(s.id)!
    return {
      id: String(s.id),
      parentId: `group-${s.system_id}`,
      position: {
        x: nodeCenter.x - NODE_WIDTH / 2 + GROUP_PADDING,
        y: nodeCenter.y - NODE_HEIGHT / 2 + GROUP_PADDING + GROUP_LABEL_HEIGHT,
      },
      data: { node: s },
      type: 'subsystemNode',
    }
  })

  const edges: Edge[] = allDependencies.map((d) => ({
    id: String(d.id),
    source: String(d.from_subsystem_id),
    target: String(d.to_subsystem_id),
    label: d.label ?? d.dependency_type,
    markerEnd: { type: MarkerType.ArrowClosed },
    ...(d.direction === 'two_way' ? { markerStart: { type: MarkerType.ArrowClosed } } : {}),
    style: d.id === selectedDepId ? { stroke: '#1976d2', strokeWidth: 2.5 } : undefined,
  }))

  return { nodes: [...groupNodes, ...subsystemNodes], edges }
}

interface EnvironmentTopologyData {
  environment_id: number
  subsystems: EnvSubsystemNode[]
  dependencies: ComponentDependencyResponse[]
  system_names: Record<string, string>
  outside_subsystems: EnvSubsystemNode[]
  outside_dependencies: ComponentDependencyResponse[]
}

interface Props {
  envId: number
}

export default function EnvironmentTopologyDiagram({ envId }: Props) {
  const [data, setData] = useState<EnvironmentTopologyData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedDepId, setSelectedDepId] = useState<number | null>(null)

  useEffect(() => {
    setLoading(true)
    environmentService.getEnvironmentTopology(envId)
      .then((d) => { setData(d as EnvironmentTopologyData); setLoading(false) })
      .catch((e: Error) => { setError(e.message ?? 'Failed to load topology'); setLoading(false) })
  }, [envId])

  useEffect(() => { setSelectedDepId(null) }, [data])

  const envSystemIds = useMemo(() => {
    if (!data) return new Set<number>()
    return new Set(data.subsystems.map((s) => s.system_id))
  }, [data])

  const selectedDep = useMemo(() => {
    if (selectedDepId === null || !data) return null
    return [...data.dependencies, ...data.outside_dependencies]
      .find((d) => d.id === selectedDepId) ?? null
  }, [selectedDepId, data])

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [], edges: [] }
    return getLayoutedElements(
      data.subsystems,
      data.dependencies,
      data.outside_subsystems,
      data.outside_dependencies,
      data.system_names,
      envSystemIds,
      selectedDepId,
    )
  }, [data, envSystemIds, selectedDepId])

  const handleEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    const id = parseInt(edge.id, 10)
    setSelectedDepId((prev) => (prev === id ? null : id))
  }, [])

  if (loading) return <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}><CircularProgress /></Box>
  if (error) return <Alert severity="error">{error}</Alert>
  if (!data || data.subsystems.length === 0) {
    return (
      <Box sx={{ textAlign: 'center', mt: 4, color: 'text.secondary' }}>
        <Typography>No subsystems configured. Add systems with subsystems to see the topology.</Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ display: 'flex', height: 500, border: 1, borderColor: 'divider', borderRadius: 1, overflow: 'hidden' }}>
      <Box sx={{ flex: 1, minWidth: '60%', position: 'relative' }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          onEdgeClick={handleEdgeClick}
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </Box>
      {selectedDep && (
        <DependencyDetailPane dep={selectedDep} onClose={() => setSelectedDepId(null)} />
      )}
    </Box>
  )
}
