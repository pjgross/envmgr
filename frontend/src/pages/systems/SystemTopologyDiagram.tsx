import { useEffect, useMemo } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  type Node,
  type Edge,
  MarkerType,
} from 'reactflow'
import 'reactflow/dist/style.css'
import dagre from '@dagrejs/dagre'
import { Box, Chip, Typography, CircularProgress, Alert } from '@mui/material'
import type { AppDispatch, RootState } from '../../store'
import { fetchTopology, clearTopology } from '../../store/topologySlice'
import type { SubSystemResponse } from '../../types/system'
import type { ComponentDependencyResponse } from '../../types/dependency'

// Color mapping by component_type
const COMPONENT_COLORS: Record<string, string> = {
  database: '#1976d2',      // blue
  cache: '#f57c00',         // amber
  message_queue: '#7b1fa2', // purple
  web_service: '#388e3c',   // green
  api_gateway: '#00796b',   // teal
  worker: '#e64a19',        // orange
  frontend: '#303f9f',      // indigo
  other: '#616161',         // grey
}

const NODE_WIDTH = 180
const NODE_HEIGHT = 70

function getLayoutedElements(
  subsystems: SubSystemResponse[],
  dependencies: ComponentDependencyResponse[]
) {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', ranksep: 80, nodesep: 40 })
  g.setDefaultEdgeLabel(() => ({}))

  subsystems.forEach((s) => g.setNode(String(s.id), { width: NODE_WIDTH, height: NODE_HEIGHT }))
  dependencies.forEach((d) => g.setEdge(String(d.from_subsystem_id), String(d.to_subsystem_id)))
  dagre.layout(g)

  const nodes: Node[] = subsystems.map((s) => {
    const { x, y } = g.node(String(s.id))
    const color = COMPONENT_COLORS[s.component_type] ?? COMPONENT_COLORS.other
    return {
      id: String(s.id),
      position: { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 },
      data: { label: s, color },
      type: 'subsystemNode',
    }
  })

  const edges: Edge[] = dependencies.map((d) => ({
    id: String(d.id),
    source: String(d.from_subsystem_id),
    target: String(d.to_subsystem_id),
    label: d.label ?? d.dependency_type,
    markerEnd: { type: MarkerType.ArrowClosed },
    ...(d.direction === 'two_way' ? { markerStart: { type: MarkerType.ArrowClosed } } : {}),
  }))

  return { nodes, edges }
}

// Custom node component
function SubsystemNode({ data }: { data: { label: SubSystemResponse; color: string } }) {
  const s = data.label
  return (
    <Box
      sx={{
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        border: `2px solid ${data.color}`,
        borderRadius: 1,
        bgcolor: 'background.paper',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        px: 1,
        cursor: 'default',
      }}
    >
      <Typography variant="body2" fontWeight="bold" noWrap sx={{ width: '100%', textAlign: 'center' }}>
        {s.name}
      </Typography>
      <Chip
        label={s.component_type.replace(/_/g, ' ')}
        size="small"
        sx={{ bgcolor: data.color, color: '#fff', fontSize: '0.65rem', height: 18, mt: 0.5 }}
      />
      {s.technology && (
        <Typography variant="caption" color="text.secondary" noWrap>
          {s.technology}
        </Typography>
      )}
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </Box>
  )
}

const nodeTypes = { subsystemNode: SubsystemNode }

interface Props {
  systemId: number
}

export default function SystemTopologyDiagram({ systemId }: Props) {
  const dispatch = useDispatch<AppDispatch>()
  const { data, loading, error } = useSelector((state: RootState) => state.topology)

  useEffect(() => {
    dispatch(fetchTopology(systemId))
    return () => {
      dispatch(clearTopology())
    }
  }, [systemId, dispatch])

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [], edges: [] }
    return getLayoutedElements(data.subsystems, data.dependencies)
  }, [data])

  if (loading) return <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}><CircularProgress /></Box>
  if (error) return <Alert severity="error">{error}</Alert>
  if (!data || data.subsystems.length === 0) {
    return (
      <Box sx={{ textAlign: 'center', mt: 4, color: 'text.secondary' }}>
        <Typography>No subsystems yet. Add subsystems to see the topology diagram.</Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ height: 500, border: 1, borderColor: 'divider', borderRadius: 1 }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </Box>
  )
}
