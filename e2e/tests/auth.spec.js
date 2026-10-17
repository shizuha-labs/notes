// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('Authentication', () => {
  test('should redirect to login when not authenticated', async ({ page }) => {
    // Navigate to Notes without authentication
    await page.goto('/notes/');

    // Should redirect to Shizuha ID login
    await expect(page).toHaveURL(/\/id\/login/, { timeout: 10000 });
  });

  test('should load login page', async ({ page }) => {
    await page.goto('/id/login/');

    // Wait for React app to load
    await page.waitForLoadState('networkidle');

    // Should have some login-related content
    await expect(page.locator('text=/login|sign in/i').first()).toBeVisible({ timeout: 10000 });
  });
});
