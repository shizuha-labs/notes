// @ts-check
const { test, expect } = require('./fixtures');

test.describe('Trash', () => {
  test('should navigate to trash page', async ({ authenticatedPage: page }) => {
    await page.goto('/notes/trash');

    // Should be on trash page
    await expect(page).toHaveURL(/\/trash/);
  });

  test('should display trash content', async ({ authenticatedPage: page }) => {
    await page.goto('/notes/trash');

    // Should show trash page content
    await expect(page.locator('text=/trash|deleted/i').first()).toBeVisible({ timeout: 10000 });
  });
});
