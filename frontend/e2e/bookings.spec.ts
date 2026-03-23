import { test, expect } from '@playwright/test'

const TENANT = 'e2e'
const USERNAME = 'e2eadmin'
const PASSWORD = 'e2epassword123'

async function login(page: any) {
  await page.goto('/login')
  await page.getByLabel('Tenant').fill(TENANT)
  await page.getByLabel('Username').fill(USERNAME)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: /login/i }).click()
  await expect(page).toHaveURL(/\/dashboard/)
}

// --- Navigation ---

test('Bookings nav group expands on click', async ({ page }) => {
  await login(page)

  // Verify sub-items are not visible initially (group collapsed)
  await expect(page.getByRole('button', { name: 'Calendar' })).not.toBeVisible()

  // Click the parent group item
  await page.getByRole('button', { name: 'Bookings' }).click()

  // Sub-items should now be visible
  await expect(page.getByRole('button', { name: 'Calendar' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'List' })).toBeVisible()
})

test('/bookings redirects to /bookings/calendar', async ({ page }) => {
  await login(page)
  await page.goto('/bookings')
  await expect(page).toHaveURL(/\/bookings\/calendar/)
})

test('clicking Bookings > Calendar navigates to calendar view', async ({ page }) => {
  await login(page)
  await page.getByRole('button', { name: 'Bookings' }).click()
  await page.getByRole('button', { name: 'Calendar' }).click()
  await expect(page).toHaveURL(/\/bookings\/calendar/)
})

test('clicking Bookings > List navigates to list view', async ({ page }) => {
  await login(page)
  await page.getByRole('button', { name: 'Bookings' }).click()
  await page.getByRole('button', { name: 'List' }).click()
  await expect(page).toHaveURL(/\/bookings\/list/)
})

// --- List view ---

test('Bookings list renders the data grid', async ({ page }) => {
  await login(page)
  await page.goto('/bookings/list')

  // DataGrid renders a grid
  await expect(page.locator('[role="grid"]')).toBeVisible()

  // Core column headers are present
  await expect(page.getByRole('columnheader', { name: 'Project' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible()
})

test('status filter chips are visible on the list view', async ({ page }) => {
  await login(page)
  await page.goto('/bookings/list')

  // Scope to the header area containing the status chips (above the grid)
  const header = page.locator('text=Status:').locator('..')
  await expect(header.getByText('All')).toBeVisible()
  await expect(header.getByText('Pending')).toBeVisible()
  await expect(header.getByText('Approved')).toBeVisible()
  await expect(header.getByText('Rejected')).toBeVisible()
})

test('New Booking button opens the booking form dialog', async ({ page }) => {
  await login(page)
  await page.goto('/bookings/list')

  await page.getByRole('button', { name: /new booking/i }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
})

test('Bookings group auto-expands when navigating directly to /bookings/list', async ({ page }) => {
  await login(page)
  await page.goto('/bookings/list')

  // Both sub-items should be visible without clicking the group
  await expect(page.getByRole('button', { name: 'Calendar' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'List' })).toBeVisible()
})
