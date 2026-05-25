import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const POSTS_DIR = 'posts';
const OUTPUT_PATH = 'public/data/posts.json';
const NOTES_DOCS_DIR = 'public/docs/notes';
const NOTES_DOCS_INDEX = 'public/docs/notes.md';
const SITE_URL = 'https://thelongball.app';

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

function plainText(markdown) {
  return markdown
    .replaceAll(/`([^`]+)`/g, '$1')
    .replaceAll(/\*\*([^*]+)\*\*/g, '$1')
    .replaceAll(/\*([^*]+)\*/g, '$1')
    .replaceAll(/^#{1,6}\s+/gm, '')
    .replaceAll(/^- /gm, '')
    .replaceAll(/\s+/g, ' ')
    .trim();
}

function wordCount(value) {
  const text = plainText(value);
  return text ? text.split(/\s+/).length : 0;
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

    const title = metadata.title || fallbackTitle;
    const date = metadata.date || slug.slice(0, 10);
    const description = metadata.description || '';

    posts.push({
      type: 'Article',
      slug,
      title,
      date,
      author: metadata.author || 'The Long Ball',
      description,
      url: `${SITE_URL}/notes/${slug}`,
      markdownUrl: `${SITE_URL}/docs/notes/${slug}.md`,
      sourcePath: `${POSTS_DIR}/${filename}`,
      wordCount: wordCount(body),
      markdown: body,
      html: markdownToHtml(body)
    });
  }

  posts.sort((a, b) => b.date.localeCompare(a.date) || b.slug.localeCompare(a.slug));

  await mkdir(NOTES_DOCS_DIR, { recursive: true });
  await writeFile(
    NOTES_DOCS_INDEX,
    [
      '# Longball Notes Archive',
      '',
      ...posts.map((post) => `- [${post.title}](/docs/notes/${post.slug}.md) (${post.date})${post.description ? ` - ${post.description}` : ''}`),
      ''
    ].join('\n')
  );
  await Promise.all(posts.map((post) => writeFile(
    `${NOTES_DOCS_DIR}/${post.slug}.md`,
    [
      `Date: ${post.date}`,
      `Canonical URL: ${post.url}`,
      post.description ? `Description: ${post.description}` : '',
      '',
      post.markdown,
      ''
    ].filter(Boolean).join('\n')
  )));

  await mkdir(path.dirname(OUTPUT_PATH), { recursive: true });
  await writeFile(`${OUTPUT_PATH}`, `${JSON.stringify({
    site: {
      name: 'The Long Ball',
      url: SITE_URL
    },
    dataset: 'Longball Notes',
    description: 'Editorial notes and weekly commentary for The Long Ball.',
    fields: {
      type: 'Content type for the item.',
      slug: 'Stable post identifier derived from the markdown filename.',
      title: 'Post title.',
      date: 'Publication date in YYYY-MM-DD format.',
      author: 'Post author or publisher.',
      description: 'Short post summary from frontmatter.',
      url: 'Canonical in-app URL for the post.',
      markdownUrl: 'Static Markdown URL for crawlers and agents.',
      sourcePath: 'Markdown source path in the repository.',
      wordCount: 'Approximate word count calculated from markdown body.',
      html: 'Rendered HTML used by the static frontend.'
    },
    posts: posts.map(({ markdown, ...post }) => post)
  }, null, 2)}\n`);
  console.log(`Built ${posts.length} post${posts.length === 1 ? '' : 's'} -> ${OUTPUT_PATH}`);
}

await buildPosts();
