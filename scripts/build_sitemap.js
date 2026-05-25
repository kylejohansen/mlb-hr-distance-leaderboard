import { readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const SITE_URL = 'https://thelongball.app';
const OUTPUT_PATH = 'public/sitemap.xml';

const BASE_URLS = [
  '/',
  '/hot-dog-stand',
  '/notes',
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
  const files = await listFiles('public/data', (name) => name.endsWith('.json'));
  return files.map((filePath) => `/${filePath.replace(/^public\//, '')}`);
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
