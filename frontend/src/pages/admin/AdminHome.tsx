import { Box, Card, CardContent, Grid, Link, List, ListItem, ListItemText, Stack, Typography } from '@mui/material';
import { useSelector } from 'react-redux';
import { Link as RouterLink } from 'react-router-dom';
import type { RootState } from '../../store';
import { visibleAdminNav } from '../../components/adminNavConfig';

/** `/admin` — generated from adminNav so it can never disagree with the drawer. */
export default function AdminHome() {
  const user = useSelector((state: RootState) => state.auth.user);
  const sections = visibleAdminNav(user);

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        Administration
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Tenant configuration, people and integrations.
      </Typography>
      <Grid container spacing={2}>
        {sections.map((section) => (
          <Grid item xs={12} md={6} lg={4} key={section.label}>
            <Card variant="outlined" sx={{ height: '100%' }}>
              <CardContent>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                  {section.icon}
                  <Typography variant="h6" component="h2">
                    {section.label}
                  </Typography>
                </Stack>
                <List dense disablePadding>
                  {section.children.map((item) => (
                    <ListItem key={item.path} disableGutters>
                      <ListItemText
                        primary={
                          <Link component={RouterLink} to={item.path} underline="hover">
                            {item.label}
                          </Link>
                        }
                        secondary={item.description}
                      />
                    </ListItem>
                  ))}
                </List>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}
