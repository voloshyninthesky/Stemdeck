import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { chromium } from 'playwright-core';

const BASE_URL = process.env.E2E_BASE_URL || 'http://127.0.0.1:8000';
const CHROMIUM_PATH =
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || '/Applications/Chromium.app/Contents/MacOS/Chromium';

const makeTestWav = async () => {
  const dir = await mkdtemp(join(tmpdir(), 'stemdeck-e2e-'));
  const file = join(dir, 'tiny.wav');
  const sampleRate = 8000;
  const durationSeconds = 0.25;
  const samples = sampleRate * durationSeconds;
  const dataBytes = samples * 2;
  const buffer = Buffer.alloc(44 + dataBytes);

  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + dataBytes, 4);
  buffer.write('WAVE', 8);
  buffer.write('fmt ', 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(dataBytes, 40);

  for (let i = 0; i < samples; i += 1) {
    const value = Math.round(Math.sin((2 * Math.PI * 440 * i) / sampleRate) * 16000);
    buffer.writeInt16LE(value, 44 + i * 2);
  }

  await writeFile(file, buffer);
  return { dir, file };
};

test('Stemdeck auth, language, process, and upload controls work', async () => {
  const browser = await chromium.launch({ executablePath: CHROMIUM_PATH, headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  const pageErrors = [];
  const failedRequests = [];

  page.on('console', (msg) => console.log('PAGE LOG:', msg.text()));
  page.on('pageerror', (error) => {
    console.error('PAGE ERROR:', error.stack || error.message);
    pageErrors.push(error.message);
  });
  page.on('requestfailed', (request) => {
    console.warn('REQUEST FAILED:', request.method(), request.url());
    failedRequests.push(`${request.method()} ${request.url()}`);
  });

  try {
    await page.goto(`${BASE_URL}/?username=leak&password=secret`, { waitUntil: 'networkidle' });
    const cleanedUrl = new URL(page.url());
    assert.equal(cleanedUrl.searchParams.has('username'), false, 'username query param should be removed');
    assert.equal(cleanedUrl.searchParams.has('password'), false, 'password query param should be removed');
    await page.locator('#authSection').waitFor({ state: 'hidden', timeout: 5000 });
    await page.locator('#logoutBtn').waitFor({ state: 'hidden', timeout: 5000 });
    await page.locator('#authToggleBtn').waitFor({ state: 'visible', timeout: 5000 });
    await page.getByRole('button', { name: 'Process' }).click();
    await assertVisibleText(page, 'Choose a file or enter a YouTube link first.');

    await page.locator('#authToggleBtn').click();
    await page.locator('#authSection').waitFor({ state: 'visible', timeout: 5000 });

    const username = `e2e_${Date.now()}`;
    await page.getByLabel('Username').fill(username);
    await page.getByLabel('Password').fill('password123');

    const registerResponse = page.waitForResponse(
      (response) => response.url().endsWith('/api/register') && response.request().method() === 'POST'
    );
    await page.getByRole('button', { name: /create account|sign up/i }).click();
    assert.equal((await registerResponse).ok(), true, 'register should succeed');
    await assertVisibleText(page, username);

    const logoutResponse = page.waitForResponse(
      (response) => response.url().endsWith('/api/logout') && response.request().method() === 'POST'
    );
    await page.getByRole('button', { name: /logout/i }).click();
    assert.equal((await logoutResponse).ok(), true, 'logout should succeed');
    await page.locator('#authToggleBtn').waitFor({ state: 'visible', timeout: 5000 });
    await page.locator('#authSection').waitFor({ state: 'hidden', timeout: 5000 });

    await page.locator('#authToggleBtn').click();
    await page.getByLabel('Username').fill(username);
    await page.getByLabel('Password').fill('password123');
    const loginResponse = page.waitForResponse(
      (response) => response.url().endsWith('/api/login') && response.request().method() === 'POST'
    );
    await page.locator('#loginBtn').click();
    assert.equal((await loginResponse).ok(), true, 'login should succeed');
    await assertVisibleText(page, username);

    await page.getByRole('button', { name: 'Українська' }).click();
    await assertVisibleText(page, 'Аудіо або відео');
    await assertVisibleText(page, 'Запустити');

    await page.getByRole('button', { name: 'English' }).click();
    await assertVisibleText(page, 'Upload audio or video');
    await assertVisibleText(page, 'Process');

    await page.getByRole('button', { name: 'Process' }).click();
    await assertVisibleText(page, 'Choose a file or enter a YouTube link first.');

    const wav = await makeTestWav();
    try {
      await page.locator('#audioFile').setInputFiles(wav.file);
      const uploadResponse = page.waitForResponse(
        (response) => response.url().endsWith('/api/jobs') && response.request().method() === 'POST'
      );
      await page.getByRole('button', { name: 'Process' }).click();
      assert.equal((await uploadResponse).ok(), true, 'upload should queue a job');
      await assertVisibleText(page, 'tiny.wav');
    } finally {
      await rm(wav.dir, { recursive: true, force: true });
    }

    assert.deepEqual(pageErrors, [], 'browser page errors should be empty');
    assert.deepEqual(failedRequests, [], 'browser request failures should be empty');
  } finally {
    await context.close();
    await browser.close();
  }
});

const assertVisibleText = async (page, text) => {
  await page.getByText(text, { exact: false }).first().waitFor({ state: 'visible', timeout: 5000 });
};
