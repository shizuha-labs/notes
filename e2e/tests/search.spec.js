// @ts-check
const { test, expect } = require('./fixtures');

test.describe('Search', () => {
  test('should navigate to search page', async ({ authenticatedPage: page }) => {
    await page.goto('/notes/search');

    // Should be on search page
    await expect(page).toHaveURL(/\/search/);
  });

  test('should display search input', async ({ authenticatedPage: page }) => {
    await page.goto('/notes/search');

    // Should have search input
    await expect(page.locator('input[type="search"], input[placeholder*="search" i]').first()).toBeVisible({ timeout: 10000 });
  });
});
