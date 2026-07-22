import { useState } from 'react';
import { Box, Paper, Tab, Tabs } from '@mui/material';
import type { ReleaseResponse } from '../../../types/release';
import ReleaseMainTab from '../../../components/releases/ReleaseMainTab';
import ReleasePlanTab from '../../../components/releases/ReleasePlanTab';
import ReleaseEnvironmentsTab from '../../../components/releases/ReleaseEnvironmentsTab';
import ReleaseLinkedRequestsTab from '../../../components/releases/ReleaseLinkedRequestsTab';
import ReleaseScopeTab from '../../../components/releases/ReleaseScopeTab';
import { MembersTab } from './MembersTab';
import { SystemsRollupTab } from './SystemsRollupTab';
import { ScopeRollupTab } from './ScopeRollupTab';
import { RaidRollupTab } from './RaidRollupTab';
import { TimelineTab } from './TimelineTab';
import { ReportTab } from './ReportTab';

interface Props {
  release: ReleaseResponse;
}

export function EnterpriseTabs({ release }: Props) {
  const [tab, setTab] = useState('main');

  return (
    <Box>
      <Paper sx={{ mb: 2 }}>
        <Tabs
          value={tab}
          onChange={(_, v) => setTab(v)}
          variant="scrollable"
          scrollButtons="auto"
          sx={{ px: 2 }}
        >
          <Tab label="Main" value="main" />
          <Tab label="Members" value="members" />
          <Tab label="Gates & Test Phases" value="phases" />
          <Tab label="Environments" value="environments" />
          <Tab label="Linked Requests" value="requests" />
          <Tab label="Scope" value="scope" />
          <Tab label="Systems Impacted" value="systems" />
          <Tab label="Scope Rollup" value="scope_rollup" />
          <Tab label="RAID Rollup" value="raid_rollup" />
          <Tab label="Timeline" value="timeline" />
          <Tab label="Report" value="report" />
        </Tabs>
      </Paper>
      <Box>
        {tab === 'main' && <ReleaseMainTab releaseId={release.id} />}
        {tab === 'members' && <MembersTab release={release} />}
        {tab === 'phases' && <ReleasePlanTab releaseId={release.id} />}
        {tab === 'environments' && <ReleaseEnvironmentsTab releaseId={release.id} />}
        {tab === 'requests' && <ReleaseLinkedRequestsTab releaseId={release.id} />}
        {tab === 'scope' && <ReleaseScopeTab releaseId={release.id} />}
        {tab === 'systems' && <SystemsRollupTab release={release} />}
        {tab === 'scope_rollup' && <ScopeRollupTab release={release} onNavigateToReport={() => setTab('report')} />}
        {tab === 'raid_rollup' && <RaidRollupTab release={release} />}
        {tab === 'timeline' && <TimelineTab release={release} />}
        {tab === 'report' && <ReportTab release={release} />}
      </Box>
    </Box>
  );
}
