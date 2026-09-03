import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import PageHeader from '../PageHeader';
import DetailPageHeader from '../DetailPageHeader';

// `ReactNode`, not `React.ReactNode`: the new JSX transform does not bring the
// React namespace into scope for types.
const at = (path: string, ui: ReactNode) =>
  render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);

describe('PageHeader', () => {
  it('renders the title as the page h1 (audit P3-8)', () => {
    at('/environments', <PageHeader title="Environments" />);
    expect(screen.getByRole('heading', { level: 1, name: 'Environments' })).toBeInTheDocument();
  });

  it('renders breadcrumbs from the route, not from props', () => {
    at('/admin/environments', <PageHeader title="Environments" />);
    expect(screen.getByRole('link', { name: 'Administration' })).toHaveAttribute('href', '/admin');
  });

  it('renders actions', () => {
    at('/environments', <PageHeader title="Environments" actions={<button>New</button>} />);
    expect(screen.getByRole('button', { name: 'New' })).toBeInTheDocument();
  });
});

describe('DetailPageHeader', () => {
  it('links back to an explicit target', () => {
    // Never history.back(): after a create, that lands on the form.
    at('/environments/2', <DetailPageHeader back={{ to: '/environments', label: 'Environments' }} title="Mortgage_SIT" />);
    // Named, and a real link: an icon with only a click handler has no
    // accessible name and no keyboard route.
    expect(screen.getByRole('link', { name: 'Back to Environments' })).toHaveAttribute(
      'href',
      '/environments',
    );
  });

  it('renders the entity name as h1', () => {
    at('/environments/2', <DetailPageHeader back={{ to: '/environments', label: 'Environments' }} title="Mortgage_SIT" />);
    expect(screen.getByRole('heading', { level: 1, name: 'Mortgage_SIT' })).toBeInTheDocument();
  });

  it('puts the entity name in the document title', () => {
    at('/environments/2', <DetailPageHeader back={{ to: '/environments', label: 'Environments' }} title="Mortgage_SIT" />);
    expect(document.title).toContain('Mortgage_SIT');
    expect(document.title).toContain('EnvManager');
  });
});
