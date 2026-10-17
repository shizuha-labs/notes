// @ts-check
const { test, expect } = require('./fixtures');

test.describe('Tags', () => {
  test('should navigate to tags page', async ({ authenticatedPage: page }) => {
    await page.goto('/notes/tags');

    // Should be on tags page
    await expect(page).toHaveURL(/\/tags/);
  });

  test('should display tags content', async ({ authenticatedPage: page }) => {
    await page.goto('/notes/tags');

    // Should show tags page content
    await expect(page.locator('text=/tag/i').first()).toBeVisible({ timeout: 10000 });
  });
});
