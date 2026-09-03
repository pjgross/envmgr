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

  it('renders a placeholder, never an empty h1, while title is absent', () => {
    // Every consumer's fetched title starts out `undefined`/null-derived —
    // the component owns the empty case rather than forcing `?? ''` at 53
    // call sites, which would render a heading with no accessible name.
    at('/environments', <PageHeader />);
    const headings = screen.getAllByRole('heading', { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).not.toHaveAccessibleName('');
    expect(document.title).not.toMatch(/^ ·/);
    expect(document.title).toBe('Environments · EnvManager');
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
    // Exact match, not two `toContain`s: those would still pass with the
    // parts in the wrong order (e.g. "EnvManager · Mortgage_SIT").
    expect(document.title).toBe('Mortgage_SIT · Environments · EnvManager');
  });

  it('renders a placeholder, never an empty h1, while title is absent', () => {
    // Every detail page's entity is typed `T | null`, and its loading guard
    // leaves a window where the page renders on with a null entity —
    // DetailPageHeader owns that case rather than forcing `?? ''` at every
    // one of its 13 call sites, which would render an unnamed heading.
    at('/environments/2', <DetailPageHeader back={{ to: '/environments', label: 'Environments' }} />);
    const headings = screen.getAllByRole('heading', { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).not.toHaveAccessibleName('');
    // No override means usePageTitle falls back to the route trail — never
    // a leading " · " from an empty override.
    expect(document.title).not.toMatch(/^ ·/);
    expect(document.title).toBe('Environment · Environments · EnvManager');
  });
});
