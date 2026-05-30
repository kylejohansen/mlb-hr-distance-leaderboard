import { readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const SITE_URL = 'https://thelongball.app';
const OUTPUT_PATH = 'public/sitemap.xml';

const BASE_URLS = [
  '/',
  '/hot-dog-stand',
  '/home-run-distance-leaderboard',
  '/longball-index',
  '/cheapies',
  '/daily-dong',
  '/stack-watch',
  '/notes',
  '/reports',
  '/about',
  '/about/longball-index',
  '/about/hot-dog-index',
  '/about/cheapies',
  '/about/daily-dong',
  '/about/hot-dog-robbery',
  '/about/cheapest-dong',
  '/llms.txt',
  '/docs/data-dictionary.md',
  '/docs/longball-index-methodology.md',
  '/docs/hot-dog-index-methodology.md',
  '/docs/notes.md',
  '/static/about.html',
  '/static/notes.html',
  '/static/stack-watch.html',
  '/static/reports.html',
  '/static/docs/data-dictionary.html',
  '/static/docs/longball-index-methodology.html',
  '/static/docs/hot-dog-index-methodology.html'
];

async function fileExists(filePath) {
  try {
    await readFile(filePath);
    return true;
  } catch {
    return false;
  }
}

async function listFiles(directory, predicate) {
  try {
    const entries = await readdir(directory, { withFileTypes: true });
    return entries
      .filter((entry) => entry.isFile() && predicate(entry.name))
      .map((entry) => path.join(directory, entry.name));
  } catch {
    return [];
  }
}

async function listFilesRecursive(directory, predicate) {
  let entries = [];

  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch {
    return [];
  }

  const files = [];
  for (const entry of entries) {
    const filePath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...await listFilesRecursive(filePath, predicate));
    } else if (entry.isFile() && predicate(entry.name)) {
      files.push(filePath);
    }
  }
  return files;
}

async function postUrls() {
  if (!(await fileExists('public/data/posts.json'))) return [];
  const payload = JSON.parse(await readFile('public/data/posts.json', 'utf8'));
  const posts = Array.isArray(payload.posts) ? payload.posts : [];
  return posts.flatMap((post) => {
    if (!post.slug) return [];
    return [
      `/notes/${post.slug}`,
      `/docs/notes/${post.slug}.md`,
      `/static/notes/${post.slug}.html`
    ];
  });
}

async function dataUrls() {
  const files = await listFilesRecursive('public/data', (name) => name.endsWith('.json'));
  return files.map((filePath) => `/${filePath.replace(/^public\//, '')}`);
}

async function taleOfTheTapeUrls() {
  const files = await listFiles('public/data/tale-of-the-tape', (name) => name.endsWith('.json'));
  return files.flatMap((filePath) => {
    const slug = path.basename(filePath, '.json');
    return [
      `/tale-of-the-tape/${slug}`,
      `/static/tale-of-the-tape/${slug}.html`
    ];
  });
}

async function reportUrls() {
  const files = await listFiles('content/reports', (name) => name.endsWith('-longball-scouting-report.md'));
  const urls = files.flatMap((filePath) => {
    const slug = path.basename(filePath, '.md');
    return [
      `/reports/${slug}`,
      `/static/reports/${slug}.html`
    ];
  });
  if (files.length) {
    urls.push('/reports/latest-longball-scouting-report');
    urls.push('/static/reports/latest-longball-scouting-report.html');
  }
  return urls;
}

function absoluteUrl(pathname) {
  return `${SITE_URL}${pathname}`;
}

function xmlEscape(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}

async function buildSitemap() {
  const urls = [...new Set([
    ...BASE_URLS,
    ...(await postUrls()),
    ...(await reportUrls()),
    ...(await taleOfTheTapeUrls()),
    ...(await dataUrls())
  ])].sort((a, b) => {
    if (a === '/') return -1;
    if (b === '/') return 1;
    return a.localeCompare(b);
  });

  const xml = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...urls.map((url) => `  <url>\n    <loc>${xmlEscape(absoluteUrl(url))}</loc>\n  </url>`),
    '</urlset>',
    ''
  ].join('\n');

  await writeFile(OUTPUT_PATH, xml);
  console.log(`Built ${urls.length} sitemap URL${urls.length === 1 ? '' : 's'} -> ${OUTPUT_PATH}`);
}

await buildSitemap();
