import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const POSTS_DIR = 'posts';
const OUTPUT_PATH = 'public/data/posts.json';

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function parseFrontmatter(source) {
  if (!source.startsWith('---\n')) {
    return [{}, source];
  }

  const end = source.indexOf('\n---\n', 4);
  if (end === -1) {
    return [{}, source];
  }

  const raw = source.slice(4, end);
  const body = source.slice(end + 5).trim();
  const metadata = {};

  raw.split('\n').forEach((line) => {
    const separator = line.indexOf(':');
    if (separator === -1) return;
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim();
    metadata[key] = value.replace(/^["']|["']$/g, '');
  });

  return [metadata, body];
}

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replaceAll(/`([^`]+)`/g, '<code>$1</code>')
    .replaceAll(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replaceAll(/\*([^*]+)\*/g, '<em>$1</em>');
}

function markdownToHtml(markdown) {
  const blocks = markdown.split(/\n{2,}/);
  const html = [];

  for (const block of blocks) {
    const trimmed = block.trim();
    if (!trimmed) continue;

    if (trimmed.startsWith('### ')) {
      html.push(`<h3>${inlineMarkdown(trimmed.slice(4))}</h3>`);
    } else if (trimmed.startsWith('## ')) {
      html.push(`<h2>${inlineMarkdown(trimmed.slice(3))}</h2>`);
    } else if (trimmed.startsWith('# ')) {
      html.push(`<h1>${inlineMarkdown(trimmed.slice(2))}</h1>`);
    } else if (trimmed.split('\n').every((line) => line.startsWith('- '))) {
      const items = trimmed
        .split('\n')
        .map((line) => `<li>${inlineMarkdown(line.slice(2))}</li>`)
        .join('');
      html.push(`<ul>${items}</ul>`);
    } else {
      html.push(`<p>${inlineMarkdown(trimmed.replaceAll('\n', ' '))}</p>`);
    }
  }

  return html.join('\n');
}

async function buildPosts() {
  let filenames = [];

  try {
    filenames = await readdir(POSTS_DIR);
  } catch {
    filenames = [];
  }

  const posts = [];

  for (const filename of filenames.filter((name) => name.endsWith('.md')).sort()) {
    const slug = filename.replace(/\.md$/, '');
    const source = await readFile(path.join(POSTS_DIR, filename), 'utf8');
    const [metadata, body] = parseFrontmatter(source);
    const fallbackTitle = slug
      .replace(/^\d{4}-\d{2}-\d{2}-/, '')
      .replaceAll('-', ' ')
      .replace(/\b\w/g, (letter) => letter.toUpperCase());

    posts.push({
      slug,
      title: metadata.title || fallbackTitle,
      date: metadata.date || slug.slice(0, 10),
      description: metadata.description || '',
      html: markdownToHtml(body)
    });
  }

  posts.sort((a, b) => b.date.localeCompare(a.date) || b.slug.localeCompare(a.slug));

  await mkdir(path.dirname(OUTPUT_PATH), { recursive: true });
  await writeFile(`${OUTPUT_PATH}`, `${JSON.stringify({ posts }, null, 2)}\n`);
  console.log(`Built ${posts.length} post${posts.length === 1 ? '' : 's'} -> ${OUTPUT_PATH}`);
}

await buildPosts();
