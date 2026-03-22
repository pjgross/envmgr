import { test, expect } from '@playwright/test'

// Credentials created by seed_e2e.py
const TENANT = 'e2e'
const USERNAME = 'e2eadmin'
const PASSWORD = 'e2epassword123'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function login(page: any, tenant = TENANT, username = USERNAME, password = PASSWORD) {
  await page.goto('/login')
  await page.getByLabel('Tenant').fill(tenant)
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: /login/i }).click()
}

// ---------------------------------------------------------------------------
// Login page rendering
// ---------------------------------------------------------------------------

test('login page shows all required fields', async ({ page }) => {
  await page.goto('/login')

  await expect(page).toHaveTitle(/EnvManager|Vite/i)
  await expect(page.getByText('EnvManager')).toBeVisible()
  await expect(page.getByLabel('Tenant')).toBeVisible()
  await expect(page.getByLabel('Username')).toBeVisible()
  await expect(page.getByLabel('Password')).toBeVisible()
  await expect(page.getByRole('button', { name: /login/i })).toBeVisible()
})

// ---------------------------------------------------------------------------
// Unauthenticated access
// ---------------------------------------------------------------------------

test('unauthenticated root redirects to /login', async ({ page }) => {
  // Each test gets a fresh browser context with no localStorage — no manual clearing needed
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
})

test('unauthenticated access to /dashboard redirects to /login', async ({ page }) => {
  await page.goto('/dashboard')
  await expect(page).toHaveURL(/\/login/)
})

// ---------------------------------------------------------------------------
// Successful login
// ---------------------------------------------------------------------------

test('valid credentials log in and redirect to /dashboard', async ({ page }) => {
  await login(page)

  await expect(page).toHaveURL(/\/dashboard/)
  await expect(page.getByText('Dashboard')).toBeVisible()
})

test('dashboard shows the logged-in username', async ({ page }) => {
  await login(page)

  await expect(page.getByText(USERNAME)).toBeVisible()
})

test('dashboard shows the user role', async ({ page }) => {
  await login(page)

  // AppBar shows "username (role)"
  await expect(page.getByText(/Admin/)).toBeVisible()
})

test('dashboard renders the four metric panels', async ({ page }) => {
  await login(page)

  // Use role heading to avoid matching sub-text like "Total environments"
  await expect(page.getByRole('heading', { name: 'Environments' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Bookings' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Changes' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Releases' })).toBeVisible()
})

// ---------------------------------------------------------------------------
// Failed login
// ---------------------------------------------------------------------------

test('wrong password shows an error alert', async ({ page }) => {
  await login(page, TENANT, USERNAME, 'wrongpassword')

  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page).toHaveURL(/\/login/)
})

test('unknown username shows an error alert', async ({ page }) => {
  await login(page, TENANT, 'nobody', PASSWORD)

  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page).toHaveURL(/\/login/)
})

test('unknown tenant shows an error alert', async ({ page }) => {
  await login(page, 'no-such-tenant', USERNAME, PASSWORD)

  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page).toHaveURL(/\/login/)
})

// ---------------------------------------------------------------------------
// Logout
// ---------------------------------------------------------------------------

test('logout button returns to /login', async ({ page }) => {
  await login(page)
  await expect(page).toHaveURL(/\/dashboard/)

  await page.getByRole('button', { name: /logout/i }).click()
  await expect(page).toHaveURL(/\/login/)
})

test('after logout, /dashboard redirects to /login', async ({ page }) => {
  await login(page)
  await page.getByRole('button', { name: /logout/i }).click()
  await expect(page).toHaveURL(/\/login/)

  await page.goto('/dashboard')
  await expect(page).toHaveURL(/\/login/)
})

// ---------------------------------------------------------------------------
// Session persistence
// ---------------------------------------------------------------------------

test('token persists across page reload', async ({ page }) => {
  await login(page)
  await expect(page).toHaveURL(/\/dashboard/)

  // Hard reload — should remain on /dashboard (token in localStorage)
  await page.reload()
  await expect(page).toHaveURL(/\/dashboard/)
  await expect(page.getByText('Dashboard')).toBeVisible()
})
